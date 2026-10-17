"""Music: albums, artists, songs, favourites, playlists and streaming."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session, one_row
from ..models import Library, MusicAlbum, Playlist, PlaylistTrack, Track, TrackStat, User, utcnow
from ..schemas import (MusicAlbumDetailOut, MusicAlbumOut, ArtistDetailOut, ArtistOut, AudioReadyOut, FavoriteIn,
                       MusicHomeOut, PlaylistAddIn, PlaylistDetailOut, PlaylistIn, PlaylistOut,
                       PlaylistUpdateIn, TrackOut)
from ..security import current_user
from ..services import activity, audio_convert, storage
from ..services.ranged import ranged_file_response
from ..services.ratings import allowed
from ..services.shelf_files import AUDIO_MIME

router = APIRouter(prefix="/api/music", tags=["music"])


async def visible_libraries(session: AsyncSession, user: User, kinds: set[str]) -> dict[str, Library]:
    """Categories of these kinds this profile may see (age limits apply to the whole category)."""
    libs = (await session.scalars(select(Library).where(Library.kind.in_(kinds)))).all()
    return {lib.id: lib for lib in libs if allowed(user.max_age, lib.age_rating)}


async def _lib_ids(session: AsyncSession, user: User) -> list[str]:
    return list(await visible_libraries(session, user, {"music"}))


def safe_path(lib: Library, rel: str) -> Path:
    root = Path(lib.path).resolve()
    path = (root / rel).resolve()
    if root != path and root not in path.parents:
        raise HTTPException(400, "Invalid path")
    return path


async def _stats(session: AsyncSession, user: User, ids: list[str]) -> dict[str, TrackStat]:
    if not ids:
        return {}
    rows = (await session.scalars(select(TrackStat).where(TrackStat.user_id == user.id,
                                                          TrackStat.track_id.in_(ids)))).all()
    return {s.track_id: s for s in rows}


async def track_outs(session: AsyncSession, user: User, tracks: list[Track]) -> list[TrackOut]:
    stats = await _stats(session, user, [t.id for t in tracks])
    album_ids = {t.album_id for t in tracks if t.album_id}
    covers = dict((await session.execute(select(MusicAlbum.id, MusicAlbum.cover_ready)
                                         .where(MusicAlbum.id.in_(album_ids)))).all()) if album_ids else {}
    out = []
    for t in tracks:
        o = TrackOut.model_validate(t)
        s = stats.get(t.id)
        o.favorite, o.plays = (s.favorite, s.plays) if s else (False, 0)
        o.cover_ready = bool(covers.get(t.album_id))
        out.append(o)
    return out


def _album_query(lib_ids: list[str]):
    counts = (select(Track.album_id, func.count().label("n"), func.coalesce(func.sum(Track.duration), 0).label("d"))
              .where(Track.missing.is_(False)).group_by(Track.album_id).subquery())
    return (select(MusicAlbum, counts.c.n, counts.c.d).join(counts, counts.c.album_id == MusicAlbum.id)
            .where(MusicAlbum.library_id.in_(lib_ids)))


def _album_out(row) -> MusicAlbumOut:
    album, n, d = row
    o = MusicAlbumOut.model_validate(album)
    o.track_count, o.duration = n, float(d or 0)
    return o


async def _track(session: AsyncSession, user: User, track_id: str) -> tuple[Track, Library]:
    t = await session.get(Track, track_id)
    if t is None or t.missing or t.library_id not in await _lib_ids(session, user):
        raise HTTPException(404, "Song not found")
    return t, await session.get(Library, t.library_id)


def _visible_tracks(lib_ids: list[str]):
    return select(Track).where(Track.library_id.in_(lib_ids), Track.missing.is_(False))


_ORDER = (Track.disc_no.is_(None), Track.disc_no, Track.track_no.is_(None), Track.track_no, Track.rel_path)


# ------------------------------------------------------------------ browse

@router.get("/home", response_model=MusicHomeOut)
async def music_home(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    ids = await _lib_ids(session, user)
    recent = (await session.execute(_album_query(ids).order_by(MusicAlbum.added_at.desc()).limit(18))).all()
    played_rows = (await session.execute(
        select(Track).join(TrackStat, TrackStat.track_id == Track.id)
        .where(TrackStat.user_id == user.id, TrackStat.last_played.is_not(None), Track.missing.is_(False),
               Track.library_id.in_(ids)).order_by(TrackStat.last_played.desc()).limit(18))).scalars().all()
    most = (await session.execute(
        select(Track).join(TrackStat, TrackStat.track_id == Track.id)
        .where(TrackStat.user_id == user.id, TrackStat.plays > 0, Track.missing.is_(False),
               Track.library_id.in_(ids)).order_by(TrackStat.plays.desc()).limit(18))).scalars().all()
    favs = await session.scalar(select(func.count()).select_from(TrackStat).join(Track, Track.id == TrackStat.track_id)
                                .where(TrackStat.user_id == user.id, TrackStat.favorite.is_(True),
                                       Track.missing.is_(False), Track.library_id.in_(ids)))
    return MusicHomeOut(recent_albums=[_album_out(r) for r in recent],
                        recently_played=await track_outs(session, user, list(played_rows)),
                        most_played=await track_outs(session, user, list(most)),
                        playlists=await _playlist_outs(session, user, ids), favorite_count=favs or 0)


@router.get("/albums", response_model=list[MusicAlbumOut])
async def list_albums(library_id: str | None = None, q: str | None = None, artist: str | None = None,
                      sort: str = Query("added", pattern="^(added|title|artist|year)$"),
                      limit: int = Query(500, ge=1, le=2000), offset: int = Query(0, ge=0),
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    ids = await _lib_ids(session, user)
    if library_id:
        ids = [i for i in ids if i == library_id]
    stmt = _album_query(ids)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(MusicAlbum.title.ilike(like), MusicAlbum.artist.ilike(like)))
    if artist:
        stmt = stmt.where(MusicAlbum.artist == artist)
    order = {"added": [MusicAlbum.added_at.desc()], "title": [func.lower(MusicAlbum.title)],
             "artist": [func.lower(MusicAlbum.artist), MusicAlbum.year], "year": [MusicAlbum.year.desc()]}[sort]
    rows = (await session.execute(stmt.order_by(*order).limit(limit).offset(offset))).all()
    return [_album_out(r) for r in rows]


@router.get("/albums/{album_id}", response_model=MusicAlbumDetailOut)
async def get_album(album_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = (await session.execute(_album_query(await _lib_ids(session, user)).where(MusicAlbum.id == album_id))).first()
    if row is None:
        raise HTTPException(404, "Album not found")
    out = MusicAlbumDetailOut(**_album_out(row).model_dump())
    tracks = (await session.scalars(select(Track).where(Track.album_id == album_id, Track.missing.is_(False))
                                    .order_by(*_ORDER))).all()
    out.tracks = await track_outs(session, user, list(tracks))
    return out


@router.get("/albums/{album_id}/cover")
async def album_cover(album_id: str, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    album = await session.get(MusicAlbum, album_id)
    if album is None or album.library_id not in await _lib_ids(session, user):
        raise HTTPException(404, "Album not found")
    path = storage.cover_path("album", album.id)
    if not album.cover_ready or not path.is_file():
        raise HTTPException(404, "No cover")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/artists", response_model=list[ArtistOut])
async def list_artists(library_id: str | None = None, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    ids = await _lib_ids(session, user)
    if library_id:
        ids = [i for i in ids if i == library_id]
    rows = (await session.execute(_album_query(ids))).all()
    artists: dict[str, ArtistOut] = {}
    for album, n, _d in rows:
        a = artists.setdefault(album.artist, ArtistOut(name=album.artist, album_count=0, track_count=0,
                                                       cover_album_id=None))
        a.album_count += 1
        a.track_count += n
        if album.cover_ready and not a.cover_album_id:
            a.cover_album_id = album.id
    return sorted(artists.values(), key=lambda a: (a.name in ("Various artists", "Unknown artist"), a.name.lower()))


@router.get("/artist", response_model=ArtistDetailOut)
async def get_artist(name: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    ids = await _lib_ids(session, user)
    albums = (await session.execute(_album_query(ids).where(MusicAlbum.artist == name)
                                    .order_by(MusicAlbum.year.desc()))).all()
    tracks = (await session.scalars(_visible_tracks(ids).where(
        or_(Track.artist == name, Track.album_id.in_([a[0].id for a in albums] or [""])))
        .order_by(Track.album_id, *_ORDER).limit(500))).all()
    if not albums and not tracks:
        raise HTTPException(404, "Artist not found")
    outs = await track_outs(session, user, list(tracks))
    outs.sort(key=lambda t: -t.plays)
    return ArtistDetailOut(name=name, albums=[_album_out(r) for r in albums], tracks=outs)


@router.get("/tracks", response_model=list[TrackOut])
async def list_tracks(q: str | None = None, library_id: str | None = None, favorites: bool = False,
                      sort: str = Query("title", pattern="^(title|artist|added|album)$"),
                      limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0),
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    ids = await _lib_ids(session, user)
    if library_id:
        ids = [i for i in ids if i == library_id]
    stmt = _visible_tracks(ids)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Track.title.ilike(like), Track.artist.ilike(like), Track.album_title.ilike(like)))
    if favorites:
        stmt = stmt.join(TrackStat, TrackStat.track_id == Track.id).where(
            TrackStat.user_id == user.id, TrackStat.favorite.is_(True))
    order = {"title": [func.lower(Track.title)], "artist": [func.lower(Track.artist), func.lower(Track.title)],
             "added": [Track.added_at.desc()], "album": [Track.album_id, *_ORDER]}[sort]
    rows = (await session.scalars(stmt.order_by(*order).limit(limit).offset(offset))).all()
    return await track_outs(session, user, list(rows))


# ---------------------------------------------------------------- playing

@router.get("/tracks/{track_id}/prepare", response_model=AudioReadyOut)
async def prepare_track(track_id: str, force: bool = False, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """For songs browsers can't play as they are: converts once, then says when it's ready.
    `force` converts a song that should play, for a browser that couldn't play it after all."""
    t, lib = await _track(session, user, track_id)
    if t.playable and not force:
        return AudioReadyOut(ready=True)
    ready, failed = audio_convert.status(safe_path(lib, t.rel_path), f"track-{t.id}")
    return AudioReadyOut(ready=ready, failed=failed)


@router.api_route("/tracks/{track_id}/stream", methods=["GET", "HEAD"])
async def stream_track(track_id: str, request: Request, converted: bool = False, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    t, lib = await _track(session, user, track_id)
    path = safe_path(lib, t.rel_path)
    activity.stream_seen(user.id, user.username, f"track-{t.id}", f"{t.title}" + (f" by {t.artist}" if t.artist else ""))
    if t.playable and not converted:
        return ranged_file_response(request, path, AUDIO_MIME.get(path.suffix.lower(), "audio/mpeg"), path.name)
    copy = audio_convert.ready_path(path, f"track-{t.id}")
    if copy is None:
        audio_convert.status(path, f"track-{t.id}")
        raise HTTPException(409, "This song is still being converted")
    return ranged_file_response(request, copy, "audio/mpeg", path.stem + ".mp3")


async def _stat(session: AsyncSession, user: User, track_id: str) -> TrackStat:
    return await one_row(session, TrackStat, user_id=user.id, track_id=track_id)


@router.post("/tracks/{track_id}/played", status_code=204)
async def track_played(track_id: str, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Called once a song has played for a while; feeds Recently played and Most played."""
    await _track(session, user, track_id)
    s = await _stat(session, user, track_id)
    s.plays = (s.plays or 0) + 1
    s.last_played = utcnow()
    await session.commit()


@router.put("/tracks/{track_id}/favorite", status_code=204)
async def set_favorite(track_id: str, body: FavoriteIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    await _track(session, user, track_id)
    s = await _stat(session, user, track_id)
    s.favorite = body.favorite
    await session.commit()


# --------------------------------------------------------------- playlists

async def _playlist_outs(session: AsyncSession, user: User, lib_ids: list[str],
                         lists: list[Playlist] | None = None) -> list[PlaylistOut]:
    if lists is None:
        lists = list((await session.scalars(select(Playlist).where(Playlist.user_id == user.id)
                                            .order_by(Playlist.updated_at.desc()))).all())
    out = []
    for p in lists:
        rows = (await session.execute(
            select(Track.duration, Track.album_id, MusicAlbum.cover_ready)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .outerjoin(MusicAlbum, MusicAlbum.id == Track.album_id)
            .where(PlaylistTrack.playlist_id == p.id, Track.missing.is_(False), Track.library_id.in_(lib_ids))
            .order_by(PlaylistTrack.position))).all()
        covers: list[str] = []
        for _d, album_id, cover in rows:
            if cover and album_id not in covers:
                covers.append(album_id)
        o = PlaylistOut.model_validate(p)
        o.track_count, o.duration, o.cover_album_ids = len(rows), float(sum(r[0] or 0 for r in rows)), covers[:4]
        out.append(o)
    return out


async def _playlist(session: AsyncSession, user: User, playlist_id: str) -> Playlist:
    p = await session.get(Playlist, playlist_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "Playlist not found")
    return p


async def _checked_tracks(session: AsyncSession, user: User, track_ids: list[str]) -> list[str]:
    ids = await _lib_ids(session, user)
    found = set((await session.scalars(select(Track.id).where(Track.id.in_(track_ids), Track.library_id.in_(ids)))).all())
    return [t for t in track_ids if t in found]


async def _detail(session: AsyncSession, user: User, p: Playlist) -> PlaylistDetailOut:
    ids = await _lib_ids(session, user)
    base = (await _playlist_outs(session, user, ids, [p]))[0]
    tracks = (await session.scalars(
        select(Track).join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
        .where(PlaylistTrack.playlist_id == p.id, Track.missing.is_(False), Track.library_id.in_(ids))
        .order_by(PlaylistTrack.position))).all()
    return PlaylistDetailOut(**base.model_dump(), tracks=await track_outs(session, user, list(tracks)))


async def _set_tracks(session: AsyncSession, p: Playlist, track_ids: list[str], start: int = 0) -> None:
    for i, tid in enumerate(track_ids):
        session.add(PlaylistTrack(playlist_id=p.id, track_id=tid, position=start + i))
    p.updated_at = utcnow()


@router.get("/playlists", response_model=list[PlaylistOut])
async def list_playlists(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await _playlist_outs(session, user, await _lib_ids(session, user))


@router.post("/playlists", response_model=PlaylistDetailOut, status_code=201)
async def create_playlist(body: PlaylistIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    p = Playlist(user_id=user.id, name=body.name.strip())
    session.add(p)
    await session.flush()
    await _set_tracks(session, p, await _checked_tracks(session, user, body.track_ids))
    await session.commit()
    return await _detail(session, user, p)


@router.get("/playlists/{playlist_id}", response_model=PlaylistDetailOut)
async def get_playlist(playlist_id: str, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    return await _detail(session, user, await _playlist(session, user, playlist_id))


@router.patch("/playlists/{playlist_id}", response_model=PlaylistDetailOut)
async def update_playlist(playlist_id: str, body: PlaylistUpdateIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    p = await _playlist(session, user, playlist_id)
    if body.name:
        p.name = body.name.strip()
    if body.track_ids is not None:
        await session.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == p.id))
        await _set_tracks(session, p, await _checked_tracks(session, user, body.track_ids))
    p.updated_at = utcnow()
    await session.commit()
    return await _detail(session, user, p)


@router.post("/playlists/{playlist_id}/tracks", response_model=PlaylistDetailOut)
async def add_to_playlist(playlist_id: str, body: PlaylistAddIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    p = await _playlist(session, user, playlist_id)
    last = await session.scalar(select(func.max(PlaylistTrack.position)).where(PlaylistTrack.playlist_id == p.id))
    await _set_tracks(session, p, await _checked_tracks(session, user, body.track_ids),
                      start=(last + 1) if last is not None else 0)
    await session.commit()
    return await _detail(session, user, p)


@router.delete("/playlists/{playlist_id}", status_code=204)
async def delete_playlist(playlist_id: str, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    await session.delete(await _playlist(session, user, playlist_id))
    await session.commit()
