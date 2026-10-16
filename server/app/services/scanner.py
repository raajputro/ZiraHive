"""Movie library scanner: walk folders, parse names, probe files, make posters."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import httpx
from sqlalchemy import select

from ..config import get_settings
from ..db import sessionmaker
from ..models import Library, MediaItem
from . import media_tools, storage

log = logging.getLogger(__name__)

MOVIE_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".wmv", ".ts", ".m2ts", ".mpg", ".mpeg"}
_SKIP_WORDS = re.compile(r"\b(sample|trailer|featurette)\b", re.I)
_YEAR_PAREN = re.compile(r"^(?P<title>.+?)\s*[\(\[](?P<year>(19|20)\d{2})[\)\]]")
_YEAR_DOTTED = re.compile(r"^(?P<title>.+?)[ ._\-]+(?P<year>(19|20)\d{2})(?=$|[ ._\-\[\(])")
_JUNK = re.compile(
    r"[ ._\-\[\(]+(2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|hdrip|"
    r"dvdrip|hdtv|x264|x265|h\.?264|h\.?265|hevc|aac|ac3|dts|hdr|10bit|proper|repack|extended|"
    r"remastered|unrated)(?=$|[ ._\-\[\]\(\)]).*$", re.I)


def parse_movie_name(filename: str) -> tuple[str, int | None]:
    """'The.Matrix.1999.1080p.BluRay.x264.mkv' -> ('The Matrix', 1999)"""
    stem = Path(filename).stem
    for rx in (_YEAR_PAREN, _YEAR_DOTTED):
        m = rx.match(stem)
        if m:
            title = re.sub(r"[._]+", " ", m.group("title")).strip(" -")
            if title:
                return title, int(m.group("year"))
    title = _JUNK.sub("", stem)
    title = re.sub(r"[._]+", " ", title).strip(" -")
    return title or stem, None


def _walk(root: Path) -> list[tuple[str, int, float]]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if Path(fn).suffix.lower() not in MOVIE_EXT or _SKIP_WORDS.search(fn):
                continue
            full = Path(dirpath) / fn
            try:
                st = full.stat()
            except OSError:
                continue
            rel = PurePosixPath(*full.relative_to(root).parts)
            found.append((str(rel), st.st_size, st.st_mtime))
    return found


async def _tmdb_lookup(client: httpx.AsyncClient, title: str, year: int | None) -> dict | None:
    key = get_settings().tmdb_api_key
    if not key:
        return None
    params = {"api_key": key, "query": title}
    if year:
        params["year"] = str(year)
    try:
        r = await client.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=15)
        r.raise_for_status()
        results = r.json().get("results") or []
        return results[0] if results else None
    except Exception as exc:
        log.info("TMDB lookup failed for %s: %s", title, exc)
        return None


async def _fetch_poster(client: httpx.AsyncClient, poster: str, dest: Path) -> bool:
    try:
        r = await client.get(f"https://image.tmdb.org/t/p/w500{poster}", timeout=30)
        r.raise_for_status()
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(r.content)
        await asyncio.to_thread(media_tools.make_image_thumb, tmp, dest, 500)
        tmp.unlink(missing_ok=True)
        return True
    except Exception as exc:
        log.info("poster download failed: %s", exc)
        return False


async def scan(library_id: str) -> dict:
    stats = {"added": 0, "updated": 0, "missing": 0, "total": 0}
    async with sessionmaker()() as session:
        lib = await session.get(Library, library_id)
        if lib is None:
            return stats
        root = Path(lib.path)
        if not root.is_dir():
            log.warning("library path not found: %s", root)
            return stats
        files = await asyncio.to_thread(_walk, root)
        existing = {m.rel_path: m for m in (await session.scalars(
            select(MediaItem).where(MediaItem.library_id == lib.id))).all()}
        seen = set()
        async with httpx.AsyncClient() as client:
            for rel, size, mtime in files:
                seen.add(rel)
                item = existing.get(rel)
                if item and item.size == size and item.mtime == mtime and not item.missing:
                    continue
                full = root / rel
                info = await asyncio.to_thread(media_tools.probe, full)
                if item is None:
                    title, year = parse_movie_name(PurePosixPath(rel).name)
                    item = MediaItem(library_id=lib.id, rel_path=rel, title=title, year=year)
                    session.add(item)
                    await session.flush()
                    stats["added"] += 1
                    meta = await _tmdb_lookup(client, title, year)
                    if meta:
                        item.tmdb_id = meta.get("id")
                        item.title = meta.get("title") or title
                        item.overview = meta.get("overview")
                        rd = meta.get("release_date") or ""
                        item.year = int(rd[:4]) if rd[:4].isdigit() else year
                        if meta.get("poster_path"):
                            item.poster_ready = await _fetch_poster(
                                client, meta["poster_path"], storage.poster_path(item.id))
                else:
                    stats["updated"] += 1
                item.size, item.mtime, item.missing = size, mtime, False
                item.container, item.video_codec, item.audio_codec = (
                    info.container, info.video_codec, info.audio_codec)
                item.width, item.height, item.duration = info.width, info.height, info.duration
                if not item.poster_ready:
                    at = (info.duration or 0) * 0.1
                    item.poster_ready = await asyncio.to_thread(
                        media_tools.make_video_thumb, full, storage.poster_path(item.id), at, 500)
                await session.commit()
        for rel, item in existing.items():
            if rel not in seen and not item.missing:
                item.missing = True
                stats["missing"] += 1
        lib.last_scan_at = datetime.now(timezone.utc)
        stats["total"] = len(files)
        await session.commit()
    log.info("scan of %s finished: %s", library_id, stats)
    return stats
