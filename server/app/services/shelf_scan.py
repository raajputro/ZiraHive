"""Scanning music, audiobook, ebook and comic categories.

Music       every audio file is a track; tracks in one folder with the same album name are an album.
Audiobooks  a file in the category folder is a book; a folder of audio files is one book (its
            files are the parts, in name order, CD1/CD2 subfolders included); a folder of
            several .m4b files holds one book per file.
Books and   every .epub, .pdf, .cbz, .cbr, .cb7 and .cbt is a book or comic; a folder of page
comics      images (2 or more, with no book files next to them) is a comic too.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from ..db import sessionmaker
from ..models import Book, Library, MusicAlbum, Track, User
from . import storage
from .browse import DATA_MARK, walk_filter
from .shelf_files import (AUDIO_EXT, COMIC_EXT, EBOOK_EXT, IMAGE_EXT, audio_info, clean_name, comic_meta,
                          comic_series_from_name, embedded_art, epub_meta, folder_image, natural_key, pdf_meta,
                          save_cover)

log = logging.getLogger(__name__)

SHELF_KINDS = {"music", "audiobooks", "books", "comics"}
_DISC_DIR = re.compile(r"^(?:cd|disc|disk|part|pt)[ ._\-]?\d{1,2}\b", re.I)
_LEADING_TRACK = re.compile(r"^\s*(?:\d{1,2}[-.])?(?P<n>\d{1,3})\s*[-._ )]+\s*(?=\S)")


def _rel(root: Path, p: Path) -> str:
    return str(PurePosixPath(*p.relative_to(root).parts))


def _stat(p: Path) -> tuple[int, float]:
    try:
        st = p.stat()
        return st.st_size, st.st_mtime
    except OSError:
        return 0, 0.0


def _visible(p: Path) -> bool:
    return not p.name.startswith((".", "$", "@"))


# ---------------------------------------------------------------- walking

def walk_music(root: Path) -> list[tuple[str, int, float]]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = walk_filter(dirpath, dirnames)
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in AUDIO_EXT and _visible(p):
                out.append((_rel(root, p), *_stat(p)))
    return out


@dataclass
class Unit:
    """One book: its path relative to the category, and its file(s)."""
    rel: str
    files: list[Path] = field(default_factory=list)
    folder: bool = False
    size: int = 0
    mtime: float = 0.0


def _finish(unit: Unit) -> Unit:
    for f in unit.files:
        s, m = _stat(f)
        unit.size += s
        unit.mtime = max(unit.mtime, m)
    unit.mtime += len(unit.files) / 1000  # adding or removing a part counts as a change
    return unit


def walk_audiobooks(root: Path) -> list[Unit]:
    units: list[Unit] = []

    def audio_in(d: Path) -> list[Path]:
        try:
            return sorted((p for p in d.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXT and _visible(p)),
                          key=lambda p: natural_key(p.name))
        except OSError:
            return []

    def subdirs(d: Path) -> list[Path]:
        try:
            return sorted((p for p in d.iterdir() if p.is_dir() and _visible(p) and not (p / DATA_MARK).exists()),
                          key=lambda p: natural_key(p.name))
        except OSError:
            return []

    def visit(d: Path) -> None:
        files, dirs = audio_in(d), subdirs(d)
        discs = [s for s in dirs if _DISC_DIR.match(s.name) and audio_in(s)]
        if d == root or (files and len(files) > 1 and all(f.suffix.lower() == ".m4b" for f in files)):
            units.extend(_finish(Unit(_rel(root, f), [f])) for f in files)
        elif files or (discs and len(discs) == len(dirs)):
            parts = list(files)
            for s in discs:
                parts += audio_in(s)
            units.append(_finish(Unit(_rel(root, d), parts, folder=True)))
            dirs = [s for s in dirs if s not in discs]
            if files:
                return
        for s in dirs:
            visit(s)

    visit(root)
    return units


def walk_books(root: Path) -> list[Unit]:
    units: list[Unit] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(walk_filter(dirpath, dirnames))
        d = Path(dirpath)
        books = [d / f for f in filenames if Path(f).suffix.lower() in EBOOK_EXT | COMIC_EXT and _visible(d / f)]
        images = [f for f in filenames if Path(f).suffix.lower() in IMAGE_EXT]
        units.extend(_finish(Unit(_rel(root, b), [b])) for b in books)
        if d != root and not books and len(images) >= 2:
            units.append(_finish(Unit(_rel(root, d), [d / f for f in images], folder=True)))
    return units


# ------------------------------------------------------------------ music

def _track_fields(root: Path, rel: str) -> dict:
    p = root / rel
    info = audio_info(p)
    parts = PurePosixPath(rel).parts
    stem = Path(rel).stem
    title, track = info.title, info.track
    if not title:
        m = _LEADING_TRACK.match(stem)
        title = clean_name(stem[m.end():] if m else stem)
        if m and track is None:
            track = int(m.group("n"))
    folder = str(PurePosixPath(rel).parent) if len(parts) > 1 else ""
    album = info.album or (clean_name(parts[-2]) if len(parts) > 1 else "Singles")
    artist = info.artist or (clean_name(parts[-3]) if len(parts) > 2 else None)
    return {"title": title[:512], "artist": (artist or None) and artist[:512], "album_title": album[:512],
            "track_no": track, "disc_no": info.disc, "year": info.year, "genre": info.genre and info.genre[:128],
            "duration": info.duration, "codec": info.codec, "playable": info.playable,
            "_key": f"{folder}|{album.lower()}"[:1024], "_album_artist": info.album_artist}


async def scan_music(session, lib: Library, root: Path, stats: dict) -> None:
    files = await asyncio.to_thread(walk_music, root)
    existing = {t.rel_path: t for t in (await session.scalars(select(Track).where(Track.library_id == lib.id))).all()}
    albums = {a.key: a for a in (await session.scalars(select(MusicAlbum).where(MusicAlbum.library_id == lib.id))).all()}
    touched: dict[str, str | None] = {}  # album id -> album artist tag seen in this scan
    seen, done = set(), 0
    for rel, size, mtime in files:
        seen.add(rel)
        t = existing.get(rel)
        if t and t.size == size and t.mtime == mtime and not t.missing:
            continue
        fields = await asyncio.to_thread(_track_fields, root, rel)
        key, album_artist = fields.pop("_key"), fields.pop("_album_artist")
        album = albums.get(key)
        if album is None:
            album = MusicAlbum(library_id=lib.id, key=key, title=fields["album_title"])
            session.add(album)
            await session.flush()
            albums[key] = album
            stats["added_albums"] = stats.get("added_albums", 0) + 1
        if t is None:
            t = Track(library_id=lib.id, rel_path=rel, title=fields["title"])
            session.add(t)
            stats["added"] += 1
        else:
            stats["updated"] += 1
        for k, v in fields.items():
            setattr(t, k, v)
        t.album_id, t.size, t.mtime, t.missing = album.id, size, mtime, False
        touched[album.id] = touched.get(album.id) or album_artist
        done += 1
        if done % 50 == 0:
            await session.commit()
    for rel, t in existing.items():
        if rel not in seen and not t.missing:
            t.missing = True
            stats["missing"] += 1
    await session.flush()
    for album_id, album_artist in touched.items():
        album = await session.get(MusicAlbum, album_id)
        tracks = (await session.scalars(select(Track).where(Track.album_id == album_id, Track.missing.is_(False))
                                        .order_by(Track.disc_no, Track.track_no, Track.rel_path))).all()
        if not tracks:
            continue
        artists = {t.artist for t in tracks if t.artist}
        album.artist = (album_artist or (artists.pop() if len(artists) == 1 else
                                         "Various artists" if artists else "Unknown artist"))[:512]
        years = [t.year for t in tracks if t.year]
        album.year = max(years) if years else None
        genres = Counter(t.genre for t in tracks if t.genre)
        album.genre = genres.most_common(1)[0][0] if genres else None
        if not album.cover_ready:
            first = root / tracks[0].rel_path
            art = await asyncio.to_thread(embedded_art, first) or await asyncio.to_thread(folder_image, first.parent)
            album.cover_ready = await asyncio.to_thread(save_cover, art, storage.cover_path("album", album.id))
    stats["total"] = len(files)


# ------------------------------------------------------------- audiobooks

def _audiobook_fields(root: Path, unit: Unit) -> dict:
    from .tracks import probe_tracks

    first = unit.files[0]
    tags = audio_info(first)
    parts, chapters, start = [], [], 0.0
    for i, f in enumerate(unit.files):
        info = tags if i == 0 else audio_info(f)
        dur = info.duration or 0.0
        parts.append({"rel": _rel(root, f), "duration": dur, "playable": info.playable})
        if len(unit.files) > 1:
            m = _LEADING_TRACK.match(f.stem)
            name = info.title if info.title and info.title != tags.album else clean_name(f.stem[m.end():] if m else f.stem)
            chapters.append({"title": name or f"Part {i + 1}", "start": round(start, 3)})
        start += dur
    if len(unit.files) == 1:
        try:
            chapters = [{"title": c["title"] or f"Chapter {n + 1}", "start": c["start"]}
                        for n, c in enumerate(probe_tracks(first)["chapters"])]
        except Exception:
            chapters = []
    rel_parts = PurePosixPath(unit.rel).parts
    name = clean_name(Path(unit.rel).stem if not unit.folder else rel_parts[-1])
    author = tags.album_artist or tags.artist or (clean_name(rel_parts[-2]) if len(rel_parts) > 1 else None)
    title = tags.album or (tags.title if not unit.folder else None) or name
    return {"kind": "audiobook", "format": "audio", "title": title[:512], "author": author and author[:512],
            "narrator": tags.composer and tags.composer[:512], "year": tags.year, "description": tags.comment,
            "duration": start or None, "pages": None, "parts_json": json.dumps(parts),
            "chapters_json": json.dumps(chapters), "_art": lambda: embedded_art(first)
            or folder_image(first.parent, first.stem if not unit.folder else None)}


# ------------------------------------------------------- ebooks and comics

def _book_fields(root: Path, unit: Unit) -> dict:
    path = root / unit.rel
    ext = "images" if unit.folder else path.suffix.lower().lstrip(".")
    rel_parts = PurePosixPath(unit.rel).parts
    stem = rel_parts[-1] if unit.folder else Path(unit.rel).stem
    if ext == "epub":
        meta, kind = epub_meta(path), "ebook"
    elif ext == "pdf":
        meta, kind = pdf_meta(path), "ebook"
    else:
        meta, kind = comic_meta(path), "comic"
    series, index = meta.series, meta.series_index
    if kind == "comic" and not series:
        series, index = comic_series_from_name(stem)
        if unit.folder and len(rel_parts) > 1:  # Manga/One Piece/Chapter 001/
            series = clean_name(rel_parts[-2])
            meta.title = meta.title or f"{series}: {clean_name(stem)}"
    title = meta.title or clean_name(stem)
    parts = {"pages": meta.page_names, "rtl": meta.rtl} if kind == "comic" else None
    cover = meta.cover
    return {"kind": kind, "format": ext, "title": title[:512], "author": meta.author and meta.author[:512],
            "narrator": None, "year": meta.year, "description": meta.description, "language": meta.language,
            "series_name": series and series[:512], "series_index": index, "duration": None, "pages": meta.pages,
            "parts_json": json.dumps(parts) if parts else None, "chapters_json": None,
            "_art": lambda: cover or (folder_image(path.parent, path.stem) if not unit.folder else None)}


async def scan_books(session, lib: Library, root: Path, stats: dict) -> None:
    audio = lib.kind == "audiobooks"
    units = await asyncio.to_thread(walk_audiobooks if audio else walk_books, root)
    existing = {b.rel_path: b for b in (await session.scalars(select(Book).where(Book.library_id == lib.id))).all()}
    seen = set()
    for unit in units:
        seen.add(unit.rel)
        b = existing.get(unit.rel)
        if b and b.size == unit.size and b.mtime == unit.mtime and not b.missing:
            continue
        try:
            fields = await asyncio.to_thread(_audiobook_fields if audio else _book_fields, root, unit)
        except Exception as exc:  # one broken file must not stop the scan
            log.warning("couldn't read %s: %s", unit.rel, exc)
            continue
        art = fields.pop("_art")
        if b is None:
            b = Book(library_id=lib.id, rel_path=unit.rel, kind=fields["kind"], format=fields["format"],
                     title=fields["title"])
            session.add(b)
            await session.flush()
            stats["added"] += 1
        else:
            stats["updated"] += 1
            # the file changed: pictures of its old pages must not be shown
            pages = storage.page_cache_path(b.id, 1, 1).parent
            await asyncio.to_thread(shutil.rmtree, pages, True)
        for k, v in fields.items():
            setattr(b, k, v)
        b.size, b.mtime, b.missing = unit.size, unit.mtime, False
        b.cover_ready = await asyncio.to_thread(lambda: save_cover(art(), storage.cover_path("book", b.id)))
        await session.commit()
    for rel, b in existing.items():
        if rel not in seen and not b.missing:
            b.missing = True
            stats["missing"] += 1
    stats["total"] = len(units)


# ------------------------------------------------------------------ entry

_NOUN = {"music": ("song", "songs"), "audiobooks": ("audiobook", "audiobooks"),
         "books": ("book", "books"), "comics": ("comic", "comics")}
_SECTION = {"music": "/listen", "audiobooks": "/listen/audiobooks", "books": "/read", "comics": "/read"}


async def scan(library_id: str) -> dict:
    stats = {"added": 0, "updated": 0, "missing": 0, "total": 0}
    async with sessionmaker()() as session:
        lib = await session.get(Library, library_id)
        if lib is None:
            return stats
        root = Path(lib.path)
        if not root.is_dir():
            log.warning("library folder not found: %s", root)
            model = Track if lib.kind == "music" else Book
            for row in (await session.scalars(select(model).where(model.library_id == lib.id))).all():
                row.missing = True
            await session.commit()
            return stats
        if lib.kind == "music":
            await scan_music(session, lib, root, stats)
        else:
            await scan_books(session, lib, root, stats)
        lib.last_scan_at = datetime.now(timezone.utc)
        if stats["added"]:
            from .events import notify

            n = stats["added"]
            one, many = _NOUN[lib.kind]
            for user in (await session.scalars(select(User))).all():
                await notify(session, user, "media", f"{n} new {one if n == 1 else many} in {lib.name}",
                             link=_SECTION[lib.kind])
        await session.commit()
    log.info("scan of %s (%s) finished: %s", lib.name, lib.kind, stats)
    return stats
