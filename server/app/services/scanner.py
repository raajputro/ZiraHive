"""Library scanner: walk folders, tell movies from episodes, probe files, make posters."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import httpx
from sqlalchemy import select

from ..config import get_settings
from ..db import sessionmaker
from ..models import Library, MediaItem, Series
from . import media_tools, storage

log = logging.getLogger(__name__)

MOVIE_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".wmv", ".ts", ".m2ts", ".mpg", ".mpeg"}
_SKIP_WORDS = re.compile(r"\b(sample|trailer|featurette)\b", re.I)
_YEAR_PAREN = re.compile(r"^(?P<title>.+?)\s*[\(\[](?P<year>(19|20)\d{2})[\)\]]")
_YEAR_DOTTED = re.compile(r"^(?P<title>.+?)[ ._\-]+(?P<year>(19|20)\d{2})(?=$|[ ._\-\[\(])")
_JUNK = re.compile(
    r"[ ._\-\[\(]+(2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|hdrip|"
    r"dvdrip|hdtv|x264|x265|h\.?264|h\.?265|hevc|aac|ac3|dts|hdr|10bit|proper|repack|extended|"
    r"remastered|unrated|nf|amzn|hulu|dsnp|zee5|hoichoi|chorki)(?=$|[ ._\-\[\]\(\)]).*$", re.I)

# Episode patterns, most reliable first
_SXXEYY = re.compile(r"(?<![A-Za-z0-9])[Ss](?P<s>\d{1,2})[ ._\-]?[Ee](?P<e>\d{1,3})(?:[ ._\-]?[Ee]\d{1,3})*")
_NXNN = re.compile(r"(?<![\dA-Za-z])(?P<s>\d{1,2})x(?P<e>\d{2,3})(?![\dA-Za-z])")
_SEASON_DIR = re.compile(r"^(?:season|series|book|part|volume|vol|s)[ ._\-]?(?P<s>\d{1,2})$", re.I)
_EP_WORD = re.compile(r"(?:^|[ ._\-\[])(?:episode|ep|e)[ ._\-]?(?P<e>\d{1,3})(?=$|[ ._\-\]\)])", re.I)
_LEADING_NUM = re.compile(r"^(?P<e>\d{1,3})(?=$|[ ._\-])")


def _clean(text: str) -> str:
    text = _JUNK.sub("", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    text = re.sub(r"[\s\-]*[\(\[]\s*$", "", text)  # opener left dangling by junk removal
    text = re.sub(r"^[\)\]\s\-]+", "", text)
    return text.strip(" -")


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


def _title_and_year(text: str) -> tuple[str, int | None]:
    m = _YEAR_PAREN.match(text) or _YEAR_DOTTED.match(text)
    if m:
        return _clean(m.group("title")), int(m.group("year"))
    return _clean(text), None


def series_key(title: str) -> str:
    return re.sub(r"[^0-9a-zঀ-৿ऀ-ॿ]+", "", title.lower()) or title.lower()


@dataclass
class EpisodeInfo:
    series_title: str
    series_year: int | None
    season: int | None
    episode: int | None
    episode_title: str | None


def parse_episode(rel_path: str, strict: bool = False) -> EpisodeInfo | None:
    """Work out series, season and episode from a path inside a library.

    'Mirzapur/Season 2/Mirzapur.S02E05.1080p.mkv' -> Mirzapur, season 2, episode 5
    'Friends (1994)/Season 1/01 - The Pilot.mkv'   -> Friends (1994), season 1, episode 1
    strict=True (mixed libraries) only accepts explicit S01E02 / 1x02 names; anything
    else is treated as a movie and None is returned.
    """
    parts = PurePosixPath(rel_path).parts
    stem, dirs = Path(parts[-1]).stem, list(parts[:-1])

    season_idx, dir_season = None, None
    for i, d in enumerate(dirs):
        m = _SEASON_DIR.match(d.strip())
        if m:
            season_idx, dir_season = i, int(m.group("s"))

    m = _SXXEYY.search(stem) or _NXNN.search(stem)
    if m:
        season, episode = int(m.group("s")), int(m.group("e"))
        name_part, rest = stem[: m.start()], stem[m.end():]
    elif strict:
        return None
    else:
        m = _EP_WORD.search(stem) or _LEADING_NUM.match(stem)
        season = dir_season or 1
        if m:
            episode = int(m.group("e"))
            name_part, rest = stem[: m.start()], stem[m.end():]
        else:
            episode, name_part, rest = None, "", stem

    # The show's folder is the one above "Season N", or the file's own folder.
    if season_idx is not None and season_idx > 0:
        show_dir = dirs[season_idx - 1]
    elif season_idx is None and dirs:
        show_dir = dirs[-1]
    else:
        show_dir = None
    title, year = _title_and_year(show_dir) if show_dir else _title_and_year(name_part)
    if not title:
        title, year = _title_and_year(name_part or stem)
    ep_title = _clean(rest) or None
    if ep_title and ep_title.lower() == title.lower():
        ep_title = None
    return EpisodeInfo(title or stem, year, season, episode, ep_title)


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


async def _tmdb_lookup(client: httpx.AsyncClient, title: str, year: int | None,
                       kind: str = "movie") -> dict | None:
    key = get_settings().tmdb_api_key
    if not key:
        return None
    params = {"api_key": key, "query": title}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = str(year)
    try:
        r = await client.get(f"https://api.themoviedb.org/3/search/{kind}", params=params, timeout=15)
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


class _SeriesCache:
    def __init__(self, session, client, lib: Library):
        self.session, self.client, self.lib = session, client, lib
        self.by_key: dict[str, Series] = {}

    async def load(self) -> None:
        for s in (await self.session.scalars(select(Series).where(Series.library_id == self.lib.id))).all():
            self.by_key[s.key] = s

    async def get(self, ep: EpisodeInfo) -> Series:
        key = series_key(ep.series_title)
        series = self.by_key.get(key)
        if series is None:
            series = Series(library_id=self.lib.id, key=key, title=ep.series_title, year=ep.series_year)
            self.session.add(series)
            await self.session.flush()
            self.by_key[key] = series
            meta = await _tmdb_lookup(self.client, ep.series_title, ep.series_year, "tv")
            if meta:
                series.tmdb_id = meta.get("id")
                series.title = meta.get("name") or series.title
                series.overview = meta.get("overview")
                fa = meta.get("first_air_date") or ""
                series.year = int(fa[:4]) if fa[:4].isdigit() else series.year
                if meta.get("poster_path"):
                    series.poster_ready = await _fetch_poster(
                        self.client, meta["poster_path"], storage.series_poster_path(series.id))
        return series


def _episode_label(ep: EpisodeInfo, rel: str) -> str:
    if ep.episode_title:
        return ep.episode_title
    if ep.episode is not None:
        return f"Episode {ep.episode}"
    return _clean(Path(rel).stem) or Path(rel).stem


async def scan(library_id: str) -> dict:
    stats = {"added": 0, "updated": 0, "missing": 0, "total": 0}
    async with sessionmaker()() as session:
        lib = await session.get(Library, library_id)
        if lib is None:
            return stats
        root = Path(lib.path)
        existing = {m.rel_path: m for m in (await session.scalars(
            select(MediaItem).where(MediaItem.library_id == lib.id))).all()}
        if not root.is_dir():
            # Drive unplugged or folder moved: hide its titles until it comes back.
            log.warning("library folder not found: %s", root)
            for item in existing.values():
                item.missing = True
            await session.commit()
            return stats
        files = await asyncio.to_thread(_walk, root)
        seen = set()
        async with httpx.AsyncClient() as client:
            cache = _SeriesCache(session, client, lib)
            await cache.load()
            for rel, size, mtime in files:
                seen.add(rel)
                item = existing.get(rel)
                if item and item.size == size and item.mtime == mtime and not item.missing:
                    continue
                full = root / rel
                info = await asyncio.to_thread(media_tools.probe, full)
                if item is None:
                    item = MediaItem(library_id=lib.id, rel_path=rel, title=Path(rel).stem)
                    session.add(item)
                    await session.flush()
                    stats["added"] += 1
                else:
                    stats["updated"] += 1

                ep = None if lib.kind == "movies" else parse_episode(rel, strict=lib.kind == "mixed")
                if ep:
                    series = await cache.get(ep)
                    item.series_id, item.season, item.episode = series.id, ep.season, ep.episode
                    item.episode_title = ep.episode_title
                    item.title, item.year, item.tmdb_id = _episode_label(ep, rel), None, None
                else:
                    item.series_id = item.season = item.episode = item.episode_title = None
                    if item.tmdb_id is None:  # keep titles TMDB already fixed
                        item.title, item.year = parse_movie_name(PurePosixPath(rel).name)
                        meta = await _tmdb_lookup(client, item.title, item.year)
                        if meta:
                            item.tmdb_id = meta.get("id")
                            item.title = meta.get("title") or item.title
                            item.overview = meta.get("overview")
                            rd = meta.get("release_date") or ""
                            item.year = int(rd[:4]) if rd[:4].isdigit() else item.year
                            if meta.get("poster_path"):
                                item.poster_ready = await _fetch_poster(
                                    client, meta["poster_path"], storage.poster_path(item.id))

                item.size, item.mtime, item.missing = size, mtime, False
                item.container, item.video_codec, item.audio_codec = (
                    info.container, info.video_codec, info.audio_codec)
                item.width, item.height, item.duration = info.width, info.height, info.duration
                if not item.poster_ready:
                    at = (info.duration or 0) * 0.1
                    item.poster_ready = await asyncio.to_thread(
                        media_tools.make_video_thumb, full, storage.poster_path(item.id), at, 500)
                if item.series_id:
                    series = await session.get(Series, item.series_id)
                    if series and not series.poster_ready and item.poster_ready:
                        # No TMDB poster: use a frame from the first episode we see.
                        await asyncio.to_thread(shutil.copyfile, storage.poster_path(item.id),
                                                storage.series_poster_path(series.id))
                        series.poster_ready = True
                await session.commit()
        for rel, item in existing.items():
            if rel not in seen and not item.missing:
                item.missing = True
                stats["missing"] += 1
        lib.last_scan_at = datetime.now(timezone.utc)
        stats["total"] = len(files)
        if stats["added"]:
            from ..models import User
            from .events import notify
            n = stats["added"]
            for user in (await session.scalars(select(User))).all():
                await notify(session, user, "media", f"{n} new {'video' if n == 1 else 'videos'} in {lib.name}",
                             link=f"/watch/c/{lib.id}")
        await session.commit()
    log.info("scan of %s finished: %s", library_id, stats)
    return stats
