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

import logging
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Library
from .browse import marked

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
    known = set((await session.scalars(select(Library.path))).all())
    order = (await session.scalar(select(func.max(Library.sort_order)))) or 0
    created = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith((".", "$")) or str(child) in known or marked(child):
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
