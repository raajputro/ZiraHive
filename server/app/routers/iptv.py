"""IPTV (Xtream Codes): Live TV with a programme guide, movies and series from a subscription.

The browser only talks to ZiraHive; ZiraHive talks to the provider (see services/iptv.py).
Kids' profiles (an age limit set) don't get IPTV: providers' channels carry no age ratings.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import IptvFavorite, IptvSource, User
from ..security import current_user
from ..services import iptv, transcode
from ..services.iptv_live import LiveBusy, LiveError, manager as live

router = APIRouter(prefix="/api/iptv", tags=["iptv"])

DIRECT_EXT = {"mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm"}
_VIEWER = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
HLS_TYPE = "application/vnd.apple.mpegurl"
NO_STORE = {"Cache-Control": "no-store"}


async def iptv_user(user: User = Depends(current_user)) -> User:
    if user.max_age is not None:
        raise HTTPException(403, "Live TV isn't available on kids' profiles.")
    return user


def _fail(e: iptv.XtreamError) -> HTTPException:
    return HTTPException(502, str(e))


async def _source(session: AsyncSession, source_id: str, user: User, manage: bool = False) -> IptvSource:
    src = await session.get(IptvSource, source_id)
    if src is None or not (src.owner_id == user.id or src.shared or user.is_admin):
        raise HTTPException(404, "IPTV source not found")
    if manage and not (src.owner_id == user.id or user.is_admin):
        raise HTTPException(403, "Only the person who added this IPTV source can change it.")
    return src


def _out(src: IptvSource, user: User) -> dict:
    mine = src.owner_id == user.id
    return {"id": src.id, "name": src.name, "shared": src.shared, "mine": mine,
            "can_manage": mine or user.is_admin,
            # the server address helps the owner recognise it; the login never leaves the server
            "server": src.server if (mine or user.is_admin) else None,
            "username": src.username if (mine or user.is_admin) else None}


def _viewer(user: User, v: str | None) -> str:
    return f"{user.id}:{v}" if v and _VIEWER.match(v) else user.id


# ------------------------------------------------------------------ sources

class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    server: str = Field(min_length=1, max_length=500)
    port: str | None = Field(default=None, max_length=6)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1000)
    shared: bool = False


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    server: str | None = Field(default=None, min_length=1, max_length=500)
    port: str | None = Field(default=None, max_length=6)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=1000)  # empty = keep
    shared: bool | None = None


@router.get("/sources")
async def list_sources(user: User = Depends(iptv_user), session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.scalars(select(IptvSource).where(
        or_(IptvSource.owner_id == user.id, IptvSource.shared.is_(True))).order_by(IptvSource.created_at))).all()
    return [_out(s, user) for s in rows]


@router.post("/sources", status_code=201)
async def add_source(body: SourceIn, user: User = Depends(iptv_user),
                     session: AsyncSession = Depends(get_session)) -> dict:
    try:
        server = iptv.normalize_server(body.server, body.port)
        info = await iptv.account(iptv.Creds("new", server, body.username.strip(), body.password))
    except iptv.XtreamError as e:
        raise HTTPException(400, str(e))
    src = IptvSource(owner_id=user.id, name=body.name.strip(), server=server, username=body.username.strip(),
                     password=body.password, shared=body.shared and user.is_admin)
    session.add(src)
    await session.commit()
    return {**_out(src, user), "account": info}


@router.patch("/sources/{source_id}")
async def update_source(source_id: str, body: SourcePatch, user: User = Depends(iptv_user),
                        session: AsyncSession = Depends(get_session)) -> dict:
    src = await _source(session, source_id, user, manage=True)
    login_changed = any(v is not None for v in (body.server, body.port, body.username, body.password))
    server = src.server
    if body.server is not None or body.port is not None:
        try:
            server = iptv.normalize_server(body.server if body.server is not None else src.server, body.port)
        except iptv.XtreamError as e:
            raise HTTPException(400, str(e))
    username = body.username.strip() if body.username is not None else src.username
    password = body.password if body.password else src.password
    info = None
    if login_changed:
        try:
            info = await iptv.account(iptv.Creds(src.id, server, username, password))
        except iptv.XtreamError as e:
            raise HTTPException(400, str(e))
        iptv.forget(src.id)
    src.server, src.username, src.password = server, username, password
    if body.name is not None:
        src.name = body.name.strip()
    if body.shared is not None and user.is_admin:
        src.shared = body.shared
    await session.commit()
    return {**_out(src, user), "account": info}


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: str, user: User = Depends(iptv_user),
                        session: AsyncSession = Depends(get_session)) -> None:
    src = await _source(session, source_id, user, manage=True)
    iptv.forget(src.id)
    await session.delete(src)
    await session.commit()


@router.get("/sources/{source_id}/account")
async def source_account(source_id: str, user: User = Depends(iptv_user),
                         session: AsyncSession = Depends(get_session)) -> dict:
    src = await _source(session, source_id, user, manage=True)
    try:
        return await iptv.account(iptv.creds_of(src))
    except iptv.XtreamError as e:
        raise _fail(e)


# ------------------------------------------------------------------ browsing

def _kind(kind: str) -> str:
    if kind not in iptv.KINDS:
        raise HTTPException(400, "kind must be live, vod or series")
    return kind


@router.get("/sources/{source_id}/categories")
async def source_categories(source_id: str, kind: str = Query("live"), user: User = Depends(iptv_user),
                            session: AsyncSession = Depends(get_session)) -> list[dict]:
    src = await _source(session, source_id, user)
    try:
        cats = await iptv.categories(iptv.creds_of(src), _kind(kind))
        all_items = await iptv.items(iptv.creds_of(src), kind)
    except iptv.XtreamError as e:
        raise _fail(e)
    counts: dict[str | None, int] = {}
    for i in all_items:
        counts[i["category_id"]] = counts.get(i["category_id"], 0) + 1
    return [{**c, "count": counts.get(c["id"], 0)} for c in cats if counts.get(c["id"])]


@router.get("/sources/{source_id}/items")
async def source_items(source_id: str, kind: str = Query("live"), category: str | None = None,
                       q: str | None = Query(None, max_length=100), sort: str = Query("default"),
                       offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000),
                       user: User = Depends(iptv_user), session: AsyncSession = Depends(get_session)) -> dict:
    src = await _source(session, source_id, user)
    try:
        rows = await iptv.items(iptv.creds_of(src), _kind(kind))
    except iptv.XtreamError as e:
        raise _fail(e)
    if category:
        rows = [r for r in rows if r["category_id"] == category]
    if q and q.strip():
        words = q.casefold().split()
        rows = [r for r in rows if all(w in r["name"].casefold() for w in words)]
    if sort == "name":
        rows = sorted(rows, key=lambda r: r["name"].casefold())
    elif sort == "added" and kind != "live":
        rows = sorted(rows, key=lambda r: r.get("added") or "", reverse=True)
    elif sort == "rating" and kind != "live":
        rows = sorted(rows, key=lambda r: r.get("rating") or 0, reverse=True)
    return {"total": len(rows), "items": rows[offset: offset + limit]}


@router.get("/sources/{source_id}/epg/{stream_id}")
async def channel_epg(source_id: str, stream_id: str, user: User = Depends(iptv_user),
                      session: AsyncSession = Depends(get_session)) -> list[dict]:
    src = await _source(session, source_id, user)
    try:
        return await iptv.short_epg(iptv.creds_of(src), stream_id)
    except iptv.XtreamError:
        return []  # no guide is not an error worth a red message


@router.get("/sources/{source_id}/movie/{vod_id}")
async def movie_info(source_id: str, vod_id: str, user: User = Depends(iptv_user),
                     session: AsyncSession = Depends(get_session)) -> dict:
    src = await _source(session, source_id, user)
    try:
        return await iptv.vod_info(iptv.creds_of(src), vod_id)
    except iptv.XtreamError as e:
        raise _fail(e)


@router.get("/sources/{source_id}/series/{series_id}")
async def series_detail(source_id: str, series_id: str, user: User = Depends(iptv_user),
                        session: AsyncSession = Depends(get_session)) -> dict:
    src = await _source(session, source_id, user)
    try:
        return await iptv.series_info(iptv.creds_of(src), series_id)
    except iptv.XtreamError as e:
        raise _fail(e)


@router.get("/img")
async def picture(u: str = Query(..., max_length=2000), s: str = Query(..., max_length=64),
                  _: User = Depends(iptv_user)):
    if not iptv.image_signature_ok(u, s):
        raise HTTPException(404, "Not found")
    found = await iptv.image(u)
    if not found:
        raise HTTPException(404, "No picture")
    path, ctype = found
    return FileResponse(path, media_type=ctype, headers={"Cache-Control": "private, max-age=604800"})


# ------------------------------------------------------------------ playing

def _stream_kind(kind: str) -> str:
    if kind not in ("live", "vod", "episode"):
        raise HTTPException(400, "kind must be live, vod or episode")
    return kind


@router.get("/sources/{source_id}/play/{kind}/{stream_id}")
async def play(source_id: str, kind: str, stream_id: str, ext: str | None = None,
               duration: float | None = Query(None, gt=0), height: int | None = Query(None, gt=0),
               user: User = Depends(iptv_user), session: AsyncSession = Depends(get_session)) -> dict:
    """How to play one stream: 'live' (rolling HLS), 'direct' (the file as it is), or HLS
    converted on the fly with a seek bar (needs the length)."""
    src = await _source(session, source_id, user)
    base = f"/api/iptv/sources/{src.id}"
    if _stream_kind(kind) == "live":
        return {"mode": "live", "url": f"{base}/ch/live/{stream_id}/copy/index.m3u8",
                "convert_url": f"{base}/ch/live/{stream_id}/convert/index.m3u8"}
    if kind == "vod" and (not duration or not ext):
        try:
            info = await iptv.vod_info(iptv.creds_of(src), stream_id)
        except iptv.XtreamError as e:
            raise _fail(e)
        duration, height, ext = duration or info["duration"], height or info["height"], ext or info["ext"]
    ext = (ext or "mp4").lower()
    if not iptv.valid_ext(ext):
        raise HTTPException(400, "Unknown file type")
    out: dict = {"mode": "direct" if ext in DIRECT_EXT else "hls", "duration": duration,
                 "direct_url": f"{base}/file/{kind}/{stream_id}.{ext}" if ext in DIRECT_EXT else None,
                 "qualities": [], "hls_url": None,
                 "convert_url": f"{base}/ch/{kind}/{stream_id}/convert/index.m3u8?ext={ext}"}
    if duration:
        out["qualities"] = transcode.qualities_for(height)
        query = f"?d={duration:.3f}&ext={ext}" + (f"&h={height}" if height else "")
        out["hls_url"] = f"{base}/hls/{kind}/{stream_id}/{{quality}}/index.m3u8{query}"
    elif out["mode"] == "hls":
        out["mode"] = "convert"  # length unknown: a growing playlist without seeking ahead
    return out


@router.get("/sources/{source_id}/ch/{kind}/{stream_id}/{mode}/index.m3u8")
async def channel_playlist(source_id: str, kind: str, stream_id: str, mode: str, ext: str | None = None,
                           v: str | None = None, user: User = Depends(iptv_user),
                           session: AsyncSession = Depends(get_session)) -> PlainTextResponse:
    src = await _source(session, source_id, user)
    if mode not in ("copy", "convert") or not re.fullmatch(r"[\w-]{1,32}", stream_id):
        raise HTTPException(404, "Not found")
    _stream_kind(kind)
    if ext is not None and not iptv.valid_ext(ext):
        raise HTTPException(400, "Unknown file type")
    key = f"{src.id}-{kind}-{stream_id}-{mode}"
    url = iptv.stream_url(iptv.creds_of(src), "live" if kind == "live" else ("vod" if kind == "vod" else "series"),
                          stream_id, ext)
    try:
        text = await live.open(key, url, f"{src.name} {kind} {stream_id}", mode == "convert",
                               _viewer(user, v), rolling=kind == "live")
    except LiveBusy:
        raise HTTPException(503, "Too many channels are playing at once. Stop one and try again.")
    except LiveError as e:
        detail = str(e).lower()
        if any(w in detail for w in ("403", "401", "forbidden", "unauthorized")):
            raise HTTPException(502, "The IPTV server refused this channel. Your plan may allow fewer screens at once.")
        if "404" in detail or "not found" in detail:
            raise HTTPException(502, "This channel is off the air right now.")
        raise HTTPException(502, "This channel couldn't be played right now.")
    return PlainTextResponse(text, media_type=HLS_TYPE, headers=NO_STORE)


@router.get("/sources/{source_id}/ch/{kind}/{stream_id}/{mode}/{name}")
async def channel_segment(source_id: str, kind: str, stream_id: str, mode: str, name: str,
                          user: User = Depends(iptv_user), session: AsyncSession = Depends(get_session)):
    src = await _source(session, source_id, user)
    path = live.segment(f"{src.id}-{kind}-{stream_id}-{mode}", name)
    if path is None:
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="video/mp2t", headers=NO_STORE)


class StopIn(BaseModel):
    v: str | None = None


@router.post("/stop", status_code=204)
async def stop_watching(body: StopIn | None = None, v: str | None = None, user: User = Depends(iptv_user)) -> None:
    """The player closed: free the provider connection now instead of after a minute."""
    await live.leave(_viewer(user, (body.v if body else None) or v))


@router.get("/sources/{source_id}/file/{kind}/{name}")
async def direct_file(source_id: str, kind: str, name: str, request: Request,
                      user: User = Depends(iptv_user), session: AsyncSession = Depends(get_session)):
    src = await _source(session, source_id, user)
    if _stream_kind(kind) == "live":
        raise HTTPException(404, "Not found")
    m = re.fullmatch(r"([\w-]{1,32})\.([A-Za-z0-9]{1,5})", name)
    if not m or m.group(2).lower() not in DIRECT_EXT:
        raise HTTPException(404, "Not found")
    url = iptv.stream_url(iptv.creds_of(src), "vod" if kind == "vod" else "series", m.group(1), m.group(2))
    headers = {"User-Agent": iptv.USER_AGENT}
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]
    http = iptv.client(timeout=60)
    try:
        upstream = await http.send(http.build_request("GET", url, headers=headers), stream=True)
    except Exception:
        await http.aclose()
        raise HTTPException(502, "Can't reach the IPTV server.")
    if upstream.status_code >= 400:
        await upstream.aclose()
        await http.aclose()
        raise HTTPException(502, "The IPTV server didn't send this video.")
    out_headers = {k: upstream.headers[k] for k in ("content-length", "content-range", "accept-ranges")
                   if k in upstream.headers}
    ctype = upstream.headers.get("content-type", "")
    if not ctype.startswith("video/"):
        ctype = DIRECT_EXT[m.group(2).lower()]

    async def body():
        try:
            async for chunk in upstream.aiter_bytes(256 * 1024):
                yield chunk
        finally:
            await upstream.aclose()
            await http.aclose()

    return StreamingResponse(body(), status_code=upstream.status_code, media_type=ctype, headers=out_headers)


def _hls_session(src: IptvSource, kind: str, stream_id: str, quality: str, d: float, h: int | None,
                 ext: str, user: User) -> transcode.Session:
    if quality not in transcode.QUALITIES or not re.fullmatch(r"[\w-]{1,32}", stream_id) or not iptv.valid_ext(ext):
        raise HTTPException(404, "Not found")
    url = iptv.stream_url(iptv.creds_of(src), "vod" if kind == "vod" else "series", stream_id, ext)
    try:
        return transcode.manager.session(f"iptv-{src.id}-{kind}-{stream_id}", f"IPTV {kind} {stream_id}", url,
                                         d, h, quality, 0, user.username,
                                         input_args=["-user_agent", iptv.USER_AGENT])
    except transcode.TooBusy:
        raise HTTPException(503, "The server is busy converting other videos. Try again in a minute.")


@router.get("/sources/{source_id}/hls/{kind}/{stream_id}/{quality}/index.m3u8")
async def vod_playlist(source_id: str, kind: str, stream_id: str, quality: str,
                       d: float = Query(..., gt=0, lt=360000), ext: str = Query("mkv"), h: int | None = Query(None, gt=0),
                       user: User = Depends(iptv_user), session: AsyncSession = Depends(get_session)) -> PlainTextResponse:
    src = await _source(session, source_id, user)
    if _stream_kind(kind) == "live":
        raise HTTPException(404, "Not found")
    _hls_session(src, kind, stream_id, quality, d, h, ext, user)
    query = f"?d={d:.3f}&ext={ext}" + (f"&h={h}" if h else "")
    return PlainTextResponse(transcode.playlist(d, query), media_type=HLS_TYPE, headers=NO_STORE)


@router.get("/sources/{source_id}/hls/{kind}/{stream_id}/{quality}/seg/{n}.ts")
async def vod_segment(source_id: str, kind: str, stream_id: str, quality: str, n: int,
                      d: float = Query(..., gt=0, lt=360000), ext: str = Query("mkv"), h: int | None = Query(None, gt=0),
                      user: User = Depends(iptv_user), session: AsyncSession = Depends(get_session)):
    src = await _source(session, source_id, user)
    if _stream_kind(kind) == "live" or n < 0 or n >= transcode.segment_count(d):
        raise HTTPException(404, "Not found")
    s = _hls_session(src, kind, stream_id, quality, d, h, ext, user)
    try:
        path = await transcode.manager.segment(s, n)
    except (RuntimeError, TimeoutError):
        raise HTTPException(502, "The IPTV server stopped sending this video.")
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ favourites

class FavoriteIn(BaseModel):
    source_id: str
    kind: str
    stream_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    icon: str | None = Field(default=None, max_length=2400)
    ext: str | None = Field(default=None, max_length=8)


def _fav(f: IptvFavorite) -> dict:
    return {"id": f.id, "source_id": f.source_id, "kind": f.kind, "stream_id": f.stream_id, "name": f.name,
            "icon": f.icon, "ext": f.ext, "created_at": f.created_at.isoformat() if f.created_at else None}


@router.get("/favorites")
async def list_favorites(source_id: str | None = None, user: User = Depends(iptv_user),
                         session: AsyncSession = Depends(get_session)) -> list[dict]:
    stmt = select(IptvFavorite).where(IptvFavorite.user_id == user.id)
    if source_id:
        stmt = stmt.where(IptvFavorite.source_id == source_id)
    return [_fav(f) for f in (await session.scalars(stmt.order_by(IptvFavorite.created_at))).all()]


@router.post("/favorites", status_code=201)
async def add_favorite(body: FavoriteIn, user: User = Depends(iptv_user),
                       session: AsyncSession = Depends(get_session)) -> dict:
    await _source(session, body.source_id, user)
    _kind(body.kind)
    existing = await session.scalar(select(IptvFavorite).where(
        IptvFavorite.user_id == user.id, IptvFavorite.source_id == body.source_id,
        IptvFavorite.kind == body.kind, IptvFavorite.stream_id == body.stream_id))
    if existing:
        return _fav(existing)
    # only our own signed picture links, never an outside address
    icon = body.icon if body.icon and body.icon.startswith("/api/iptv/img?") else None
    fav = IptvFavorite(user_id=user.id, source_id=body.source_id, kind=body.kind, stream_id=body.stream_id,
                       name=body.name, icon=icon, ext=body.ext if iptv.valid_ext(body.ext) else None)
    session.add(fav)
    await session.commit()
    return _fav(fav)


@router.delete("/favorites/{favorite_id}", status_code=204)
async def remove_favorite(favorite_id: str, user: User = Depends(iptv_user),
                          session: AsyncSession = Depends(get_session)) -> None:
    fav = await session.get(IptvFavorite, favorite_id)
    if fav is None or fav.user_id != user.id:
        raise HTTPException(404, "Not found")
    await session.delete(fav)
    await session.commit()
