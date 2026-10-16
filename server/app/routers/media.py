from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Library, MediaItem, User, WatchProgress, utcnow
from ..schemas import LibraryIn, LibraryOut, MediaOut, ProgressIn
from ..security import admin_user, create_token, current_user
from ..services import jobs, storage
from ..services.ranged import ranged_file_response

router = APIRouter(prefix="/api", tags=["media"])

# What a typical browser can play without transcoding. Anything else needs the
# transcoding milestone (or a native player such as VLC on the TV for now).
_WEB_VIDEO = {"h264", "vp8", "vp9", "av1"}
_WEB_AUDIO = {None, "aac", "mp3", "opus", "vorbis", "flac"}
_WEB_CONTAINER = {"mov", "mp4", "m4a", "3gp", "matroska", "webm"}
_MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
         ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo"}


def browser_playable(item: MediaItem) -> bool:
    return (item.video_codec in _WEB_VIDEO and item.audio_codec in _WEB_AUDIO
            and (item.container or "") in _WEB_CONTAINER)


def _out(item: MediaItem, progress: WatchProgress | None) -> MediaOut:
    out = MediaOut.model_validate(item)
    out.browser_playable = browser_playable(item)
    if progress:
        out.position, out.finished = progress.position, progress.finished
    return out


# -------------------------------------------------------------- libraries

@router.get("/libraries", response_model=list[LibraryOut])
async def list_libraries(_: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    counts = dict((await session.execute(select(MediaItem.library_id, func.count()).where(
        MediaItem.missing.is_(False)).group_by(MediaItem.library_id))).all())
    libs = (await session.scalars(select(Library).order_by(Library.name))).all()
    out = []
    for lib in libs:
        o = LibraryOut.model_validate(lib)
        o.item_count = counts.get(lib.id, 0)
        out.append(o)
    return out


@router.post("/libraries", response_model=LibraryOut, status_code=201)
async def add_library(body: LibraryIn, _: User = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    if not Path(body.path).is_dir():
        raise HTTPException(400, "That folder doesn't exist inside the server. With Docker, "
                                 "mount it in docker-compose.yml first (e.g. /media/movies).")
    lib = Library(name=body.name, path=body.path, kind=body.kind)
    session.add(lib)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "That folder is already a library")
    await jobs.enqueue("scan_library", lib.id)
    return LibraryOut.model_validate(lib)


@router.delete("/libraries/{library_id}", status_code=204)
async def remove_library(library_id: str, _: User = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    lib = await session.get(Library, library_id)
    if lib is None:
        raise HTTPException(404, "Library not found")
    await session.delete(lib)  # movie files on disk are never touched
    await session.commit()


@router.post("/libraries/{library_id}/scan", status_code=202)
async def scan_library(library_id: str, _: User = Depends(admin_user),
                       session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(Library, library_id) is None:
        raise HTTPException(404, "Library not found")
    await jobs.enqueue("scan_library", library_id)
    return {"status": "scan started"}


# ------------------------------------------------------------------ media

@router.get("/media", response_model=list[MediaOut])
async def list_media(library_id: str | None = None, q: str | None = None,
                     user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    stmt = select(MediaItem, WatchProgress).outerjoin(WatchProgress, (
        WatchProgress.media_id == MediaItem.id) & (WatchProgress.user_id == user.id)).where(
        MediaItem.missing.is_(False))
    if library_id:
        stmt = stmt.where(MediaItem.library_id == library_id)
    if q:
        stmt = stmt.where(MediaItem.title.ilike(f"%{q}%"))
    rows = (await session.execute(stmt.order_by(MediaItem.title))).all()
    return [_out(m, p) for m, p in rows]


@router.get("/media/continue", response_model=list[MediaOut])
async def continue_watching(user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(MediaItem, WatchProgress).join(WatchProgress, WatchProgress.media_id == MediaItem.id)
        .where(WatchProgress.user_id == user.id, WatchProgress.finished.is_(False),
               WatchProgress.position > 30, MediaItem.missing.is_(False))
        .order_by(WatchProgress.updated_at.desc()).limit(20))).all()
    return [_out(m, p) for m, p in rows]


async def _get_media(media_id: str, session: AsyncSession) -> MediaItem:
    item = await session.get(MediaItem, media_id)
    if item is None:
        raise HTTPException(404, "Not found")
    return item


@router.get("/media/{media_id}", response_model=MediaOut)
async def get_media(media_id: str, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session)
    progress = await session.scalar(select(WatchProgress).where(
        WatchProgress.user_id == user.id, WatchProgress.media_id == media_id))
    return _out(item, progress)


@router.get("/media/{media_id}/poster")
async def media_poster(media_id: str, _: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session)
    path = storage.poster_path(item.id)
    if not item.poster_ready or not path.exists():
        raise HTTPException(404, "No poster")
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/media/{media_id}/stream")
async def stream_media(media_id: str, request: Request, _: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Direct play: the original file, with Range support so players can seek."""
    item = await _get_media(media_id, session)
    lib = await session.get(Library, item.library_id)
    root = Path(lib.path).resolve()
    path = (root / item.rel_path).resolve()
    if root not in path.parents:
        raise HTTPException(400, "Invalid path")
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    return ranged_file_response(request, path, mime, path.name, inline=True)


@router.get("/media/{media_id}/link")
async def stream_link(media_id: str, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)) -> dict:
    """A signed URL (valid 24 h) for players that can't log in, e.g. VLC on a TV."""
    await _get_media(media_id, session)
    return {"path": f"/api/media/{media_id}/stream?token={create_token(user.id, days=1)}"}


@router.put("/media/{media_id}/progress", status_code=204)
async def save_progress(media_id: str, body: ProgressIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session)
    duration = body.duration or item.duration
    prog = await session.scalar(select(WatchProgress).where(
        WatchProgress.user_id == user.id, WatchProgress.media_id == media_id))
    if prog is None:
        prog = WatchProgress(user_id=user.id, media_id=media_id)
        session.add(prog)
    prog.position, prog.duration = body.position, duration
    prog.finished = bool(duration and body.position >= duration * 0.92)
    prog.updated_at = utcnow()
    await session.commit()
