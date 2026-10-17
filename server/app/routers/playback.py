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
from ..models import Library, MediaItem, OfflineCopy, Series, User, WatchProgress, utcnow
from ..schemas import CastOut, CastSubtitle, MarkersIn, OfflineIn, OfflineOut, RatingIn, SeriesOut, TracksOut
from ..security import admin_user, create_media_token, current_user
from ..services import activity, jobs, transcode
from ..services.events import audit
from ..services.ranged import ranged_file_response
from ..services.ai_jobs import subtitle_path
from ..services.tracks import language_name, probe_tracks, to_vtt
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
    data = json.loads(item.tracks_json)
    if (item.ai_subtitles or "").startswith("done:") and subtitle_path(item.id).exists():
        lang = language_name(item.ai_subtitles[5:])
        data["subtitles"].append({"id": "ai", "source": "ai", "label": f"{lang or 'Speech'} (AI)", "language": lang,
                                  "usable": True, "forced": False})
    return data


@router.get("/media/{media_id}/tracks", response_model=TracksOut)
async def media_tracks(media_id: str, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session, user)
    tracks = await _tracks(session, item, await _source(session, item))
    return TracksOut(audio=tracks["audio"], subtitles=[s for s in tracks["subtitles"]],
                     qualities=transcode.qualities_for(item.height), direct_play=browser_playable(item),
                     encoder=transcode.encoder(), ai_subtitles=item.ai_subtitles)


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


def _device_headers(request: Request, headers: dict) -> dict:
    """A Chromecast fetches with its own player page, from another origin: allow that for the
    one-title links (?token=), which only work for this title anyway."""
    if request.query_params.get("token"):
        headers["Access-Control-Allow-Origin"] = "*"
    return headers


@router.get("/media/{media_id}/hls/{quality}/{audio}/index.m3u8")
async def hls_playlist(media_id: str, quality: str, audio: int, request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    item, _ = await _session_for(session, user, media_id, quality, audio)
    token = request.query_params.get("token")
    query = f"?token={token}" if token else ""  # devices without cookies need it on every segment
    return PlainTextResponse(transcode.playlist(item.duration, query), media_type="application/vnd.apple.mpegurl",
                             headers=_device_headers(request, {"Cache-Control": "no-cache"}))


@router.get("/media/{media_id}/hls/{quality}/{audio}/seg/{n}.ts")
async def hls_segment(media_id: str, quality: str, audio: int, n: int, request: Request,
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    item, s = await _session_for(session, user, media_id, quality, audio)
    if n < 0 or n >= transcode.segment_count(item.duration):
        raise HTTPException(404, "No such segment")
    activity.stream_seen(user.id, user.username, item.id, item.title)
    await session.close()  # don't hold a database connection while ffmpeg works
    try:
        path = await transcode.manager.segment(s, n)
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(500, f"Couldn't convert this part of the video: {exc}")
    return FileResponse(path, media_type="video/mp2t",
                        headers=_device_headers(request, {"Cache-Control": "private, max-age=3600"}))


# ------------------------------------------------------------- subtitles

@router.get("/media/{media_id}/subtitles/{sub_id}.vtt")
async def subtitle(media_id: str, sub_id: str, request: Request, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session, user)
    if sub_id == "ai":  # made by Whisper (Settings: local AI)
        path = subtitle_path(item.id)
        if not path.exists():
            raise HTTPException(404, "Subtitle not available")
        return FileResponse(path, media_type="text/vtt",
                            headers=_device_headers(request, {"Cache-Control": "private, max-age=3600"}))
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
    return FileResponse(dest, media_type="text/vtt",
                        headers=_device_headers(request, {"Cache-Control": "private, max-age=86400"}))


# ------------------------------------------------------------ Chromecast

_PRIVATE = re.compile(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)")
_CASTABLE = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4", ".webm": "video/webm"}


def device_base_url(request: Request) -> str:
    """The address TVs and Chromecasts on the home network can reach ZiraHive at."""
    from ..config import get_settings

    configured = get_settings().lan_url.strip().rstrip("/")
    if configured:
        return configured
    host = request.url.hostname or ""
    if _PRIVATE.match(host):
        return str(request.base_url).rstrip("/")
    raise HTTPException(409, {"code": "lan_url_needed", "message":
                              "To cast, ZiraHive needs this PC's home-network address. Set ZIRAHIVE_LAN_URL "
                              "in .env (setup.ps1 fills it in) and restart ZiraHive."})


@router.get("/media/{media_id}/cast", response_model=CastOut)
async def cast_info(media_id: str, request: Request, quality: str | None = None, audio: int | None = None,
                    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Links for a Chromecast: the file itself when it can play it, otherwise the converted
    stream, plus poster and subtitles. They work only for this title, for 12 hours."""
    item = await _get_media(media_id, session, user)
    base = device_base_url(request)
    src = await _source(session, item)
    tracks = await _tracks(session, item, src)
    default_audio = next((a["index"] for a in tracks["audio"] if a.get("default")), 0)
    audio = default_audio if audio is None else audio
    token = create_media_token(user, item.id)
    t = f"token={token}"
    ext = Path(item.rel_path).suffix.lower()
    direct = (browser_playable(item) and ext in _CASTABLE and audio == default_audio
              and quality in (None, "original"))
    if direct:
        url, content_type = f"{base}/api/media/{item.id}/stream?{t}", _CASTABLE[ext]
    else:
        options = transcode.qualities_for(item.height)
        q = quality if quality in options else next((o for o in options if o in ("1080p", "720p")), options[0])
        url, content_type = f"{base}/api/media/{item.id}/hls/{q}/{audio}/index.m3u8?{t}", "application/x-mpegURL"
    progress = await session.scalar(select(WatchProgress).where(WatchProgress.user_id == user.id,
                                                                WatchProgress.media_id == item.id))
    series = await session.get(Series, item.series_id) if item.series_id else None
    return CastOut(
        url=url, content_type=content_type, converted=not direct,
        title=series.title if series else item.title,
        subtitle=(f"S{item.season or 1} E{item.episode}" + (f" · {item.episode_title}" if item.episode_title else "")
                  if series and item.episode is not None else (str(item.year) if item.year else None)),
        poster=f"{base}/api/media/{item.id}/poster?{t}" if item.poster_ready else None,
        duration=item.duration, start=progress.position if progress and not progress.finished else 0,
        subtitles=[CastSubtitle(url=f"{base}/api/media/{item.id}/subtitles/{s['id']}.vtt?{t}", label=s["label"],
                                language=s.get("language")) for s in tracks["subtitles"] if s["usable"]])


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

