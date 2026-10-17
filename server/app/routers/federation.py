"""Linking two ZiraHive servers: this side shares categories with another ZiraHive.

The admin makes an invite code for, say, "Rahim's house", choosing which video categories to share
and an age limit. Rahim's ZiraHive stores the code and from then on asks this server for those
categories only, with the code's token (Authorization: ZiraHive-Link <token>). People on Rahim's
side never talk to this server directly: their ZiraHive fetches for them.

The /api/fed/* endpoints reuse the normal media endpoints with a stand-in account that has the
guest's age limit, after checking the title is in a shared category.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import FedGuest, Library, MediaItem, Series, User, utcnow
from ..security import admin_user, client_ip, share_throttle
from ..services.events import audit
from ..services.shelf_scan import SHELF_KINDS
from . import media as media_routes
from . import playback

router = APIRouter(prefix="/api", tags=["linked servers"])

SCHEME = "ZiraHive-Link"
CODE_PREFIX = "zh1."


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make_code(url: str, token: str) -> str:
    raw = json.dumps({"u": url.rstrip("/"), "t": token}, separators=(",", ":")).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def read_code(code: str) -> tuple[str, str]:
    code = code.strip()
    if not code.startswith(CODE_PREFIX):
        raise ValueError("not a ZiraHive link code")
    body = code[len(CODE_PREFIX):]
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    url, token = str(data["u"]), str(data["t"])
    if not url.startswith(("http://", "https://")) or len(token) < 20:
        raise ValueError("damaged code")
    return url, token


def server_name() -> str:
    return get_settings().server_name or "ZiraHive"


# ------------------------------------------------------------ the guest's requests

class Guest:
    def __init__(self, row: FedGuest):
        self.row = row
        self.library_ids: set[str] = set(json.loads(row.library_ids or "[]"))
        # stands in for a person: the normal media endpoints check its age limit
        self.user = User(id=f"link-{row.id}", username=f"{row.name} (linked)", is_admin=False,
                         max_age=row.max_age, password_hash="", token_version=0)


async def fed_guest(request: Request, session: AsyncSession = Depends(get_session)) -> Guest:
    ip = client_ip(request)
    auth = request.headers.get("authorization", "")
    if not auth.startswith(SCHEME + " "):
        raise HTTPException(401, "This is for linked ZiraHive servers")
    row = await session.scalar(select(FedGuest).where(FedGuest.token_hash == token_hash(auth[len(SCHEME) + 1:].strip())))
    if row is None or row.revoked_at:
        # Only wrong tokens are slowed down: a server with one removed link must still be able to
        # use its other links (guessing a 256-bit token is hopeless anyway).
        share_throttle.check(f"fed:{ip}")
        share_throttle.fail(f"fed:{ip}")
        raise HTTPException(401, "This link was removed on the other ZiraHive")
    now = utcnow()
    seen = row.last_seen_at
    if seen is None or (now - (seen if seen.tzinfo else seen.replace(tzinfo=now.tzinfo))) > timedelta(minutes=5):
        row.last_seen_at = now
        await session.commit()
    return Guest(row)


async def _check_media(session: AsyncSession, g: Guest, media_id: str) -> MediaItem:
    item = await session.get(MediaItem, media_id)
    if item is None or item.library_id not in g.library_ids or item.missing:
        raise HTTPException(404, "Not found")
    return item


async def _check_series(session: AsyncSession, g: Guest, series_id: str) -> Series:
    s = await session.get(Series, series_id)
    if s is None or s.library_id not in g.library_ids:
        raise HTTPException(404, "Not found")
    return s


class FedLibrary(BaseModel):
    id: str
    name: str
    kind: str


class FedInfo(BaseModel):
    name: str
    libraries: list[FedLibrary]


@router.get("/fed/info", response_model=FedInfo)
async def fed_info(g: Guest = Depends(fed_guest), session: AsyncSession = Depends(get_session)):
    libs = (await session.scalars(select(Library).where(Library.id.in_(g.library_ids))
                                  .order_by(Library.sort_order, Library.name))).all()
    return FedInfo(name=server_name(), libraries=[FedLibrary(id=lib.id, name=lib.name, kind=lib.kind)
                                                  for lib in libs if lib.kind not in SHELF_KINDS])


@router.get("/fed/titles")
async def fed_titles(library_id: str, q: str | None = None, g: Guest = Depends(fed_guest),
                     session: AsyncSession = Depends(get_session)):
    if library_id not in g.library_ids:
        raise HTTPException(404, "Not found")
    return await media_routes.list_titles(library_id=library_id, q=q, sort="title", limit=5000, user=g.user,
                                          session=session)


@router.get("/fed/series/{series_id}")
async def fed_series(series_id: str, g: Guest = Depends(fed_guest), session: AsyncSession = Depends(get_session)):
    await _check_series(session, g, series_id)
    return await media_routes.get_series(series_id, user=g.user, session=session)


@router.get("/fed/series/{series_id}/poster")
async def fed_series_poster(series_id: str, g: Guest = Depends(fed_guest),
                            session: AsyncSession = Depends(get_session)):
    await _check_series(session, g, series_id)
    return await media_routes.series_poster(series_id, user=g.user, session=session)


@router.get("/fed/media/{media_id}")
async def fed_media(media_id: str, g: Guest = Depends(fed_guest), session: AsyncSession = Depends(get_session)):
    await _check_media(session, g, media_id)
    return await media_routes.get_media(media_id, user=g.user, session=session)


@router.get("/fed/media/{media_id}/poster")
async def fed_poster(media_id: str, g: Guest = Depends(fed_guest), session: AsyncSession = Depends(get_session)):
    await _check_media(session, g, media_id)
    return await media_routes.media_poster(media_id, user=g.user, session=session)


@router.get("/fed/media/{media_id}/tracks")
async def fed_tracks(media_id: str, g: Guest = Depends(fed_guest), session: AsyncSession = Depends(get_session)):
    await _check_media(session, g, media_id)
    return await playback.media_tracks(media_id, user=g.user, session=session)


@router.api_route("/fed/media/{media_id}/stream", methods=["GET", "HEAD"])
async def fed_stream(media_id: str, request: Request, g: Guest = Depends(fed_guest),
                     session: AsyncSession = Depends(get_session)):
    await _check_media(session, g, media_id)
    return await media_routes.stream_media(media_id, request, user=g.user, session=session)


@router.get("/fed/media/{media_id}/hls/{quality}/{audio}/index.m3u8")
async def fed_hls(media_id: str, quality: str, audio: int, request: Request, g: Guest = Depends(fed_guest),
                  session: AsyncSession = Depends(get_session)):
    await _check_media(session, g, media_id)
    return await playback.hls_playlist(media_id, quality, audio, request, user=g.user, session=session)


@router.get("/fed/media/{media_id}/hls/{quality}/{audio}/seg/{n}.ts")
async def fed_segment(media_id: str, quality: str, audio: int, n: int, request: Request,
                      g: Guest = Depends(fed_guest), session: AsyncSession = Depends(get_session)):
    await _check_media(session, g, media_id)
    return await playback.hls_segment(media_id, quality, audio, n, request, user=g.user, session=session)


@router.get("/fed/media/{media_id}/subtitles/{sub_id}.vtt")
async def fed_subtitle(media_id: str, sub_id: str, request: Request, g: Guest = Depends(fed_guest),
                       session: AsyncSession = Depends(get_session)):
    await _check_media(session, g, media_id)
    return await playback.subtitle(media_id, sub_id, request, user=g.user, session=session)


# ------------------------------------------------------------ the admin's side

class GuestIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    library_ids: list[str] = Field(min_length=1)
    max_age: int | None = Field(default=None, ge=0, le=18)
    url: str = Field(min_length=8, max_length=512)  # this server's address, as the other one reaches it


class GuestOut(BaseModel):
    id: str
    name: str
    library_ids: list[str]
    max_age: int | None
    created_at: datetime
    last_seen_at: datetime | None
    code: str | None = None  # only right after making it


def _guest_out(row: FedGuest, code: str | None = None) -> GuestOut:
    return GuestOut(id=row.id, name=row.name, library_ids=json.loads(row.library_ids or "[]"), max_age=row.max_age,
                    created_at=row.created_at, last_seen_at=row.last_seen_at, code=code)


@router.get("/admin/link-guests", response_model=list[GuestOut])
async def list_guests(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(FedGuest).where(FedGuest.revoked_at.is_(None))
                                  .order_by(FedGuest.created_at))).all()
    return [_guest_out(r) for r in rows]


@router.post("/admin/link-guests", response_model=GuestOut, status_code=201)
async def create_guest(body: GuestIn, request: Request, admin: User = Depends(admin_user),
                       session: AsyncSession = Depends(get_session)):
    libs = (await session.scalars(select(Library).where(Library.id.in_(body.library_ids)))).all()
    if len(libs) != len(set(body.library_ids)) or any(lib.kind in SHELF_KINDS for lib in libs):
        raise HTTPException(400, "Choose video categories to share")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "The address must start with http:// or https://")
    token = secrets.token_urlsafe(32)
    row = FedGuest(name=body.name.strip(), token_hash=token_hash(token), library_ids=json.dumps(body.library_ids),
                   max_age=body.max_age, created_by=admin.username)
    session.add(row)
    await audit(session, "link_invite_created", admin, detail=f"{row.name}: {', '.join(lib.name for lib in libs)}",
                request=request)
    await session.commit()
    return _guest_out(row, make_code(body.url, token))


@router.delete("/admin/link-guests/{guest_id}", status_code=204)
async def revoke_guest(guest_id: str, request: Request, admin: User = Depends(admin_user),
                       session: AsyncSession = Depends(get_session)):
    row = await session.get(FedGuest, guest_id)
    if row is None or row.revoked_at:
        raise HTTPException(404, "Not found")
    row.revoked_at = utcnow()
    await audit(session, "link_invite_removed", admin, detail=row.name, request=request)
    await session.commit()
