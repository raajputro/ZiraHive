"""IPTV (Xtream Codes): sources, browsing, pictures, playing, favourites, kids' profiles."""
from __future__ import annotations

import base64
import functools
import http.server
import json
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.services import iptv

SERVER = "http://iptv.example:8080"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def fake_xtream(request: httpx.Request) -> httpx.Response:
    url = urlsplit(str(request.url))
    if url.netloc == "img.example":
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    if url.path.startswith("/movie/"):
        body = b"x" * 1000
        if request.headers.get("range") == "bytes=0-9":
            return httpx.Response(206, content=body[:10], headers={"content-type": "video/mp4", "content-range": "bytes 0-9/1000"})
        return httpx.Response(200, content=body, headers={"content-type": "video/mp4"})
    if url.path != "/player_api.php":
        return httpx.Response(404)
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    if (q.get("username"), q.get("password")) != ("mahbub", "s3cret"):
        return httpx.Response(200, json={"user_info": {"auth": 0}})
    action = q.get("action")
    data: object
    if action is None:
        data = {"user_info": {"auth": 1, "status": "Active", "exp_date": "1893456000", "max_connections": "2",
                              "active_cons": "0", "is_trial": "0"}, "server_info": {"timezone": "Asia/Dhaka"}}
    elif action == "get_live_categories":
        data = [{"category_id": "1", "category_name": "Bangla"}, {"category_id": "2", "category_name": "Sports"},
                {"category_id": "9", "category_name": "Empty"}]
    elif action == "get_live_streams":
        data = [{"num": 1, "name": "BTV World", "stream_id": 101, "stream_icon": "http://img.example/btv.png",
                 "epg_channel_id": "btv.bd", "category_id": "1"},
                {"num": 2, "name": "Somoy TV", "stream_id": 102, "stream_icon": "", "category_id": "1"},
                {"num": 3, "name": "T Sports", "stream_id": 103, "stream_icon": None, "category_id": "2"}]
    elif action == "get_vod_categories":
        data = [{"category_id": "5", "category_name": "Bangla Movies"}]
    elif action == "get_vod_streams":
        data = [{"name": "Hawa", "stream_id": 501, "stream_icon": "http://img.example/hawa.jpg", "rating": "7.9",
                 "added": "1700000000", "category_id": "5", "container_extension": "mkv"},
                {"name": "Aynabaji", "stream_id": 502, "rating": "8.4", "added": "1600000000",
                 "category_id": "5", "container_extension": "mp4"}]
    elif action == "get_vod_info":
        data = {"info": {"plot": "Fishermen find a mysterious woman.", "duration_secs": 7800,
                         "releasedate": "2022-07-29", "movie_image": "http://img.example/hawa.jpg",
                         "video": {"height": 1080}},
                "movie_data": {"stream_id": 501, "name": "Hawa", "container_extension": "mkv"}}
    elif action == "get_series_categories":
        data = [{"category_id": "7", "category_name": "Web Series"}]
    elif action == "get_series":
        data = [{"series_id": 77, "name": "Mohanagar", "cover": "http://img.example/m.jpg", "category_id": "7"}]
    elif action == "get_series_info":
        data = {"info": {"name": "Mohanagar", "plot": "One night in a Dhaka police station."},
                "episodes": {"2": [{"id": "9002", "episode_num": 1, "title": "S2 E1", "container_extension": "mp4",
                                    "season": 2, "info": {"duration_secs": 1800}}],
                             "1": [{"id": "9001", "episode_num": 1, "title": "S1 E1", "container_extension": "mkv",
                                    "season": 1, "info": {"duration": "00:45:00"}}]}}
    elif action == "get_short_epg":
        enc = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731
        data = {"epg_listings": [{"title": enc("খবর"), "description": enc("Evening news"),
                                  "start_timestamp": "1760788800", "stop_timestamp": "1760792400"}]}
    else:
        data = []
    return httpx.Response(200, json=data)


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    monkeypatch.setattr(iptv, "transport", httpx.MockTransport(fake_xtream))
    iptv._cache.clear()
    yield


async def add(client, **extra):
    body = {"name": "My IPTV", "server": "iptv.example", "port": "8080", "username": "mahbub",
            "password": "s3cret", **extra}
    return await client.post("/api/iptv/sources", json=body)


def test_normalize_server():
    assert iptv.normalize_server("iptv.example", "8080") == SERVER
    assert iptv.normalize_server("http://iptv.example:8080/player_api.php?x=1") == SERVER
    assert iptv.normalize_server("https://iptv.example:443/") == "https://iptv.example"
    assert iptv.normalize_server(" http://1.2.3.4 ", 25461) == "http://1.2.3.4:25461"
    with pytest.raises(iptv.XtreamError):
        iptv.normalize_server("ftp://x")
    with pytest.raises(iptv.XtreamError):
        iptv.normalize_server("x.com", "abc")


async def test_sources_and_browsing(client, admin):
    assert (await add(client, password="wrong")).status_code == 400
    r = await add(client)
    assert r.status_code == 201, r.text
    src = r.json()
    assert src["server"] == SERVER and src["account"]["max_connections"] == 2
    assert "s3cret" not in r.text
    sid = src["id"]
    listed = (await client.get("/api/iptv/sources")).json()
    assert [s["name"] for s in listed] == ["My IPTV"] and "s3cret" not in json.dumps(listed)

    cats = (await client.get(f"/api/iptv/sources/{sid}/categories?kind=live")).json()
    assert [(c["name"], c["count"]) for c in cats] == [("Bangla", 2), ("Sports", 1)]  # empty ones hidden
    page = (await client.get(f"/api/iptv/sources/{sid}/items?kind=live&category=1")).json()
    assert page["total"] == 2 and page["items"][0]["name"] == "BTV World"
    assert page["items"][0]["icon"].startswith("/api/iptv/img?") and page["items"][1]["icon"] is None
    found = (await client.get(f"/api/iptv/sources/{sid}/items?kind=live&q=t%20spo")).json()
    assert [i["name"] for i in found["items"]] == ["T Sports"]
    movies = (await client.get(f"/api/iptv/sources/{sid}/items?kind=vod&sort=rating")).json()
    assert [m["name"] for m in movies["items"]] == ["Aynabaji", "Hawa"]

    movie = (await client.get(f"/api/iptv/sources/{sid}/movie/501")).json()
    assert movie["duration"] == 7800 and movie["year"] == "2022" and movie["ext"] == "mkv"
    series = (await client.get(f"/api/iptv/sources/{sid}/series/77")).json()
    assert [(e["season"], e["id"]) for e in series["episodes"]] == [(1, "9001"), (2, "9002")]
    assert series["episodes"][0]["duration"] == 2700
    epg = (await client.get(f"/api/iptv/sources/{sid}/epg/101")).json()
    assert epg[0]["title"] == "খবর" and epg[0]["start"].startswith("2025-10-18")

    # pictures come through ZiraHive, and only ones the provider listed
    icon = page["items"][0]["icon"]
    r = await client.get(icon)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert (await client.get(icon.replace("btv", "evil"))).status_code == 404

    # changing only the name keeps the login; a wrong new password is refused
    assert (await client.patch(f"/api/iptv/sources/{sid}", json={"name": "Home TV"})).json()["name"] == "Home TV"
    assert (await client.patch(f"/api/iptv/sources/{sid}", json={"password": "nope"})).status_code == 400


async def test_play_modes_and_direct_file(client, admin):
    sid = (await add(client)).json()["id"]
    live = (await client.get(f"/api/iptv/sources/{sid}/play/live/101")).json()
    assert live["mode"] == "live" and live["url"].endswith("/ch/live/101/copy/index.m3u8")
    mkv = (await client.get(f"/api/iptv/sources/{sid}/play/vod/501")).json()
    assert mkv["mode"] == "hls" and mkv["duration"] == 7800 and "1080p" in mkv["qualities"]
    assert "{quality}" in mkv["hls_url"] and "s3cret" not in json.dumps(mkv)
    mp4 = (await client.get(f"/api/iptv/sources/{sid}/play/vod/502?ext=mp4&duration=60")).json()
    assert mp4["mode"] == "direct"
    r = await client.get(mp4["direct_url"], headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.headers["content-range"] == "bytes 0-9/1000" and len(r.content) == 10
    ep = (await client.get(f"/api/iptv/sources/{sid}/play/episode/9001?ext=mkv")).json()
    assert ep["mode"] == "convert"  # length unknown: growing playlist
    playlist = await client.get(mkv["hls_url"].replace("{quality}", "480p"))
    assert playlist.status_code == 200 and "seg/0.ts?d=7800.000&ext=mkv" in playlist.text


async def test_live_channel_through_ffmpeg(client, admin, tmp_path, monkeypatch):
    """A real live remux: provider MPEG-TS (H.264 + MP2 audio) -> HLS with AAC."""
    ts = tmp_path / "ch.ts"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=12:size=320x240:rate=25",
                    "-f", "lavfi", "-i", "sine=duration=12", "-c:v", "libx264", "-g", "50", "-pix_fmt", "yuv420p",
                    "-c:a", "mp2", "-f", "mpegts", str(ts)], check=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = iptv.stream_url
    monkeypatch.setattr(iptv, "stream_url", lambda c, kind, sid, ext=None:
                        f"http://127.0.0.1:{srv.server_port}/{'ch' if sid == '101' else 'missing'}.ts")
    try:
        sid = (await add(client)).json()["id"]
        base = f"/api/iptv/sources/{sid}/ch/live"
        r = await client.get(f"{base}/101/copy/index.m3u8?v=tv-1")
        assert r.status_code == 200, r.text
        newest = [line for line in r.text.splitlines() if line.endswith(".ts")][-1]  # older ones roll away
        seg = await client.get(f"{base}/101/copy/{newest}")
        assert seg.status_code == 200 and len(seg.content) > 1000
        bad = await client.get(f"{base}/102/copy/index.m3u8?v=tv-1")
        assert bad.status_code == 502 and "127.0.0.1" not in bad.text
        assert (await client.post("/api/iptv/stop", json={"v": "tv-1"})).status_code == 204
    finally:
        srv.shutdown()
        monkeypatch.setattr(iptv, "stream_url", real)


async def test_sharing_kids_and_favorites(client, admin):
    sid = (await add(client, shared=True)).json()["id"]
    private = (await add(client, name="Mine only")).json()["id"]
    await client.post("/api/users", json={"username": "rina", "password": "password12"})
    await client.post("/api/users", json={"username": "tuktuki", "password": "password12"})
    users = (await client.get("/api/users")).json()
    kid = next(u for u in users if u["username"] == "tuktuki")
    await client.patch(f"/api/users/{kid['id']}", json={"max_age": 7})

    async def as_(name):
        tok = (await client.post("/api/auth/login", json={"username": name, "password": "password12"})).json()["token"]
        return {"Authorization": f"Bearer {tok}"}
    rina, tuk = await as_("rina"), await as_("tuktuki")

    seen = (await client.get("/api/iptv/sources", headers=rina)).json()
    assert [s["id"] for s in seen] == [sid] and seen[0]["server"] is None and not seen[0]["can_manage"]
    assert (await client.get(f"/api/iptv/sources/{private}/items", headers=rina)).status_code == 404
    assert (await client.delete(f"/api/iptv/sources/{sid}", headers=rina)).status_code == 403
    assert (await client.get("/api/iptv/sources", headers=tuk)).status_code == 403

    fav = {"source_id": sid, "kind": "live", "stream_id": "101", "name": "BTV World", "icon": "http://evil/x.png"}
    r = await client.post("/api/iptv/favorites", json=fav, headers=rina)
    assert r.status_code == 201 and r.json()["icon"] is None
    assert (await client.post("/api/iptv/favorites", json=fav, headers=rina)).json()["id"] == r.json()["id"]
    assert len((await client.get("/api/iptv/favorites", headers=rina)).json()) == 1
    assert (await client.get("/api/iptv/favorites")).json() == []  # per person
    assert (await client.delete(f"/api/iptv/favorites/{r.json()['id']}", headers=rina)).status_code == 204
