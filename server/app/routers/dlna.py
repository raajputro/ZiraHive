"""What smart TVs see over DLNA.

TVs find media servers on the home network with UPnP (SSDP multicast), which Docker Desktop
can't do, so the DLNA part runs in the ZiraHive app on the PC (zirahive_sync/dlna.py). It asks
this endpoint for one folder at a time, as the account it is signed in with, and hands the TV
links that play one title each (12 hours), straight from ZiraHive.

Folder ids: "0" (top), "lib:<id>", "series:<id>", "season:<series id>:<n>", "music:<library id>",
"album:<id>", "continue".
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Library, MediaItem, MusicAlbum, Series, Track, User, WatchProgress, song_shown
from ..security import create_media_token, current_user
from ..services.ratings import allowed
from ..services.shelf_files import AUDIO_MIME
from ..services.shelf_scan import SHELF_KINDS
from .media import _MIME, _episode_order, gate_for

router = APIRouter(prefix="/api/dlna", tags=["dlna"])

_VIDEO_MIME = {**_MIME, ".ts": "video/mp2t", ".m2ts": "video/mp2t", ".mpg": "video/mpeg", ".mpeg": "video/mpeg",
               ".wmv": "video/x-ms-wmv", ".flv": "video/x-flv", ".3gp": "video/3gpp"}


class DlnaFolder(BaseModel):
    id: str
    title: str
    count: int | None = None


class DlnaItem(BaseModel):
    id: str
    title: str
    kind: str  # video | audio
    mime: str
    size: int | None = None
    duration: float | None = None
    path: str  # on ZiraHive, with a token that plays only this
    art: str | None = None
    year: int | None = None
    artist: str | None = None
    album: str | None = None
    track_no: int | None = None


class DlnaOut(BaseModel):
    id: str
    parent: str | None
    title: str
    folders: list[DlnaFolder] = []
    items: list[DlnaItem] = []
    lan_url: str | None = None  # ZiraHive's home-network address, when set


def _video(user: User, m: MediaItem, title: str | None = None) -> DlnaItem:
    t = f"?token={create_media_token(user, m.id)}"
    return DlnaItem(id=f"m:{m.id}", title=title or m.title, kind="video",
                    mime=_VIDEO_MIME.get(Path(m.rel_path).suffix.lower(), "video/x-matroska"), size=m.size,
                    duration=m.duration, year=m.year, path=f"/api/media/{m.id}/stream{t}",
                    art=f"/api/media/{m.id}/poster{t}" if m.poster_ready else None)


def _episode_title(m: MediaItem) -> str:
    code = f"{m.episode:02d}" if m.episode is not None else ""
    return f"{code}. {m.episode_title}" if code and m.episode_title else (f"Episode {m.episode}" if code else m.title)


@router.get("/browse", response_model=DlnaOut)
async def browse(id: str = "0", user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    gate = await gate_for(session, user)
    lan = get_settings().lan_url.strip().rstrip("/") or None
    kind, _, rest = id.partition(":")

    if id == "0":
        libs = (await session.scalars(select(Library).order_by(Library.sort_order, Library.name))).all()
        folders = []
        if await session.scalar(select(WatchProgress.id).where(WatchProgress.user_id == user.id,
                                                               WatchProgress.finished.is_(False),
                                                               WatchProgress.position > 30).limit(1)):
            folders.append(DlnaFolder(id="continue", title="Continue watching"))
        for lib in libs:
            if lib.kind == "music" and allowed(user.max_age, lib.age_rating):
                folders.append(DlnaFolder(id=f"music:{lib.id}", title=lib.name))
            elif lib.kind not in SHELF_KINDS:
                folders.append(DlnaFolder(id=f"lib:{lib.id}", title=lib.name))
        return DlnaOut(id="0", parent=None, title="ZiraHive", folders=folders, lan_url=lan)

    if kind == "continue":
        rows = (await session.execute(
            select(MediaItem, WatchProgress).join(WatchProgress, WatchProgress.media_id == MediaItem.id)
            .where(WatchProgress.user_id == user.id, WatchProgress.finished.is_(False), WatchProgress.position > 30,
                   MediaItem.missing.is_(False)).order_by(WatchProgress.updated_at.desc()).limit(30))).all()
        series = gate.series
        items = []
        for m, _ in rows:
            if gate.ok_item(m):
                s = series.get(m.series_id) if m.series_id else None
                items.append(_video(user, m, f"{s.title}: {_episode_title(m)}" if s else None))
        return DlnaOut(id=id, parent="0", title="Continue watching", items=items, lan_url=lan)

    if kind == "lib":
        lib = await session.get(Library, rest)
        if lib is None or lib.kind in SHELF_KINDS:
            raise HTTPException(404, "No such folder")
        movies = (await session.scalars(select(MediaItem).where(
            MediaItem.library_id == lib.id, MediaItem.series_id.is_(None), MediaItem.missing.is_(False)))).all()
        shows = [s for s in gate.series.values() if s.library_id == lib.id and gate.ok_series(s)]
        return DlnaOut(id=id, parent="0", title=lib.name, lan_url=lan,
                       folders=[DlnaFolder(id=f"series:{s.id}", title=s.title)
                                for s in sorted(shows, key=lambda s: s.title.lower())],
                       items=[_video(user, m) for m in sorted(movies, key=lambda m: m.title.lower()) if gate.ok_item(m)])

    if kind in ("series", "season"):
        sid, _, season = rest.partition(":")
        s = await session.get(Series, sid)
        if s is None or not gate.ok_series(s):
            raise HTTPException(404, "No such folder")
        eps = sorted((await session.scalars(select(MediaItem).where(
            MediaItem.series_id == s.id, MediaItem.missing.is_(False)))).all(), key=_episode_order)
        eps = [e for e in eps if gate.ok_item(e)]
        seasons = sorted({e.season or 1 for e in eps})
        if kind == "series" and len(seasons) > 1:
            return DlnaOut(id=id, parent=f"lib:{s.library_id}", title=s.title, lan_url=lan,
                           folders=[DlnaFolder(id=f"season:{s.id}:{n}", title=f"Season {n}",
                                               count=sum(1 for e in eps if (e.season or 1) == n)) for n in seasons])
        if kind == "season":
            eps = [e for e in eps if (e.season or 1) == int(season or 1)]
        return DlnaOut(id=id, parent=f"series:{s.id}" if kind == "season" else f"lib:{s.library_id}",
                       title=f"{s.title}, Season {season}" if kind == "season" else s.title, lan_url=lan,
                       items=[_video(user, e, _episode_title(e)) for e in eps])

    if kind == "music":
        lib = await session.get(Library, rest)
        if lib is None or lib.kind != "music" or not allowed(user.max_age, lib.age_rating):
            raise HTTPException(404, "No such folder")
        albums = (await session.scalars(select(MusicAlbum).where(MusicAlbum.library_id == lib.id)
                                        .order_by(MusicAlbum.artist, MusicAlbum.title))).all()
        return DlnaOut(id=id, parent="0", title=lib.name, lan_url=lan,
                       folders=[DlnaFolder(id=f"album:{a.id}", title=f"{a.artist}: {a.title}") for a in albums])

    if kind == "album":
        a = await session.get(MusicAlbum, rest)
        lib = await session.get(Library, a.library_id) if a else None
        if a is None or lib is None or not allowed(user.max_age, lib.age_rating):
            raise HTTPException(404, "No such folder")
        tracks = (await session.scalars(select(Track).where(Track.album_id == a.id, song_shown())
                                        .order_by(Track.disc_no, Track.track_no, Track.title))).all()
        art = f"/api/music/albums/{a.id}/cover?token={create_media_token(user, a.id)}" if a.cover_ready else None
        items = [DlnaItem(id=f"t:{t.id}", title=t.title, kind="audio", size=t.size, duration=t.duration,
                          mime=AUDIO_MIME.get(Path(t.rel_path).suffix.lower(), "audio/mpeg") if t.playable else "audio/mpeg",
                          path=f"/api/music/tracks/{t.id}/stream?token={create_media_token(user, t.id)}",
                          art=art, artist=t.artist or a.artist, album=a.title, track_no=t.track_no, year=t.year)
                 for t in tracks]
        return DlnaOut(id=id, parent=f"music:{a.library_id}", title=a.title, items=items, lan_url=lan)

    raise HTTPException(404, "No such folder")
