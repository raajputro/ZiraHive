"""Turn the folders in your media folder into categories (libraries) automatically.

    D:/Media/English Movies   -> "English Movies"  (movies)
    D:/Media/hindi_movies     -> "Hindi Movies"    (movies)
    D:/Media/Web Series       -> "Web Series"      (shows)
    D:/Media/Animation        -> "Animation"       (mixed: movies and series together)
    D:/Media/Music            -> "Music"           (music)
    D:/Media/Audiobooks       -> "Audiobooks"      (audiobooks)
    D:/Media/Ebooks           -> "Ebooks"          (books: EPUB and PDF)
    D:/Media/Comics           -> "Comics"          (comics: CBZ, CBR, folders of pages)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (Book, BookProgress, FedGuest, Library, MediaItem, MusicAlbum, OfflineCopy,
                      PlaylistTrack, Series, Track, TrackStat, WatchParty, WatchProgress)
from .browse import marked, preferred, same_folder_key

log = logging.getLogger(__name__)

_AUDIOBOOKS = re.compile(r"audio ?books?|\bgolpo\b|story ?tapes?", re.I)
_MUSIC = re.compile(r"music|songs?\b|\bgaan\b|sangeet|sangit|\bgeet|qawwali|\bmp3\b|albums?\b|playlist", re.I)
_COMICS = re.compile(r"comic|manga|manhwa|webtoon|graphic novel", re.I)
_BOOKS = re.compile(r"books?\b|ebook|novel|\bpdfs?\b|reading|library|\bboi\b", re.I)
_SHOWS = re.compile(r"series|\bshows?\b|\btv\b|drama|sitcom|season|natok|serial", re.I)
_MIXED = re.compile(r"anim|cartoon|kids|children|anime", re.I)
_SMALL = {"and", "of", "the", "a", "an", "in", "on"}


def pretty_name(folder: str) -> str:
    """'english_movies' -> 'English Movies'; keeps words that already have capitals (TV, BBC)."""
    words = [w for w in re.split(r"[\s_.\-]+", folder.strip()) if w]
    out = []
    for i, w in enumerate(words):
        if any(c.isupper() for c in w):
            out.append(w)
        elif i > 0 and w in _SMALL:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out) or folder


def guess_kind(name: str) -> str:
    for kind, pattern in (("audiobooks", _AUDIOBOOKS), ("music", _MUSIC), ("comics", _COMICS), ("books", _BOOKS)):
        if pattern.search(name):
            return kind
    if _SHOWS.search(name):
        return "shows"
    if _MIXED.search(name):
        return "mixed"
    return "movies"


async def discover(session: AsyncSession) -> list[Library]:
    """Create a library for every new top-level folder in media_root. Returns the new ones."""
    root_setting = get_settings().media_root
    if not root_setting:
        return []
    root = Path(root_setting)
    if not root.is_dir():
        log.warning("media folder not found: %s", root)
        return []
    known = {same_folder_key(p) for p in (await session.scalars(select(Library.path))).all()}
    order = (await session.scalar(select(func.max(Library.sort_order)))) or 0
    created = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith((".", "$")) or same_folder_key(child) in known or marked(child):
            continue
        order += 1
        name = pretty_name(child.name)
        lib = Library(name=name, path=str(child), kind=guess_kind(name), sort_order=order)
        session.add(lib)
        created.append(lib)
        log.info("found category %s (%s) at %s", name, lib.kind, child)
    if created:
        await session.commit()
    return created


# ------------------------------------------------------------ duplicate categories
# A folder could become two categories when it was reached two ways (with Docker, G:\Media is
# both the media folder /media and part of the drive /drives/g). merge_duplicates() folds them
# back into one, keeping everyone's progress, favourites, playlists and offline copies.

# (item model, its group model and group column, rows that point at an item: (model, column, unique-with))
_ITEM_KINDS = [
    (MediaItem, Series, "series_id", [(WatchProgress, "media_id", "user_id"),
                                      (OfflineCopy, "media_id", "quality"),
                                      (WatchParty, "media_id", None)]),
    (Track, MusicAlbum, "album_id", [(TrackStat, "track_id", "user_id"),
                                     (PlaylistTrack, "track_id", None)]),
    (Book, None, None, [(BookProgress, "book_id", "user_id")]),
]


async def _move_rows(session: AsyncSession, model, col: str, unique_with: str | None,
                     old_id: str, new_id: str) -> None:
    """Point rows at new_id instead of old_id. Where both items already have a row for the same
    person (or quality), the more recently updated one wins."""
    column = getattr(model, col)
    if unique_with is None:
        await session.execute(update(model).where(column == old_id).values({col: new_id}))
        return
    other = getattr(model, unique_with)
    stamp = model.__table__.c.get("updated_at")
    if stamp is None:
        stamp = model.__table__.c.get("last_played")
    for row in (await session.scalars(select(model).where(column == old_id))).all():
        clash = await session.scalar(select(model).where(column == new_id, other == getattr(row, unique_with)))
        if clash is not None and model is TrackStat:  # same song twice: add the plays up
            clash.plays = (clash.plays or 0) + (row.plays or 0)
            clash.favorite = clash.favorite or row.favorite
            if row.last_played and (clash.last_played is None or row.last_played > clash.last_played):
                clash.last_played = row.last_played
            await session.delete(row)
            continue
        if clash is not None:
            mine = getattr(row, stamp.key) if stamp is not None else None
            theirs = getattr(clash, stamp.key) if stamp is not None else None
            if mine is None or (theirs is not None and mine <= theirs):
                await session.delete(row)
                continue
            await session.delete(clash)
            await session.flush()
        setattr(row, col, new_id)
    await session.flush()


async def _merge_into(session: AsyncSession, keep: Library, dup: Library) -> None:
    for item_model, group_model, group_col, refs in _ITEM_KINDS:
        group_map: dict[str, str] = {}
        if group_model is not None:
            kept = {g.key: g.id for g in (await session.scalars(
                select(group_model).where(group_model.library_id == keep.id))).all()}
            for g in (await session.scalars(select(group_model).where(group_model.library_id == dup.id))).all():
                if g.key in kept:
                    group_map[g.id] = kept[g.key]
                else:  # a series or album only the duplicate knows: move it over
                    g.library_id = keep.id
            await session.flush()
        kept_items = {i.rel_path: i.id for i in (await session.scalars(
            select(item_model).where(item_model.library_id == keep.id))).all()}
        for item in (await session.scalars(select(item_model).where(item_model.library_id == dup.id))).all():
            if item.rel_path in kept_items:
                for model, col, unique_with in refs:
                    await _move_rows(session, model, col, unique_with, item.id, kept_items[item.rel_path])
            else:
                item.library_id = keep.id
                if group_col and getattr(item, group_col) in group_map:
                    setattr(item, group_col, group_map[getattr(item, group_col)])
        await session.flush()
    for guest in (await session.scalars(select(FedGuest))).all():
        ids = json.loads(guest.library_ids or "[]")
        if dup.id in ids:
            guest.library_ids = json.dumps(list(dict.fromkeys(keep.id if i == dup.id else i for i in ids)))
    if keep.age_rating is None:
        keep.age_rating = dup.age_rating
    keep.sort_order = min(keep.sort_order, dup.sort_order)
    await session.execute(delete(Library).where(Library.id == dup.id))
    await session.flush()


async def merge_duplicates(session: AsyncSession) -> list[Library]:
    """Fold categories that are the same folder into one, and store every category inside the
    media folder by its media-folder path. Returns the categories that were kept from a merge."""
    libs = (await session.scalars(select(Library).order_by(Library.created_at))).all()
    groups: dict[str, list[Library]] = {}
    for lib in libs:
        groups.setdefault(same_folder_key(lib.path), []).append(lib)
    merged = []
    for group in groups.values():
        keep = next((l for l in group if preferred(l.path) == l.path), group[0])
        for dup in group:
            if dup is not keep:
                log.info("merging duplicate category %s (%s) into %s (%s)", dup.name, dup.path, keep.name, keep.path)
                await _merge_into(session, keep, dup)
        if len(group) > 1:
            merged.append(keep)
        if preferred(keep.path) != keep.path:
            keep.path = preferred(keep.path)
    await session.commit()
    return merged
