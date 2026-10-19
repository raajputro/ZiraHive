"""Finds songs that are in the music folders more than once, keeps the best copy and takes the
others out of Listen.

Duplicates mostly arrive by themselves: a download saved twice ("Song (1).mp3", "Song - Copy.mp3"),
the same album synced into two folders, a phone backup copying songs again. The check runs after
every music scan (so also every night) and can be run by hand from Settings.

Two songs count as the same when
  * the files are identical (same size and SHA-256), or
  * they are the same recording: same title and artist (ignoring junk like "(1)", "- Copy",
    "[320kbps]", "(Official Audio)") and within 2 seconds of each other in length. A "Live",
    "Remix" or "Acoustic" version keeps those words, so it never matches the studio version.
    Untagged files must also be in the same folder.

The best copy stays: lossless over lossy, higher bitrate, tagged and with cover art, a clean name,
then the oldest. Plays, favourites and playlist entries of the others move to it.

Nothing is deleted. A duplicate's file is moved into ".zirahive-duplicates" inside its category
folder when ZiraHive may write there; when it can't (the media folder is read-only in Docker), the
song is only hidden. Either way it can be put back from Settings.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Library, MusicAlbum, PlaylistTrack, Track, TrackStat

log = logging.getLogger(__name__)

DUP_FOLDER = ".zirahive-duplicates"
LOSSLESS = {"flac", "alac", "wav", "pcm_s16le", "pcm_s24le", "ape", "wavpack", "aiff"}

# what's added to a name when a file is saved or copied again: "Song (1)", "Song - Copy", "Song copy 2"
_COPY_MARK = re.compile(r"\s*(?:[\(\[]\s*\d{1,2}\s*[\)\]]|[-_ ]+copy(?:\s*\(\d+\))?|\s+copy\s*\d*)\s*$", re.I)
_NOISE = re.compile(
    r"[\(\[]\s*(?:official\s*(?:music\s*)?(?:video|audio|lyrics?\s*video)?|lyrics?|audio|hq|hd|\d{2,4}\s*kbps|"
    r"mp3|full\s*song|video\s*song|visualizer)\s*[\)\]]", re.I)
_LEADING_NO = re.compile(r"^\s*\d{1,3}\s*[-._)]\s*")


def norm(text: str | None) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).lower()
    s = _NOISE.sub(" ", s)
    for _ in range(2):
        s = _COPY_MARK.sub("", s)
    s = _LEADING_NO.sub("", s)
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def copy_named(rel: str) -> bool:
    """'Song (1).mp3', 'Song - Copy.mp3': names that say the file is an extra copy."""
    return bool(_COPY_MARK.search(PurePosixPath(rel).stem))


@dataclass
class Found:
    keep: Track
    dups: list[Track]
    reason: str  # "same file" | "same song"


def _quality(t: Track, covers: dict[str, bool]) -> tuple:
    lossless = (t.codec or "").lower() in LOSSLESS
    kbps = (t.size * 8 / 1000 / t.duration) if t.duration else 0
    tagged = bool(t.artist) + bool(t.album_title)
    cover = bool(t.album_id and covers.get(t.album_id))
    added = t.added_at.timestamp() if t.added_at else 0
    # higher is better, except: copy-named last, then oldest first
    return (lossless, round(kbps / 16), tagged, cover, not copy_named(t.rel_path), -added, -len(t.rel_path))


def _sha256(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(tracks: list[Track], roots: dict[str, Path], covers: dict[str, bool]) -> list[Found]:
    """Groups of the same song among `tracks` (all on disk, none already handled)."""
    parent = {t.id: t.id for t in tracks}
    why: dict[str, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a: Track, b: Track, reason: str):
        ra, rb = find(a.id), find(b.id)
        if ra != rb:
            parent[rb] = ra
            why.setdefault(ra, reason)
            if why.get(rb) == "same song":
                why[ra] = "same song"

    # 1. identical files (only files that share a size are read)
    by_size: dict[int, list[Track]] = defaultdict(list)
    for t in tracks:
        if t.size > 0:
            by_size[t.size].append(t)
    for group in by_size.values():
        if len(group) < 2:
            continue
        by_hash: dict[str, Track] = {}
        for t in group:
            h = _sha256(roots[t.library_id] / t.rel_path)
            if h is None:
                continue
            if h in by_hash:
                join(by_hash[h], t, "same file")
            else:
                by_hash[h] = t

    # 2. the same recording
    by_name: dict[tuple, list[Track]] = defaultdict(list)
    for t in tracks:
        title = norm(t.title) or norm(PurePosixPath(t.rel_path).stem)
        if not title or not t.duration:
            continue
        artist = norm(t.artist)
        place = "" if artist else str(PurePosixPath(t.rel_path).parent)  # untagged: same folder only
        by_name[(title, artist, place, t.library_id if not artist else "")].append(t)
    for group in by_name.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda t: t.duration or 0)
        for a, b in zip(group, group[1:]):
            if abs((a.duration or 0) - (b.duration or 0)) <= 2.0:
                join(a, b, "same song")

    sets: dict[str, list[Track]] = defaultdict(list)
    for t in tracks:
        sets[find(t.id)].append(t)
    out = []
    for root_id, members in sets.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda t: _quality(t, covers), reverse=True)
        out.append(Found(keep=members[0], dups=members[1:], reason=why.get(root_id, "same song")))
    return out


def _move_aside(root: Path, rel: str) -> bool:
    """Moves the file into .zirahive-duplicates in the category folder. False when not allowed."""
    src = root / rel
    dest = root / DUP_FOLDER / rel
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem} ({os.getpid()}){dest.suffix}")
        shutil.move(str(src), str(dest))
        return True
    except OSError as exc:
        log.info("can't move duplicate %s aside (%s); hiding it only", src, exc)
        return False


def _move_back(root: Path, rel: str) -> bool:
    src = root / DUP_FOLDER / rel
    if not src.exists():
        return (root / rel).exists()
    try:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(root / rel))
        return True
    except OSError:
        return False


async def _merge_listening(session: AsyncSession, keep: Track, dup: Track) -> None:
    """Plays, favourites and playlist places of `dup` go to `keep`."""
    await session.execute(update(PlaylistTrack).where(PlaylistTrack.track_id == dup.id).values(track_id=keep.id))
    stats = (await session.scalars(select(TrackStat).where(TrackStat.track_id == dup.id))).all()
    for s in stats:
        mine = (await session.scalars(select(TrackStat).where(TrackStat.track_id == keep.id,
                                                              TrackStat.user_id == s.user_id))).first()
        if mine is None:
            s.track_id = keep.id
            continue
        mine.plays += s.plays
        mine.favorite = mine.favorite or s.favorite
        if s.last_played and (mine.last_played is None or s.last_played > mine.last_played):
            mine.last_played = s.last_played
        await session.delete(s)
    await session.flush()


async def run(session: AsyncSession, move_files: bool = True) -> dict:
    """One check over every music category. Returns {groups, hidden, moved}."""
    libs = {lib.id: lib for lib in (await session.scalars(select(Library).where(Library.kind == "music"))).all()}
    if not libs:
        return {"groups": 0, "hidden": 0, "moved": 0}
    roots = {i: Path(lib.path) for i, lib in libs.items()}
    tracks = list((await session.scalars(select(Track).where(
        Track.library_id.in_(list(libs)), Track.missing.is_(False), Track.duplicate_of.is_(None),
        Track.dup_kept.is_(False)))).all())
    album_ids = {t.album_id for t in tracks if t.album_id}
    covers = dict((await session.execute(select(MusicAlbum.id, MusicAlbum.cover_ready)
                                         .where(MusicAlbum.id.in_(album_ids)))).all()) if album_ids else {}
    found = await asyncio.to_thread(find_duplicates, tracks, roots, covers)
    hidden = moved = 0
    for g in found:
        for d in g.dups:
            d.duplicate_of = g.keep.id
            await _merge_listening(session, g.keep, d)
            if move_files and await asyncio.to_thread(_move_aside, roots[d.library_id], d.rel_path):
                d.dup_moved = True
                moved += 1
            hidden += 1
    await session.commit()
    if hidden:
        log.info("duplicate songs: %d hidden (%d files moved aside) in %d groups", hidden, moved, len(found))
    return {"groups": len(found), "hidden": hidden, "moved": moved}


async def keep_both(session: AsyncSession, track: Track) -> bool:
    """Undo: the copy is a song of its own again (and stays so in later checks)."""
    lib = await session.get(Library, track.library_id)
    if lib is None:
        return False
    if track.dup_moved:
        if not await asyncio.to_thread(_move_back, Path(lib.path), track.rel_path):
            return False
        track.dup_moved = False
        track.missing = False
    track.duplicate_of = None
    track.dup_kept = True
    await session.commit()
    return True


async def forget_missing(session: AsyncSession) -> None:
    """Rows of duplicates whose file is gone from the duplicates folder too (someone deleted it)."""
    rows = (await session.scalars(select(Track).where(Track.duplicate_of.is_not(None), Track.dup_moved.is_(True)))).all()
    gone = []
    for t in rows:
        lib = await session.get(Library, t.library_id)
        if lib and not (Path(lib.path) / DUP_FOLDER / t.rel_path).exists() and not (Path(lib.path) / t.rel_path).exists():
            gone.append(t.id)
    if gone:
        await session.execute(delete(Track).where(Track.id.in_(gone)))
        await session.commit()
