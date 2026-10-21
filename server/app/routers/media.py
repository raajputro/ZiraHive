from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import and_, case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session, one_row
from ..models import Book, Library, MediaItem, MusicAlbum, Series, Track, User, WatchProgress, utcnow, track_shown
from ..schemas import (FolderBrowseOut, FolderPick, LibraryIn, LibraryOrderIn, LibraryOut, LibraryUpdateIn, MediaOut,
                       ProgressIn, SeasonOut, SeriesOut, TitleOut)
from ..security import admin_user, create_token, current_user
from ..services import activity, jobs, storage
from ..services import browse
from ..services.libraries import adopt_quran, discover, guess_kind, merge_duplicates, pretty_name
from ..services.shelf_scan import SHELF_KINDS
from ..services.ranged import ranged_file_response
from ..services.ratings import allowed, effective_age

router = APIRouter(prefix="/api", tags=["media"])

# What a typical browser can play without transcoding. Anything else needs the
# transcoding milestone (or a native player such as VLC on the TV for now).
_WEB_VIDEO = {"h264", "vp8", "vp9", "av1"}
_WEB_AUDIO = {None, "aac", "mp3", "opus", "vorbis", "flac"}
_WEB_CONTAINER = {"mov", "mp4", "m4a", "3gp", "matroska", "webm"}
_MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
         ".webm": "video/webm", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo"}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def browser_playable(item: MediaItem) -> bool:
    return (item.video_codec in _WEB_VIDEO and item.audio_codec in _WEB_AUDIO
            and (item.container or "") in _WEB_CONTAINER)


def _aware(dt: datetime | None) -> datetime:
    if dt is None:
        return _EPOCH
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _out(item: MediaItem, progress: WatchProgress | None, series: Series | None = None,
         next_id: str | None = None, gate: "Gate | None" = None) -> MediaOut:
    out = MediaOut.model_validate(item)
    out.browser_playable = browser_playable(item)
    if progress:
        out.position, out.finished = progress.position, progress.finished
    if series:
        out.series_title = series.title
        # markers from the file's chapters win; otherwise the series-wide ones
        if out.intro_end is None and series.intro_end is not None:
            out.intro_start, out.intro_end = series.intro_start or 0, series.intro_end
        if out.credits_start is None and series.credits_before_end and item.duration:
            out.credits_start = max(item.duration - series.credits_before_end, 0)
    out.next_id = next_id
    if gate:
        out.age = gate.item_age(item)
    return out


class Gate:
    """Age-limit checks for one request. Profiles without a limit pass everything."""

    def __init__(self, user: User, libs: dict[str, Library], series: dict[str, Series]):
        self.max_age, self.libs, self.series = user.max_age, libs, series

    def _lib_age(self, library_id: str) -> int | None:
        lib = self.libs.get(library_id)
        return lib.age_rating if lib else None

    def series_age(self, s: Series) -> int | None:
        return effective_age(series_age=s.age_rating, series_cert=s.certification, library_age=self._lib_age(s.library_id))

    def item_age(self, item: MediaItem) -> int | None:
        s = self.series.get(item.series_id) if item.series_id else None
        return effective_age(item.age_rating, item.certification, s.age_rating if s else None,
                             s.certification if s else None, self._lib_age(item.library_id))

    def ok_item(self, item: MediaItem) -> bool:
        return allowed(self.max_age, self.item_age(item))

    def ok_series(self, s: Series) -> bool:
        return allowed(self.max_age, self.series_age(s))


async def gate_for(session: AsyncSession, user: User) -> Gate:
    libs = {lib.id: lib for lib in (await session.scalars(select(Library))).all()}
    series = {s.id: s for s in (await session.scalars(select(Series))).all()}
    return Gate(user, libs, series)


def _episode_order(item: MediaItem):
    return (item.season if item.season is not None else 9999,
            item.episode if item.episode is not None else 9999, item.rel_path.lower())


async def _episodes(session: AsyncSession, series_id: str) -> list[MediaItem]:
    rows = (await session.scalars(select(MediaItem).where(
        MediaItem.series_id == series_id, MediaItem.missing.is_(False)))).all()
    return sorted(rows, key=_episode_order)


def _next_after(episodes: list[MediaItem], item_id: str) -> MediaItem | None:
    ids = [e.id for e in episodes]
    if item_id in ids and ids.index(item_id) + 1 < len(ids):
        return episodes[ids.index(item_id) + 1]
    return None


async def _progress_map(session: AsyncSession, user_id: str, ids: list[str]) -> dict[str, WatchProgress]:
    if not ids:
        return {}
    rows = (await session.scalars(select(WatchProgress).where(
        WatchProgress.user_id == user_id, WatchProgress.media_id.in_(ids)))).all()
    return {p.media_id: p for p in rows}


# -------------------------------------------------------------- libraries

async def _library_out(session: AsyncSession, libs: list[Library]) -> list[LibraryOut]:
    movies = dict((await session.execute(select(MediaItem.library_id, func.count()).where(
        MediaItem.missing.is_(False), MediaItem.series_id.is_(None))
        .group_by(MediaItem.library_id))).all())
    series = dict((await session.execute(
        select(Series.library_id, func.count(func.distinct(Series.id)))
        .join(MediaItem, MediaItem.series_id == Series.id)
        .where(MediaItem.missing.is_(False)).group_by(Series.library_id))).all())
    albums = dict((await session.execute(
        select(Track.library_id, func.count(func.distinct(Track.album_id)))
        .where(track_shown()).group_by(Track.library_id))).all())
    books = dict((await session.execute(select(Book.library_id, func.count()).where(
        Book.missing.is_(False)).group_by(Book.library_id))).all())
    out = []
    for lib in libs:
        o = LibraryOut.model_validate(lib)
        o.item_count = movies.get(lib.id, 0) + series.get(lib.id, 0) + albums.get(lib.id, 0) + books.get(lib.id, 0)
        o.available = Path(lib.path).is_dir()
        o.display_path = browse.display(lib.path)
        out.append(o)
    return out


async def _ordered_libraries(session: AsyncSession) -> list[Library]:
    return list((await session.scalars(
        select(Library).order_by(Library.sort_order, Library.name))).all())


@router.get("/libraries", response_model=list[LibraryOut])
async def list_libraries(_: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    return await _library_out(session, await _ordered_libraries(session))


@router.post("/libraries", response_model=LibraryOut, status_code=201)
async def add_library(body: LibraryIn, _: User = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    folder = browse.allowed(body.path)
    if folder is None or not folder.is_dir():
        raise HTTPException(400, "Pick a folder on one of your drives. With Docker, list the drive in .env first "
                                 "(for example DRIVE_E=E:/) and restart.")
    body.path = browse.preferred(folder)
    taken = {browse.same_folder_key(p) for p in (await session.scalars(select(Library.path))).all()}
    if browse.same_folder_key(body.path) in taken:
        raise HTTPException(409, "That folder is already a category")
    order = (await session.scalar(select(func.max(Library.sort_order)))) or 0
    lib = Library(name=body.name, path=body.path, kind=body.kind, sort_order=order + 1)
    session.add(lib)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "That folder is already a category")
    await jobs.enqueue("scan_library", lib.id)
    return (await _library_out(session, [lib]))[0]


@router.get("/admin/folders", response_model=FolderBrowseOut)
async def browse_folders(path: str | None = None, _: User = Depends(admin_user)):
    """Folders to pick a category from: the drives first, then any folder inside them."""
    if not path:
        return FolderBrowseOut(path=None, label=None, parent=None, folders=[
            FolderPick(path=str(p), label=label, name=label) for p, label in browse.roots()])
    folder = browse.allowed(path)
    if folder is None or not folder.is_dir():
        raise HTTPException(404, "Folder not found")
    root_paths = {str(r.resolve()) for r, _ in browse.roots()}
    parent = None if str(folder) in root_paths else str(folder.parent)
    return FolderBrowseOut(path=str(folder), label=browse.display(folder), parent=parent,
                           guess=guess_kind(pretty_name(folder.name)), folders=[
        FolderPick(path=str(c), label=browse.display(c), name=c.name, guess=guess_kind(pretty_name(c.name)))
        for c in browse.list_folder(folder)])


@router.post("/libraries/discover", response_model=list[LibraryOut])
async def discover_libraries(_: User = Depends(admin_user),
                             session: AsyncSession = Depends(get_session)):
    """Add every new folder in the media folder as a category and scan it (and fold together
    any categories that turn out to be the same folder)."""
    for lib in await merge_duplicates(session):
        await jobs.enqueue("scan_library", lib.id)
    created = await discover(session)
    for lib in created:
        await jobs.enqueue("scan_library", lib.id)
    for lib in await adopt_quran(session):
        await jobs.enqueue("scan_library", lib.id)
    return await _library_out(session, created)


@router.patch("/libraries/{library_id}", response_model=LibraryOut)
async def update_library(library_id: str, body: LibraryUpdateIn, _: User = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    lib = await session.get(Library, library_id)
    if lib is None:
        raise HTTPException(404, "Category not found")
    if body.name:
        lib.name = body.name
    if body.age_rating is not None:
        lib.age_rating = None if body.age_rating < 0 else body.age_rating
    rescan = body.kind is not None and body.kind != lib.kind
    if rescan:
        old, lib.kind = lib.kind, body.kind
        if old in SHELF_KINDS or body.kind in SHELF_KINDS:
            # Music, books and videos are kept apart: start this category over.
            for model in (Track, MusicAlbum, Book, MediaItem, Series):
                await session.execute(delete(model).where(model.library_id == lib.id))
        else:
            # Make the next scan re-read every file so movies/episodes are sorted again.
            await session.execute(update(MediaItem).where(MediaItem.library_id == lib.id).values(mtime=0))
    await session.commit()
    if rescan:
        await jobs.enqueue("scan_library", lib.id)
    return (await _library_out(session, [lib]))[0]


@router.put("/libraries/order", response_model=list[LibraryOut])
async def reorder_libraries(body: LibraryOrderIn, _: User = Depends(admin_user),
                            session: AsyncSession = Depends(get_session)):
    libs = {lib.id: lib for lib in await _ordered_libraries(session)}
    for i, lib_id in enumerate(body.ids):
        if lib_id in libs:
            libs[lib_id].sort_order = i + 1
    await session.commit()
    return await _library_out(session, await _ordered_libraries(session))


@router.delete("/libraries/{library_id}", status_code=204)
async def remove_library(library_id: str, _: User = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    lib = await session.get(Library, library_id)
    if lib is None:
        raise HTTPException(404, "Category not found")
    await session.delete(lib)  # files on disk are never touched
    await session.commit()


@router.post("/libraries/{library_id}/scan", status_code=202)
async def scan_library(library_id: str, _: User = Depends(admin_user),
                       session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(Library, library_id) is None:
        raise HTTPException(404, "Category not found")
    await jobs.enqueue("scan_library", library_id)
    return {"status": "scan started"}


# ----------------------------------------------------------------- titles

@router.get("/titles", response_model=list[TitleOut])
async def list_titles(library_id: str | None = None, q: str | None = None,
                      sort: str = Query("added", pattern="^(added|title|year)$"),
                      limit: int = Query(500, ge=1, le=5000),
                      user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """Cards for the Watch page: movies plus one card per series, in one list."""
    movie_q = select(MediaItem, WatchProgress).outerjoin(WatchProgress, and_(
        WatchProgress.media_id == MediaItem.id, WatchProgress.user_id == user.id)).where(
        MediaItem.missing.is_(False), MediaItem.series_id.is_(None))
    eps = (select(MediaItem.series_id.label("sid"), func.count(MediaItem.id).label("n"),
                  func.max(MediaItem.added_at).label("latest"),
                  func.sum(case((WatchProgress.finished.is_(True), 1), else_=0)).label("watched"))
           .outerjoin(WatchProgress, and_(WatchProgress.media_id == MediaItem.id,
                                          WatchProgress.user_id == user.id))
           .where(MediaItem.series_id.is_not(None), MediaItem.missing.is_(False))
           .group_by(MediaItem.series_id).subquery())
    series_q = select(Series, eps.c.n, eps.c.latest, eps.c.watched).join(eps, eps.c.sid == Series.id)
    if library_id:
        movie_q = movie_q.where(MediaItem.library_id == library_id)
        series_q = series_q.where(Series.library_id == library_id)
    if q:
        movie_q = movie_q.where(MediaItem.title.ilike(f"%{q}%"))
        series_q = series_q.where(Series.title.ilike(f"%{q}%"))
    titles: list[TitleOut] = []
    gate = await gate_for(session, user)
    for m, p in (await session.execute(movie_q)).all():
        if not gate.ok_item(m):
            continue
        titles.append(TitleOut(type="movie", age=gate.item_age(m), id=m.id, library_id=m.library_id, title=m.title,
                               year=m.year, poster_ready=m.poster_ready, added_at=_aware(m.added_at),
                               duration=m.duration, position=p.position if p else 0,
                               finished=p.finished if p else False, browser_playable=browser_playable(m)))
    for s, n, latest, watched in (await session.execute(series_q)).all():
        if not gate.ok_series(s):
            continue
        titles.append(TitleOut(type="series", age=gate.series_age(s), id=s.id, library_id=s.library_id, title=s.title,
                               year=s.year, poster_ready=s.poster_ready, added_at=_aware(latest),
                               episode_count=n, watched_count=int(watched or 0)))
    if sort == "title":
        titles.sort(key=lambda t: t.title.lower())
    elif sort == "year":
        titles.sort(key=lambda t: (t.year or 0, t.title.lower()), reverse=True)
    else:
        titles.sort(key=lambda t: t.added_at, reverse=True)
    return titles[:limit]


# ----------------------------------------------------------------- series

async def _get_series(series_id: str, session: AsyncSession) -> Series:
    series = await session.get(Series, series_id)
    if series is None:
        raise HTTPException(404, "Series not found")
    return series


@router.get("/series/{series_id}", response_model=SeriesOut)
async def get_series(series_id: str, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    series = await _get_series(series_id, session)
    gate = await gate_for(session, user)
    if not gate.ok_series(series):
        raise HTTPException(404, "Series not found")
    episodes = [e for e in await _episodes(session, series.id) if gate.ok_item(e)]
    progress = await _progress_map(session, user.id, [e.id for e in episodes])
    seasons: dict[int | None, list[MediaOut]] = {}
    for i, e in enumerate(episodes):
        nxt = episodes[i + 1].id if i + 1 < len(episodes) else None
        seasons.setdefault(e.season, []).append(_out(e, progress.get(e.id), series, nxt, gate))
    return SeriesOut(id=series.id, library_id=series.library_id, title=series.title, year=series.year,
                     overview=series.overview, poster_ready=series.poster_ready,
                     episode_count=len(episodes),
                     seasons=[SeasonOut(season=k, episodes=v) for k, v in seasons.items()],
                     up_next=_up_next(episodes, progress, series),
                     age=gate.series_age(series), age_rating=series.age_rating,
                     intro_start=series.intro_start, intro_end=series.intro_end,
                     credits_before_end=series.credits_before_end)


def _up_next(episodes: list[MediaItem], progress: dict[str, WatchProgress],
             series: Series) -> MediaOut | None:
    """The episode to play: one you're part-way through, else the one after the last you finished."""
    if not episodes:
        return None
    touched = [(progress[e.id], i) for i, e in enumerate(episodes) if e.id in progress]
    if not touched:
        target = 0
    else:
        last, i = max(touched, key=lambda t: _aware(t[0].updated_at))
        target = i + 1 if last.finished else i
        if target >= len(episodes):
            return None  # watched everything
    e = episodes[target]
    nxt = episodes[target + 1].id if target + 1 < len(episodes) else None
    return _out(e, progress.get(e.id), series, nxt)


@router.get("/series/{series_id}/poster")
async def series_poster(series_id: str, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    series = await _get_series(series_id, session)
    if not (await gate_for(session, user)).ok_series(series):
        raise HTTPException(404, "No poster")
    path = storage.series_poster_path(series.id)
    if not series.poster_ready or not path.exists():
        raise HTTPException(404, "No poster")
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})


# ------------------------------------------------------------------ media

@router.get("/media", response_model=list[MediaOut])
async def list_media(library_id: str | None = None, q: str | None = None,
                     user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    """Movies only (episodes are listed through /series)."""
    stmt = select(MediaItem, WatchProgress).outerjoin(WatchProgress, (
        WatchProgress.media_id == MediaItem.id) & (WatchProgress.user_id == user.id)).where(
        MediaItem.missing.is_(False), MediaItem.series_id.is_(None))
    if library_id:
        stmt = stmt.where(MediaItem.library_id == library_id)
    if q:
        stmt = stmt.where(MediaItem.title.ilike(f"%{q}%"))
    rows = (await session.execute(stmt.order_by(MediaItem.title))).all()
    gate = await gate_for(session, user)
    return [_out(m, p, gate=gate) for m, p in rows if gate.ok_item(m)]


@router.get("/media/continue", response_model=list[MediaOut])
async def continue_watching(user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    """Movies you stopped part-way, and for each series the episode to watch next."""
    rows = (await session.execute(
        select(MediaItem, WatchProgress).join(WatchProgress, WatchProgress.media_id == MediaItem.id)
        .where(WatchProgress.user_id == user.id, MediaItem.missing.is_(False))
        .order_by(WatchProgress.updated_at.desc()).limit(200))).all()
    out: list[MediaOut] = []
    seen_series: set[str] = set()
    gate = await gate_for(session, user)
    for item, prog in rows:
        if len(out) >= 20:
            break
        if not gate.ok_item(item):
            continue
        if item.series_id is None:
            if not prog.finished and prog.position > 30:
                out.append(_out(item, prog))
            continue
        if item.series_id in seen_series:
            continue  # only the most recent episode of each series counts
        seen_series.add(item.series_id)
        series = await session.get(Series, item.series_id)
        episodes = await _episodes(session, item.series_id)
        if not prog.finished:
            if prog.position > 30:
                nxt = _next_after(episodes, item.id)
                out.append(_out(item, prog, series, nxt.id if nxt else None))
            continue
        nxt = _next_after(episodes, item.id)
        if nxt:
            after = _next_after(episodes, nxt.id)
            nprog = (await _progress_map(session, user.id, [nxt.id])).get(nxt.id)
            out.append(_out(nxt, nprog, series, after.id if after else None))
    return out


async def _get_media(media_id: str, session: AsyncSession, user: User | None = None) -> MediaItem:
    item = await session.get(MediaItem, media_id)
    if item is None:
        raise HTTPException(404, "Not found")
    if user is not None and user.max_age is not None and not (await gate_for(session, user)).ok_item(item):
        raise HTTPException(404, "Not found")
    return item


@router.get("/media/{media_id}", response_model=MediaOut)
async def get_media(media_id: str, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session, user)
    progress = await session.scalar(select(WatchProgress).where(
        WatchProgress.user_id == user.id, WatchProgress.media_id == media_id))
    series, next_id = None, None
    if item.series_id:
        series = await session.get(Series, item.series_id)
        nxt = _next_after(await _episodes(session, item.series_id), item.id)
        next_id = nxt.id if nxt else None
    return _out(item, progress, series, next_id, await gate_for(session, user))


@router.get("/media/{media_id}/poster")
async def media_poster(media_id: str, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session, user)
    path = storage.poster_path(item.id)
    if not item.poster_ready or not path.exists():
        raise HTTPException(404, "No poster")
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.api_route("/media/{media_id}/stream", methods=["GET", "HEAD"])
async def stream_media(media_id: str, request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Direct play: the original file, with Range support so players can seek."""
    item = await _get_media(media_id, session, user)
    activity.stream_seen(user.id, user.username, item.id, item.title)
    lib = await session.get(Library, item.library_id)
    root = Path(lib.path).resolve()
    path = (root / item.rel_path).resolve()
    if root not in path.parents:
        raise HTTPException(400, "Invalid path")
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    resp = ranged_file_response(request, path, mime, path.name, inline=True)
    if request.query_params.get("token"):  # a Chromecast or TV playing it by itself
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Range, Accept-Ranges"
    return resp


@router.get("/media/{media_id}/link")
async def stream_link(media_id: str, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)) -> dict:
    """A signed URL (valid 24 h) for players that can't log in, e.g. VLC on a TV."""
    await _get_media(media_id, session, user)
    return {"path": f"/api/media/{media_id}/stream?token={create_token(user, days=1)}"}


@router.put("/media/{media_id}/progress", status_code=204)
async def save_progress(media_id: str, body: ProgressIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    item = await _get_media(media_id, session, user)
    duration = body.duration or item.duration
    prog = await one_row(session, WatchProgress, user_id=user.id, media_id=media_id)
    prog.position, prog.duration = body.position, duration
    prog.finished = bool(duration and body.position >= duration * 0.92)
    prog.updated_at = utcnow()
    await session.commit()
