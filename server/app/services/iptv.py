"""IPTV: a Live TV / movies / series subscription (Xtream Codes API) inside ZiraHive.

Everything goes through the ZiraHive server, never straight from the browser to the provider:
- the provider's username and password stay on the server (they are part of every stream address);
- the web app only loads pictures and video from itself (Content-Security-Policy), and most
  providers only speak plain http, which an https page can't load anyway;
- one live channel watched on three screens is one connection to the provider (most plans allow
  only one or two).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

KINDS = ("live", "vod", "series")
# Many providers turn away anything that doesn't look like a video player.
USER_AGENT = "VLC/3.0.20 LibVLC/3.0.20"
LIST_TTL = 600     # channel / movie / series lists, seconds
INFO_TTL = 1800    # one movie's or series' details
EPG_TTL = 120
IMAGE_MAX = 5 * 1024 * 1024
_EXT = re.compile(r"^[A-Za-z0-9]{1,5}$")

# tests swap in an httpx.MockTransport
transport: httpx.AsyncBaseTransport | None = None


class XtreamError(Exception):
    """A problem worth showing to the person, in plain words."""


@dataclass(frozen=True)
class Creds:
    id: str
    server: str
    username: str
    password: str

    @property
    def fingerprint(self) -> str:
        raw = f"{self.server}\n{self.username}\n{self.password}".encode()
        return hashlib.sha256(raw).hexdigest()[:16]


def creds_of(src: Any) -> Creds:
    return Creds(src.id, src.server, src.username, src.password)


def normalize_server(raw: str, port: int | str | None = None) -> str:
    """'example.com', 'http://example.com:8080/player_api.php', ... -> 'http://example.com:8080'."""
    text = (raw or "").strip()
    if not text:
        raise XtreamError("Enter the server address.")
    if "://" not in text:
        text = "http://" + text
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise XtreamError("The server address should look like http://example.com:8080")
    host = parts.hostname
    if ":" in host:  # IPv6
        host = f"[{host}]"
    port_text = str(port).strip() if port not in (None, "") else ""
    if port_text:
        if not port_text.isdigit() or not 0 < int(port_text) < 65536:
            raise XtreamError("The port should be a number like 8080.")
        chosen = int(port_text)
    else:
        chosen = parts.port
    default = 443 if parts.scheme == "https" else 80
    return f"{parts.scheme}://{host}" + (f":{chosen}" if chosen and chosen != default else "")


def client(timeout: float = 20) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10), follow_redirects=True,
                             transport=transport, headers={"User-Agent": USER_AGENT})


# ------------------------------------------------------------------ cache

_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def _cached(key: str, ttl: float, make):
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    async with _locks.setdefault(key, asyncio.Lock()):
        hit = _cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        value = await make()
        _cache[key] = (time.monotonic() + ttl, value)
        if len(_cache) > 2000:  # keep memory in check
            now = time.monotonic()
            for k in [k for k, (exp, _) in _cache.items() if exp < now]:
                _cache.pop(k, None)
        return value


def forget(source_id: str) -> None:
    for k in [k for k in _cache if k.startswith(source_id + ":")]:
        _cache.pop(k, None)


# --------------------------------------------------------------- the API

async def api_call(c: Creds, action: str | None = None, **params: Any) -> Any:
    query: dict[str, Any] = {"username": c.username, "password": c.password}
    if action:
        query["action"] = action
    query.update({k: v for k, v in params.items() if v is not None})
    try:
        async with client() as http:
            r = await http.get(f"{c.server}/player_api.php", params=query)
    except httpx.TimeoutException:
        raise XtreamError("The IPTV server took too long to answer. Try again in a moment.")
    except httpx.HTTPError:
        raise XtreamError("Can't reach the IPTV server. Check the address and port.")
    if r.status_code in (401, 403):
        raise XtreamError("The IPTV server refused the username or password.")
    if r.status_code >= 400:
        raise XtreamError(f"The IPTV server answered with an error ({r.status_code}).")
    try:
        return r.json()
    except ValueError:
        raise XtreamError("That address doesn't look like an Xtream Codes IPTV server.")


def _iso(ts: Any) -> str | None:
    try:
        n = int(float(ts))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return datetime.fromtimestamp(n, timezone.utc).isoformat()


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # not NaN


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ("" if v is None else str(v))


def _list(v: Any) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


async def account(c: Creds) -> dict:
    data = await api_call(c)
    info = data.get("user_info") if isinstance(data, dict) else None
    if not isinstance(info, dict) or str(info.get("auth")) != "1":
        raise XtreamError("The IPTV server refused the username or password.")
    server = data.get("server_info") if isinstance(data.get("server_info"), dict) else {}
    return {
        "status": _text(info.get("status")) or "Active",
        "expires_at": _iso(info.get("exp_date")),
        "max_connections": _int(info.get("max_connections")),
        "active_connections": _int(info.get("active_cons")),
        "is_trial": str(info.get("is_trial")) == "1",
        "timezone": _text(server.get("timezone")) or None,
    }


_CATEGORY_ACTION = {"live": "get_live_categories", "vod": "get_vod_categories", "series": "get_series_categories"}
_LIST_ACTION = {"live": "get_live_streams", "vod": "get_vod_streams", "series": "get_series"}


async def categories(c: Creds, kind: str) -> list[dict]:
    async def make():
        rows = _list(await api_call(c, _CATEGORY_ACTION[kind]))
        return [{"id": _text(r.get("category_id")), "name": _text(r.get("category_name")) or "?"}
                for r in rows if isinstance(r, dict) and _text(r.get("category_id"))]
    return await _cached(f"{c.id}:{c.fingerprint}:cat:{kind}", LIST_TTL, make)


def _item(kind: str, r: dict) -> dict | None:
    if kind == "series":
        sid = _text(r.get("series_id"))
        icon = r.get("cover")
    else:
        sid = _text(r.get("stream_id"))
        icon = r.get("stream_icon")
    if not sid:
        return None
    item = {"id": sid, "name": _text(r.get("name")) or "?", "icon": sign_image(icon),
            "category_id": _text(r.get("category_id")) or None}
    if kind == "live":
        item.update(num=_int(r.get("num")), epg_id=_text(r.get("epg_channel_id")) or None,
                    archive=str(r.get("tv_archive")) == "1")
    elif kind == "vod":
        item.update(rating=_float(r.get("rating")), added=_iso(r.get("added")),
                    ext=_text(r.get("container_extension")) or "mp4")
    else:
        item.update(rating=_float(r.get("rating")), added=_iso(r.get("last_modified")),
                    year=_text(r.get("year") or r.get("releaseDate") or r.get("release_date"))[:4] or None)
    return item


async def items(c: Creds, kind: str) -> list[dict]:
    async def make():
        rows = _list(await api_call(c, _LIST_ACTION[kind]))
        return [i for i in (_item(kind, r) for r in rows if isinstance(r, dict)) if i]
    return await _cached(f"{c.id}:{c.fingerprint}:items:{kind}", LIST_TTL, make)


def _duration(info: dict) -> float | None:
    secs = _float(info.get("duration_secs"))
    if secs:
        return secs
    text = _text(info.get("duration"))
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text):
        parts = [int(p) for p in text.split(":")]
        return float(sum(p * 60 ** i for i, p in enumerate(reversed(parts))))
    return None


def _height(info: dict) -> int | None:
    video = info.get("video")
    return _int(video.get("height")) if isinstance(video, dict) else None


async def vod_info(c: Creds, vod_id: str) -> dict:
    async def make():
        data = await api_call(c, "get_vod_info", vod_id=vod_id)
        info = data.get("info") if isinstance(data, dict) and isinstance(data.get("info"), dict) else {}
        movie = data.get("movie_data") if isinstance(data, dict) and isinstance(data.get("movie_data"), dict) else {}
        if not movie and not info:
            raise XtreamError("This movie isn't on the IPTV server any more.")
        backdrops = info.get("backdrop_path")
        backdrop = backdrops[0] if isinstance(backdrops, list) and backdrops else backdrops
        return {
            "id": vod_id, "name": _text(movie.get("name") or info.get("name")) or "?",
            "plot": _text(info.get("plot") or info.get("description")) or None,
            "cast": _text(info.get("cast") or info.get("actors")) or None,
            "director": _text(info.get("director")) or None,
            "genre": _text(info.get("genre")) or None,
            "year": (_text(info.get("releasedate") or info.get("release_date")) or "")[:4] or None,
            "rating": _float(info.get("rating")),
            "duration": _duration(info), "height": _height(info),
            "poster": sign_image(info.get("movie_image") or info.get("cover_big")),
            "backdrop": sign_image(backdrop if isinstance(backdrop, str) else None),
            "ext": _text(movie.get("container_extension")) or "mp4",
        }
    return await _cached(f"{c.id}:{c.fingerprint}:vod:{vod_id}", INFO_TTL, make)


async def series_info(c: Creds, series_id: str) -> dict:
    async def make():
        data = await api_call(c, "get_series_info", series_id=series_id)
        if not isinstance(data, dict):
            raise XtreamError("This series isn't on the IPTV server any more.")
        info = data.get("info") if isinstance(data.get("info"), dict) else {}
        raw = data.get("episodes")
        groups = raw.items() if isinstance(raw, dict) else [(None, raw)] if isinstance(raw, list) else []
        episodes = []
        for season_key, eps in groups:
            for e in _list(eps):
                if not isinstance(e, dict) or not _text(e.get("id")):
                    continue
                einfo = e.get("info") if isinstance(e.get("info"), dict) else {}
                episodes.append({
                    "id": _text(e.get("id")),
                    "season": _int(e.get("season")) or _int(season_key) or 1,
                    "episode": _int(e.get("episode_num")),
                    "title": _text(e.get("title")) or "?",
                    "plot": _text(einfo.get("plot")) or None,
                    "duration": _duration(einfo), "height": _height(einfo),
                    "image": sign_image(einfo.get("movie_image")),
                    "ext": _text(e.get("container_extension")) or "mp4",
                })
        episodes.sort(key=lambda e: (e["season"], e["episode"] or 0))
        backdrops = info.get("backdrop_path")
        backdrop = backdrops[0] if isinstance(backdrops, list) and backdrops else backdrops
        return {
            "id": series_id, "name": _text(info.get("name")) or "?",
            "plot": _text(info.get("plot")) or None, "cast": _text(info.get("cast")) or None,
            "genre": _text(info.get("genre")) or None, "rating": _float(info.get("rating")),
            "year": (_text(info.get("releaseDate") or info.get("release_date")) or "")[:4] or None,
            "poster": sign_image(info.get("cover")),
            "backdrop": sign_image(backdrop if isinstance(backdrop, str) else None),
            "episodes": episodes,
        }
    return await _cached(f"{c.id}:{c.fingerprint}:series:{series_id}", INFO_TTL, make)


def _b64(v: Any) -> str:
    text = _text(v)
    if not text:
        return ""
    try:
        return base64.b64decode(text + "=" * (-len(text) % 4), validate=False).decode("utf-8", "replace").strip()
    except Exception:
        return text


async def short_epg(c: Creds, stream_id: str, limit: int = 6) -> list[dict]:
    async def make():
        data = await api_call(c, "get_short_epg", stream_id=stream_id, limit=limit)
        rows = data.get("epg_listings") if isinstance(data, dict) else None
        out = []
        for r in _list(rows):
            if not isinstance(r, dict):
                continue
            start = _iso(r.get("start_timestamp")) or None
            end = _iso(r.get("stop_timestamp") or r.get("end_timestamp")) or None
            out.append({"title": _b64(r.get("title")) or "?", "description": _b64(r.get("description")) or None,
                        "start": start, "end": end})
        return out
    return await _cached(f"{c.id}:{c.fingerprint}:epg:{stream_id}", EPG_TTL, make)


def stream_url(c: Creds, kind: str, stream_id: str, ext: str | None = None) -> str:
    """The provider's address for one stream. Contains the password: never send it to a browser."""
    u, p = quote(c.username, safe=""), quote(c.password, safe="")
    sid = quote(stream_id, safe="")
    if kind == "live":
        return f"{c.server}/live/{u}/{p}/{sid}.ts"
    ext = ext if ext and _EXT.match(ext) else "mp4"
    folder = "movie" if kind == "vod" else "series"
    return f"{c.server}/{folder}/{u}/{p}/{sid}.{ext}"


def valid_ext(ext: str | None) -> bool:
    return bool(ext and _EXT.match(ext))


# ------------------------------------------------------------- pictures

def _image_sig(u: str) -> str:
    key = get_settings().resolved_secret().encode()
    return hmac.new(key, f"iptv-img\n{u}".encode(), hashlib.sha256).hexdigest()[:32]


def sign_image(u: Any) -> str | None:
    """Channel logos and posters come through ZiraHive (/api/iptv/img), signed so the endpoint
    only fetches pictures the IPTV server itself listed."""
    if not isinstance(u, str):
        return None
    u = u.strip()
    if not u.lower().startswith(("http://", "https://")) or len(u) > 2000:
        return None
    return f"/api/iptv/img?u={quote(u, safe='')}&s={_image_sig(u)}"


def image_signature_ok(u: str, s: str) -> bool:
    return hmac.compare_digest(_image_sig(u), s or "")


def _private_host(u: str) -> bool:
    host = (urlsplit(u).hostname or "").lower()
    if host in ("localhost", "") or host.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _image_dir() -> Path:
    return get_settings().cache_dir / "iptv-img"


async def image(u: str) -> tuple[Path, str] | None:
    """The picture, downloaded once and kept in the cache folder. None if it can't be had."""
    folder = _image_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(u.encode()).hexdigest()
    path, meta, miss = folder / name, folder / f"{name}.type", folder / f"{name}.miss"
    if path.exists() and meta.exists():
        return path, meta.read_text()
    if miss.exists() and time.time() - miss.stat().st_mtime < 3600:
        return None
    if _private_host(u):
        return None
    try:
        async with client(timeout=15) as http:
            async with http.stream("GET", u) as r:
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if r.status_code != 200 or not ctype.startswith("image/") or ctype == "image/svg+xml":
                    raise ValueError(f"not a picture ({r.status_code} {ctype})")
                body = bytearray()
                async for chunk in r.aiter_bytes():
                    body += chunk
                    if len(body) > IMAGE_MAX:
                        raise ValueError("too big")
    except Exception as e:  # noqa: BLE001 - any failure just means "no picture"
        log.debug("iptv picture %s: %s", u, e)
        miss.touch()
        return None
    tmp = folder / f"{name}.part"
    tmp.write_bytes(bytes(body))
    tmp.replace(path)
    meta.write_text(ctype)
    return path, ctype
