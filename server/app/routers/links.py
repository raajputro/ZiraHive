"""Linking two ZiraHive servers: people here watch what another ZiraHive shares with us.

Everything goes through this server: it asks the other ZiraHive (with the link's token) and passes
the answer on, so people's browsers never need to reach the other server, and the token never
leaves here. Age limits of people here are applied on top of the other server's own limit.
"""
from __future__ import annotations

import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from ..db import get_session
from ..models import FedLink, RemoteProgress, User, utcnow
from ..security import admin_user, current_user
from ..services.events import audit
from ..services.ratings import allowed
from .federation import SCHEME, read_code

router = APIRouter(prefix="/api", tags=["linked servers"])

_PASS_HEADERS = ("content-type", "content-length", "content-range", "accept-ranges", "cache-control",
                 "last-modified", "etag")


def client_for(link: FedLink) -> httpx.AsyncClient:
    """Replaced in tests, to reach the other server in-process."""
    return httpx.AsyncClient(base_url=link.url, timeout=httpx.Timeout(60, connect=10), follow_redirects=False,
                             headers={"Authorization": f"{SCHEME} {link.token}", "User-Agent": "ZiraHive link"})


async def _get_json(link: FedLink, path: str, session: AsyncSession, **params) -> dict | list:
    try:
        async with client_for(link) as c:
            r = await c.get(path, params={k: v for k, v in params.items() if v is not None})
    except httpx.HTTPError as exc:
        link.last_error = f"Can't reach {link.url}: {type(exc).__name__}"
        await session.commit()
        raise HTTPException(502, f"{link.name} can't be reached right now") from None
    if r.status_code == 401:
        link.last_error = "The other ZiraHive removed this link"
        await session.commit()
        raise HTTPException(502, f"{link.name} removed this link")
    if r.status_code == 404:
        raise HTTPException(404, "Not found")
    if r.status_code >= 400:
        raise HTTPException(502, f"{link.name} answered {r.status_code}")
    if link.last_error or not link.last_ok_at or (utcnow() - _aware(link.last_ok_at)).total_seconds() > 300:
        link.last_ok_at, link.last_error = utcnow(), None
        await session.commit()
    return r.json()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


async def _link(session: AsyncSession, link_id: str) -> FedLink:
    link = await session.get(FedLink, link_id)
    if link is None:
        raise HTTPException(404, "No such linked server")
    return link


# what the other server says about a title, briefly remembered: streams ask for many pieces
_ages: dict[tuple[str, str], tuple[float, int | None]] = {}


async def _title_age(link: FedLink, kind: str, rid: str, session: AsyncSession) -> int | None:
    key = (link.id, f"{kind}:{rid}")
    hit = _ages.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    data = await _get_json(link, f"/api/fed/{kind}/{rid}", session)
    _ages[key] = (time.time(), data.get("age"))
    return data.get("age")


async def _may_watch(user: User, link: FedLink, kind: str, rid: str, session: AsyncSession) -> None:
    if user.max_age is not None and not allowed(user.max_age, await _title_age(link, kind, rid, session)):
        raise HTTPException(404, "Not found")


async def _proxy(link: FedLink, path: str, request: Request) -> Response:
    """Streams one response from the other server through to the browser, Range and all."""
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("range", "if-range")}
    client = client_for(link)
    try:
        upstream = await client.send(client.build_request("GET", path, headers=headers), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(502, f"{link.name} can't be reached right now") from None
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(404 if upstream.status_code in (401, 404) else 502, "Not available")

    async def close():
        await upstream.aclose()
        await client.aclose()

    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() in _PASS_HEADERS}
    return StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code, headers=out_headers,
                             background=BackgroundTask(close))


# ------------------------------------------------------------ admin: add and remove links

class LinkIn(BaseModel):
    code: str = Field(min_length=10, max_length=2000)
    name: str | None = Field(default=None, max_length=100)


class LinkLibrary(BaseModel):
    id: str
    name: str
    kind: str


class LinkOut(BaseModel):
    id: str
    name: str
    url: str | None = None  # admins only
    ok: bool
    last_error: str | None = None
    libraries: list[LinkLibrary] = []


@router.post("/admin/links", response_model=LinkOut, status_code=201)
async def add_link(body: LinkIn, request: Request, admin: User = Depends(admin_user),
                   session: AsyncSession = Depends(get_session)):
    try:
        url, token = read_code(body.code)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "That isn't a ZiraHive link code. Copy the whole code, starting with zh1.") from None
    if await session.scalar(select(FedLink.id).where(FedLink.url == url, FedLink.token == token)):
        raise HTTPException(409, "This code is already added")
    link = FedLink(name=(body.name or "").strip() or "Linked ZiraHive", url=url.rstrip("/"), token=token)
    try:
        info = await _get_json(link, "/api/fed/info", session)
    except HTTPException as exc:
        raise HTTPException(400, f"The other ZiraHive didn't accept the code ({exc.detail}). Check that its "
                                 f"address {url} can be reached from this server.") from None
    if not body.name:
        link.name = str(info.get("name") or link.name)[:100]
    link.last_ok_at = utcnow()
    session.add(link)
    await audit(session, "link_added", admin, detail=link.name, request=request)
    await session.commit()
    return LinkOut(id=link.id, name=link.name, url=link.url, ok=True,
                   libraries=[LinkLibrary(**lib) for lib in info.get("libraries", [])])


@router.delete("/admin/links/{link_id}", status_code=204)
async def remove_link(link_id: str, request: Request, admin: User = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    link = await _link(session, link_id)
    await session.delete(link)
    await audit(session, "link_removed", admin, detail=link.name, request=request)
    await session.commit()


# ------------------------------------------------------------ everyone: browse and watch

@router.get("/links", response_model=list[LinkOut])
async def list_links(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    out = []
    for link in (await session.scalars(select(FedLink).order_by(FedLink.created_at))).all():
        try:
            info = await _get_json(link, "/api/fed/info", session)
            libs, ok = [LinkLibrary(**lib) for lib in info.get("libraries", [])], True
        except HTTPException:
            libs, ok = [], False
        out.append(LinkOut(id=link.id, name=link.name, url=link.url if user.is_admin else None, ok=ok,
                           last_error=link.last_error if user.is_admin else None, libraries=libs))
    return out


async def _progress(session: AsyncSession, user: User, link_id: str, ids: list[str]) -> dict[str, RemoteProgress]:
    if not ids:
        return {}
    rows = (await session.scalars(select(RemoteProgress).where(
        RemoteProgress.user_id == user.id, RemoteProgress.link_id == link_id, RemoteProgress.media_id.in_(ids)))).all()
    return {r.media_id: r for r in rows}


def _mine(m: dict, p: RemoteProgress | None, link_id: str) -> dict:
    """A title from the other server, with where this person stopped, and where to fetch it here."""
    m = dict(m)
    m["position"], m["finished"] = (p.position, p.finished) if p else (0, False)
    m["base"] = f"/api/links/{link_id}/media/{m['id']}"
    m["link_id"] = link_id
    return m


@router.get("/links/{link_id}/titles")
async def link_titles(link_id: str, library_id: str, q: str | None = None, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    link = await _link(session, link_id)
    titles = await _get_json(link, "/api/fed/titles", session, library_id=library_id, q=q)
    titles = [t for t in titles if user.max_age is None or allowed(user.max_age, t.get("age"))]
    progress = await _progress(session, user, link.id, [t["id"] for t in titles if t["type"] == "movie"])
    for t in titles:
        if t["type"] == "movie":
            p = progress.get(t["id"])
            t["position"], t["finished"] = (p.position, p.finished) if p else (0, False)
    return titles


@router.get("/links/{link_id}/series/{series_id}")
async def link_series(link_id: str, series_id: str, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    link = await _link(session, link_id)
    s = await _get_json(link, f"/api/fed/series/{series_id}", session)
    if user.max_age is not None and not allowed(user.max_age, s.get("age")):
        raise HTTPException(404, "Series not found")
    ids = [e["id"] for season in s["seasons"] for e in season["episodes"]]
    progress = await _progress(session, user, link.id, ids)
    for season in s["seasons"]:
        season["episodes"] = [_mine(e, progress.get(e["id"]), link.id) for e in season["episodes"]
                              if user.max_age is None or allowed(user.max_age, e.get("age"))]
    if s.get("up_next"):
        s["up_next"] = _mine(s["up_next"], progress.get(s["up_next"]["id"]), link.id)
    # the next unfinished episode, by this person's progress
    flat = [e for season in s["seasons"] for e in season["episodes"]]
    started = [e for e in flat if 0 < e["position"] and not e["finished"]]
    s["up_next"] = started[0] if started else next((e for e in flat if not e["finished"]), flat[0] if flat else None)
    s["link_id"] = link.id
    return s


@router.get("/links/{link_id}/series/{series_id}/poster")
async def link_series_poster(link_id: str, series_id: str, request: Request, user: User = Depends(current_user),
                             session: AsyncSession = Depends(get_session)):
    link = await _link(session, link_id)
    await _may_watch(user, link, "series", series_id, session)
    return await _proxy(link, f"/api/fed/series/{series_id}/poster", request)


@router.get("/links/{link_id}/media/{media_id}")
async def link_media(link_id: str, media_id: str, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    link = await _link(session, link_id)
    m = await _get_json(link, f"/api/fed/media/{media_id}", session)
    if user.max_age is not None and not allowed(user.max_age, m.get("age")):
        raise HTTPException(404, "Not found")
    p = (await _progress(session, user, link.id, [media_id])).get(media_id)
    return _mine(m, p, link.id)


@router.get("/links/{link_id}/media/{media_id}/tracks")
async def link_tracks(link_id: str, media_id: str, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    link = await _link(session, link_id)
    await _may_watch(user, link, "media", media_id, session)
    return await _get_json(link, f"/api/fed/media/{media_id}/tracks", session)


@router.get("/links/{link_id}/media/{media_id}/{rest:path}")
async def link_media_file(link_id: str, media_id: str, rest: str, request: Request,
                          user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Poster, the file itself, converted pieces and subtitles, passed through from the other server."""
    import re

    if not re.fullmatch(r"poster|stream|hls/\w+/\d+/(?:index\.m3u8|seg/\d+\.ts)|subtitles/[\w.-]+\.vtt", rest):
        raise HTTPException(404, "Not found")
    link = await _link(session, link_id)
    await _may_watch(user, link, "media", media_id, session)
    return await _proxy(link, f"/api/fed/media/{media_id}/{rest}", request)


class RemoteProgressIn(BaseModel):
    position: float = Field(ge=0)
    duration: float | None = Field(default=None, ge=0)
    title: str = Field(default="", max_length=512)


@router.put("/links/{link_id}/media/{media_id}/progress", status_code=204)
async def link_progress(link_id: str, media_id: str, body: RemoteProgressIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    link = await _link(session, link_id)
    row = await session.scalar(select(RemoteProgress).where(
        RemoteProgress.user_id == user.id, RemoteProgress.link_id == link.id, RemoteProgress.media_id == media_id))
    if row is None:
        row = RemoteProgress(user_id=user.id, link_id=link.id, media_id=media_id)
        session.add(row)
    row.position, row.duration = body.position, body.duration
    row.title = body.title or row.title
    row.finished = bool(body.duration and body.position >= body.duration * 0.92)
    await session.commit()
