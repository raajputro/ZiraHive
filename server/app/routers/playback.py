"""Playing anything: track lists, HLS transcoding, subtitles, offline copies, markers, ratings."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Library, MediaItem, OfflineCopy, Series, User, utcnow
from ..schemas import MarkersIn, OfflineIn, OfflineOut, RatingIn, SeriesOut, TracksOut
from ..security import admin_user, current_user
from ..services import activity, jobs, transcode
from ..services.events import audit
from ..services.ranged import ranged_file_response
from ..services.tracks import probe_tracks, to_vtt
from .media import _get_media, browser_playable, get_series

router = APIRouter(prefix="/api", tags=["playback"])
_safe = re.compile(r"[^\w\-. ()]+")


async def _source(session: AsyncSession, item: MediaItem) -> Path:
    lib = await session.get(Library, item.library_id)
    root = Path(lib.path).resolve()
    path = (root / item.rel_path).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "The video file is missing. Is the drive connected?")
    return path


async def _tracks(session: AsyncSession, item: MediaItem, src: Path) -> dict:
    if not item.tracks_json:
        item.tracks_json = json.dumps(await asyncio.to_thread(probe_tracks, src))
        await session.commit()
    return json.loads(item.tracks_json)


@router.get("/media/{media_id}/tracks", response_model=TracksOut)
async def media_tracks(media_id: str, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session, user)
    tracks = await _tracks(session, item, await _source(session, item))
    return TracksOut(audio=tracks["audio"], subtitles=[s for s in tracks["subtitles"]],
                     qualities=transcode.qualities_for(item.height), direct_play=browser_playable(item),
                     encoder=transcode.encoder())


# ------------------------------------------------------------------- HLS

async def _session_for(session: AsyncSession, user: User, media_id: str, quality: str, audio: int):
    if quality not in transcode.QUALITIES:
        raise HTTPException(404, "Unknown quality")
    item = await _get_media(media_id, session, user)
    if not item.duration:
        raise HTTPException(409, "This file's length is unknown, so it can't be converted")
    src = await _source(session, item)
    try:
        return item, transcode.manager.session(item.id, item.title, src, item.duration, item.height,
                                               quality, audio, user.username)
    except transcode.TooBusy:
        raise HTTPException(503, "The server is converting too many videos right now. Try again in a minute, "
                                 "or pick Original quality.", headers={"Retry-After": "30"})


@router.get("/media/{media_id}/hls/{quality}/{audio}/index.m3u8")
async def hls_playlist(media_id: str, quality: str, audio: int, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    item, _ = await _session_for(session, user, media_id, quality, audio)
    return PlainTextResponse(transcode.playlist(item.duration), media_type="application/vnd.apple.mpegurl",
                             headers={"Cache-Control": "no-cache"})


@router.get("/media/{media_id}/hls/{quality}/{audio}/seg/{n}.ts")
async def hls_segment(media_id: str, quality: str, audio: int, n: int, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    item, s = await _session_for(session, user, media_id, quality, audio)
    if n < 0 or n >= transcode.segment_count(item.duration):
        raise HTTPException(404, "No such segment")
    activity.stream_seen(user.id, user.username, item.id, item.title)
    await session.close()  # don't hold a database connection while ffmpeg works
    try:
        path = await transcode.manager.segment(s, n)
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(500, f"Couldn't convert this part of the video: {exc}")
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------- subtitles

@router.get("/media/{media_id}/subtitles/{sub_id}.vtt")
async def subtitle(media_id: str, sub_id: str, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session, user)
    src = await _source(session, item)
    tracks = await _tracks(session, item, src)
    sub = next((s for s in tracks["subtitles"] if s["id"] == sub_id), None)
    if sub is None or not sub["usable"]:
        raise HTTPException(404, "Subtitle not available")
    from ..config import get_settings
    dest = get_settings().cache_dir / "subtitles" / f"{item.id}-{sub_id}.vtt"
    if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
        try:
            await asyncio.to_thread(to_vtt, src, sub, dest)
        except Exception as exc:
            raise HTTPException(500, f"Couldn't read these subtitles: {exc}")
    return FileResponse(dest, media_type="text/vtt", headers={"Cache-Control": "private, max-age=86400"})


# --------------------------------------------------------- offline copies

def _copy_name(item: MediaItem, quality: str) -> str:
    base = item.title + (f" ({item.year})" if item.year else "")
    if item.series_id and item.episode is not None:
        base = f"{item.title} S{item.season or 1:02d}E{item.episode:02d}"
    return _safe.sub("", base).strip() + f" {quality}.mp4"


@router.get("/media/{media_id}/offline", response_model=list[OfflineOut])
async def offline_copies(media_id: str, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session, user)
    return (await session.scalars(select(OfflineCopy).where(OfflineCopy.media_id == item.id))).all()


@router.post("/media/{media_id}/offline", response_model=OfflineOut, status_code=202)
async def request_offline(media_id: str, body: OfflineIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    """Make (or reuse) a smaller MP4 to download and watch without internet."""
    item = await _get_media(media_id, session, user)
    await _source(session, item)
    copy = await session.scalar(select(OfflineCopy).where(
        OfflineCopy.media_id == item.id, OfflineCopy.quality == body.quality))
    if copy and copy.status in ("queued", "working", "ready"):
        return copy
    if copy is None:
        copy = OfflineCopy(media_id=item.id, quality=body.quality, requested_by=user.id)
        session.add(copy)
    copy.status, copy.progress, copy.error = "queued", 0, None
    await session.commit()
    await jobs.enqueue("make_offline_copy", copy.id)
    return copy


@router.get("/offline/{copy_id}/file")
async def download_offline(copy_id: str, request: Request, user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    copy = await session.get(OfflineCopy, copy_id)
    if copy is None or copy.status != "ready":
        raise HTTPException(404, "Not ready")
    item = await _get_media(copy.media_id, session, user)
    copy.last_used_at = utcnow()
    await session.commit()
    path = transcode.offline_path(item.id, copy.quality)
    return ranged_file_response(request, path, "video/mp4", _copy_name(item, copy.quality), inline=False)


@router.delete("/offline/{copy_id}", status_code=204)
async def delete_offline(copy_id: str, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    copy = await session.get(OfflineCopy, copy_id)
    if copy is None:
        raise HTTPException(404, "Not found")
    if not user.is_admin and copy.requested_by != user.id:
        raise HTTPException(403, "Only the person who made it, or an admin, can delete it")
    transcode.offline_path(copy.media_id, copy.quality).unlink(missing_ok=True)
    await session.delete(copy)
    await session.commit()


# ------------------------------------------------- admin: ratings, markers

@router.put("/media/{media_id}/rating", status_code=204)
async def set_media_rating(media_id: str, body: RatingIn, request: Request, admin: User = Depends(admin_user),
                           session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session)
    item.age_rating = body.age_rating
    await audit(session, "rating_set", admin, detail=f"{item.title}: {body.age_rating}", request=request)
    await session.commit()


@router.put("/series/{series_id}/rating", status_code=204)
async def set_series_rating(series_id: str, body: RatingIn, request: Request, admin: User = Depends(admin_user),
                            session: AsyncSession = Depends(get_session)):
    series = await session.get(Series, series_id)
    if series is None:
        raise HTTPException(404, "Series not found")
    series.age_rating = body.age_rating
    await audit(session, "rating_set", admin, detail=f"{series.title}: {body.age_rating}", request=request)
    await session.commit()


@router.put("/series/{series_id}/markers", response_model=SeriesOut)
async def set_series_markers(series_id: str, body: MarkersIn, admin: User = Depends(admin_user),
                             session: AsyncSession = Depends(get_session)):
    """Where the intro is, and how long the end credits are, for every episode of a series."""
    series = await session.get(Series, series_id)
    if series is None:
        raise HTTPException(404, "Series not found")
    if body.intro_end is not None and (body.intro_start or 0) >= body.intro_end:
        raise HTTPException(400, "The intro has to end after it starts")
    series.intro_start, series.intro_end = body.intro_start, body.intro_end
    series.credits_before_end = body.credits_before_end
    await session.commit()
    return await get_series(series_id, admin, session)

