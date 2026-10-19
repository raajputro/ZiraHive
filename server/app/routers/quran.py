"""Quran recitations (categories of type "quran") and the namaz times, timer and tracker.

Recitations: a folder per qari, holding a file per surah (001.mp3, "002 Al-Baqarah.mp3",
"Surah Yasin.mp3"…) or a file per ayah (002255.mp3). Files are ordinary Track rows, so they play,
convert and count plays exactly like songs.

Namaz: the times are worked out in the browser (and the Android app) from the place saved here;
the server keeps the place and the tracker so every device of the person shows the same.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Library, MusicAlbum, PrayerLog, PrayerSettings, Track, TrackStat, User, track_shown, utcnow
from ..schemas import TrackOut
from ..security import admin_user, current_user
from ..services.quran_data import SURAHS, parse_file
from ..services.shelf_files import AUDIO_EXT, clean_name
from .music import track_outs, visible_libraries

router = APIRouter(prefix="/api", tags=["quran"])


# ------------------------------------------------------------------ recitations

def _reciter(t: Track, lib_name: str) -> str:
    parts = PurePosixPath(t.rel_path).parts
    if len(parts) > 1:
        return clean_name(parts[0])
    return t.artist or lib_name


async def _quran_tracks(session: AsyncSession, user: User) -> list[tuple[Track, str]]:
    libs = await visible_libraries(session, user, {"quran"})
    if not libs:
        return []
    rows = (await session.scalars(select(Track).where(Track.library_id.in_(list(libs)), track_shown())
                                  .order_by(Track.rel_path))).all()
    return [(t, _reciter(t, libs[t.library_id].name)) for t in rows]


class ReciterOut(BaseModel):
    name: str
    surahs: int            # how many of the 114 this qari has
    files: int
    duration: float
    cover_album_id: str | None = None


class SurahFilesOut(BaseModel):
    number: int
    tracks: list[TrackOut]   # one file, or the ayah files in order
    duration: float


class ReciterDetailOut(BaseModel):
    name: str
    cover_album_id: str | None
    surahs: list[SurahFilesOut]
    other: list[TrackOut]    # duas, intros and anything that isn't one surah


class QuranHomeOut(BaseModel):
    reciters: list[ReciterOut]
    recent: list[TrackOut]
    has_category: bool


def _cover(tracks: list[Track], covers: dict[str, bool]) -> str | None:
    for t in tracks:
        if t.album_id and covers.get(t.album_id):
            return t.album_id
    return None


async def _covers(session: AsyncSession, tracks: list[Track]) -> dict[str, bool]:
    ids = {t.album_id for t in tracks if t.album_id}
    if not ids:
        return {}
    return dict((await session.execute(select(MusicAlbum.id, MusicAlbum.cover_ready).where(MusicAlbum.id.in_(ids)))).all())


@router.get("/quran/surahs")
async def surahs(_: User = Depends(current_user)) -> list[dict]:
    return SURAHS


@router.get("/quran", response_model=QuranHomeOut)
async def quran_home(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await _quran_tracks(session, user)
    groups: dict[str, list[Track]] = {}
    for t, name in rows:
        groups.setdefault(name, []).append(t)
    covers = await _covers(session, [t for t, _ in rows])
    reciters = []
    for name, tracks in groups.items():
        found = {parse_file(PurePosixPath(t.rel_path).stem, t.track_no)[0] for t in tracks} - {None}
        reciters.append(ReciterOut(name=name, surahs=len(found), files=len(tracks),
                                   duration=sum(t.duration or 0 for t in tracks), cover_album_id=_cover(tracks, covers)))
    reciters.sort(key=lambda r: r.name.lower())
    ids = [t.id for t, _ in rows]
    recent: list[Track] = []
    if ids:
        recent = list((await session.scalars(
            select(Track).join(TrackStat, TrackStat.track_id == Track.id)
            .where(TrackStat.user_id == user.id, TrackStat.last_played.is_not(None), Track.id.in_(ids))
            .order_by(TrackStat.last_played.desc()).limit(12))).all())
    has = bool(await visible_libraries(session, user, {"quran"}))
    return QuranHomeOut(reciters=reciters, recent=await track_outs(session, user, recent), has_category=has)


@router.get("/quran/reciter", response_model=ReciterDetailOut)
async def reciter(name: str = Query(..., max_length=512), user: User = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    tracks = [t for t, n in await _quran_tracks(session, user) if n == name]
    if not tracks:
        raise HTTPException(404, "Reciter not found")
    by_surah: dict[int, list[tuple[int, Track]]] = {}
    other: list[Track] = []
    for t in tracks:
        n, ayah = parse_file(PurePosixPath(t.rel_path).stem, t.track_no)
        if n is None:
            other.append(t)
        else:
            by_surah.setdefault(n, []).append((ayah or 0, t))
    outs = {o.id: o for o in await track_outs(session, user, tracks)}
    surahs = []
    for n in sorted(by_surah):
        files = [t for _, t in sorted(by_surah[n], key=lambda x: (x[0], x[1].rel_path))]
        surahs.append(SurahFilesOut(number=n, tracks=[outs[t.id] for t in files],
                                    duration=sum(t.duration or 0 for t in files)))
    covers = await _covers(session, tracks)
    return ReciterDetailOut(name=name, cover_album_id=_cover(tracks, covers), surahs=surahs,
                            other=[outs[t.id] for t in other])


class SurahReciterOut(BaseModel):
    reciter: str
    tracks: list[TrackOut]
    duration: float


@router.get("/quran/surah/{number}", response_model=list[SurahReciterOut])
async def surah_reciters(number: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Every qari's recitation of one surah, to compare or pick from."""
    if not 1 <= number <= 114:
        raise HTTPException(404, "There are 114 surahs")
    found: dict[str, list[tuple[int, Track]]] = {}
    for t, name in await _quran_tracks(session, user):
        n, ayah = parse_file(PurePosixPath(t.rel_path).stem, t.track_no)
        if n == number:
            found.setdefault(name, []).append((ayah or 0, t))
    flat = [t for files in found.values() for _, t in files]
    outs = {o.id: o for o in await track_outs(session, user, flat)}
    result = []
    for name in sorted(found, key=str.lower):
        files = [t for _, t in sorted(found[name], key=lambda x: (x[0], x[1].rel_path))]
        result.append(SurahReciterOut(reciter=name, tracks=[outs[t.id] for t in files],
                                      duration=sum(t.duration or 0 for t in files)))
    return result


# ------------------------------------------------------------- adding recitations
# The media folder is read-only to ZiraHive, so recitations added from the web page go to
# <data>/quran/<qari>/, which is its own "Quran" category.

MAX_FILE = 1024 * 1024 * 1024
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_part(s: str, what: str) -> str:
    s = " ".join(p for p in re.split(r"[\\/]+", s) if p.strip(" .")).strip()  # no "..", no folders
    s = _UNSAFE.sub(" ", s).strip().strip(".")
    s = re.sub(r"\s+", " ", s)[:120]
    if not s:
        raise HTTPException(400, f"The {what} is empty")
    return s


def uploads_root() -> Path:
    return get_settings().data_dir / "quran"


async def uploads_library(session: AsyncSession) -> Library:
    root = uploads_root()
    root.mkdir(parents=True, exist_ok=True)
    lib = (await session.scalars(select(Library).where(Library.path == str(root)))).first()
    if lib is None:
        lib = Library(name="Quran", path=str(root), kind="quran", sort_order=0)
        session.add(lib)
        await session.commit()
    return lib


class UploadedOut(BaseModel):
    reciter: str
    name: str
    size: int


@router.put("/quran/files", response_model=UploadedOut)
async def add_recitation(request: Request, reciter: str = Query(..., max_length=200),
                         name: str = Query(..., max_length=255), _: User = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    """One audio file as the request body, into the qari's folder. A file with the same name is replaced."""
    folder_name, file_name = _safe_part(reciter, "qari's name"), _safe_part(name, "file name")
    if Path(file_name).suffix.lower() not in AUDIO_EXT:
        raise HTTPException(400, "That isn't an audio file (mp3, m4a, ogg, opus, flac, wav…)")
    lib = await uploads_library(session)
    folder = uploads_root() / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".part-{os.getpid()}-{id(request)}"
    size = 0
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_FILE:
                    raise HTTPException(413, "That file is too big")
                f.write(chunk)
        if size == 0:
            raise HTTPException(400, "The file is empty")
        os.replace(tmp, folder / file_name)
    finally:
        tmp.unlink(missing_ok=True)
    return UploadedOut(reciter=folder_name, name=file_name, size=size)


@router.post("/quran/rescan")
async def rescan(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """After adding files: look through every Quran category again."""
    from ..services import jobs
    libs = (await session.scalars(select(Library).where(Library.kind == "quran"))).all()
    if not any(l.path == str(uploads_root()) for l in libs) and uploads_root().is_dir():
        libs = [*libs, await uploads_library(session)]
    for lib in libs:
        await jobs.enqueue("scan_library", lib.id)
    return {"scanning": len(libs)}


# ------------------------------------------------------------------------ namaz

PRAYERS = ("fajr", "dhuhr", "asr", "maghrib", "isha", "witr")
METHODS = ("karachi", "mwl", "isna", "makkah", "egypt", "dubai", "singapore", "turkey", "tehran", "jafari")


class Offsets(BaseModel):
    fajr: int = Field(0, ge=-60, le=60)
    sunrise: int = Field(0, ge=-60, le=60)
    dhuhr: int = Field(0, ge=-60, le=60)
    asr: int = Field(0, ge=-60, le=60)
    maghrib: int = Field(0, ge=-60, le=60)
    isha: int = Field(0, ge=-60, le=60)


class Reminders(BaseModel):
    """Phone notifications from the Android app: which prayers, and how many minutes before."""
    fajr: bool = True
    dhuhr: bool = True
    asr: bool = True
    maghrib: bool = True
    isha: bool = True
    before: int = Field(0, ge=0, le=60)
    jamaah_note: bool = False


class PrayerSettingsIn(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    place: str = Field("", max_length=120)
    timezone: str | None = Field(None, max_length=64)   # IANA name of the place, for times shown elsewhere
    method: str = "karachi"
    asr: str = Field("hanafi", pattern=r"^(hanafi|standard)$")
    high_lat: str = Field("angle", pattern=r"^(angle|midnight|seventh|none)$")
    offsets: Offsets = Offsets()
    reminders: Reminders = Reminders()


DEFAULTS = PrayerSettingsIn()


@router.get("/namaz/settings", response_model=PrayerSettingsIn)
async def get_prayer_settings(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    row = await session.get(PrayerSettings, user.id)
    if row is None:
        return DEFAULTS
    try:
        return PrayerSettingsIn.model_validate(json.loads(row.settings))
    except ValueError:
        return DEFAULTS


@router.put("/namaz/settings", response_model=PrayerSettingsIn)
async def put_prayer_settings(body: PrayerSettingsIn, user: User = Depends(current_user),
                              session: AsyncSession = Depends(get_session)):
    if body.method not in METHODS:
        raise HTTPException(400, "Unknown calculation method")
    if (body.lat is None) != (body.lng is None):
        raise HTTPException(400, "Give both latitude and longitude")
    row = await session.get(PrayerSettings, user.id)
    if row is None:
        row = PrayerSettings(user_id=user.id)
        session.add(row)
    row.settings = body.model_dump_json()
    row.updated_at = utcnow()
    await session.commit()
    return body


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day(s: str) -> str:
    if not _DAY.match(s):
        raise HTTPException(400, "Dates look like 2026-10-19")
    try:
        date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, "Not a real date") from None
    return s


class PrayerLogOut(BaseModel):
    day: str
    prayer: str
    status: str
    jamaah: bool = False


class PrayerLogIn(BaseModel):
    day: str
    prayer: str
    status: str | None = Field(None, pattern=r"^(ontime|late|missed)$")   # None clears it
    jamaah: bool = False


@router.get("/namaz/log", response_model=list[PrayerLogOut])
async def prayer_log(start: str, end: str, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    a, b = _day(start), _day(end)
    if (date.fromisoformat(b) - date.fromisoformat(a)).days > 400:
        raise HTTPException(400, "Ask for at most a year at a time")
    rows = (await session.scalars(select(PrayerLog).where(PrayerLog.user_id == user.id, PrayerLog.day >= a,
                                                          PrayerLog.day <= b).order_by(PrayerLog.day))).all()
    return [PrayerLogOut(day=r.day, prayer=r.prayer, status=r.status, jamaah=r.jamaah) for r in rows]


@router.put("/namaz/log", response_model=PrayerLogOut | None)
async def set_prayer(body: PrayerLogIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    day = _day(body.day)
    if body.prayer not in PRAYERS:
        raise HTTPException(400, "Unknown prayer")
    row = (await session.scalars(select(PrayerLog).where(PrayerLog.user_id == user.id, PrayerLog.day == day,
                                                         PrayerLog.prayer == body.prayer))).first()
    if body.status is None:
        if row is not None:
            await session.delete(row)
            await session.commit()
        return None
    if row is None:
        row = PrayerLog(user_id=user.id, day=day, prayer=body.prayer, status=body.status)
        session.add(row)
    row.status, row.jamaah, row.updated_at = body.status, body.jamaah and body.status != "missed", utcnow()
    await session.commit()
    return PrayerLogOut(day=row.day, prayer=row.prayer, status=row.status, jamaah=row.jamaah)
