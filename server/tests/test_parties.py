"""Watch parties: REST API, live sync over WebSocket, reminders, age limits."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conftest import make_video


@pytest.fixture
def tc(tmp_path, monkeypatch):
    """A synchronous client, because WebSockets are tested with Starlette's TestClient."""
    monkeypatch.setenv("GHARBOX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GHARBOX_REDIS_URL", "")
    monkeypatch.setenv("GHARBOX_DATABASE_URL", "")
    monkeypatch.setenv("GHARBOX_MEDIA_LIBRARIES", "")
    monkeypatch.setenv("GHARBOX_MEDIA_ROOT", "")
    (tmp_path / "drives").mkdir()
    (tmp_path / "drives" / "t").symlink_to(tmp_path)  # a pretend drive, so categories can be added
    monkeypatch.setenv("GHARBOX_DRIVES_DIR", str(tmp_path / "drives"))
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    from app.security import login_ip_throttle, login_throttle
    from app.services.party_rooms import rooms
    login_throttle._fails.clear()
    login_ip_throttle._fails.clear()
    rooms.rooms.clear()
    with TestClient(create_app(), base_url="http://testserver") as client:
        yield client
    get_settings.cache_clear()


def auth(tc, username, password):
    r = tc.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def family(tc, tmp_path):
    tc.post("/api/setup", json={"username": "mahbub", "password": "supersecret"})
    tc.cookies.clear()
    host = auth(tc, "mahbub", "supersecret")
    tc.post("/api/users", json={"username": "rina", "password": "password12"}, headers=host)
    tc.post("/api/users", json={"username": "nabil", "password": "kidpassword"}, headers=host)
    tc.cookies.clear()
    users = {u["username"]: u["id"] for u in tc.get("/api/users", headers=host).json()}
    make_video(tmp_path / "movies" / "Monpura (2009).mp4", seconds=3)
    tc.post("/api/libraries", json={"name": "Movies", "path": str(tmp_path / "movies")}, headers=host)
    for _ in range(100):
        media = tc.get("/api/media", headers=host).json()
        if media:
            break
        time.sleep(0.1)
    return {"host": host, "rina": auth(tc, "rina", "password12"), "nabil": auth(tc, "nabil", "kidpassword"),
            "ids": users, "media_id": media[0]["id"]}


DEBUG = False


def recv(ws, kind, limit=20):
    """Next message of a given type (skipping others)."""
    for _ in range(limit):
        msg = ws.receive_json()
        if DEBUG:
            print("  <-", kind, "got", {k: v for k, v in msg.items() if k != "chat"}, flush=True)
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def make_party(tc, f, **extra):
    r = tc.post("/api/parties", json={"media_id": f["media_id"], "invite": [f["ids"]["rina"]], **extra},
                headers=f["host"])
    assert r.status_code == 201, r.text
    return r.json()


def test_create_list_rsvp_and_invite_notification(tc, family):
    p = make_party(tc, family, scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    assert p["title"] == "Monpura" and p["is_host"] and [m["username"] for m in p["members"]] == ["rina"]
    notes = tc.get("/api/notifications", headers=family["rina"]).json()["items"]
    assert notes[0]["title"] == "mahbub invited you to watch Monpura" and notes[0]["link"] == f"/party/{p['id']}"
    mine = tc.get("/api/parties", headers=family["rina"]).json()
    assert [x["id"] for x in mine] == [p["id"]] and mine[0]["my_rsvp"] == "invited"
    r = tc.put(f"/api/parties/{p['id']}/rsvp", json={"rsvp": "going"}, headers=family["rina"])
    assert r.json()["my_rsvp"] == "going"
    host_notes = [n["title"] for n in tc.get("/api/notifications", headers=family["host"]).json()["items"]]
    assert "rina is coming to Monpura" in host_notes
    # people who weren't invited can't see it
    assert tc.get(f"/api/parties/{p['id']}", headers=family["nabil"]).status_code == 404
    assert tc.patch(f"/api/parties/{p['id']}", json={"control": "host"}, headers=family["rina"]).status_code == 403


def test_kids_cant_be_invited_to_unsuitable_titles(tc, family):
    tc.patch(f"/api/users/{family['ids']['nabil']}", json={"max_age": 7}, headers=family["host"])
    r = tc.post("/api/parties", json={"media_id": family["media_id"], "invite": [family["ids"]["nabil"]]},
                headers=family["host"])
    assert r.status_code == 400 and "nabil" in r.json()["detail"]
    tc.put(f"/api/media/{family['media_id']}/rating", json={"age_rating": 0}, headers=family["host"])
    r = tc.post("/api/parties", json={"media_id": family["media_id"], "invite": [family["ids"]["nabil"]]},
                headers=family["host"])
    assert r.status_code == 201


def test_live_sync_play_pause_seek_and_control(tc, family):
    p = make_party(tc, family)
    url = f"/api/parties/{p['id']}/ws"
    with tc.websocket_connect(url, headers=family["host"]) as host, \
            tc.websocket_connect(url, headers=family["rina"]) as rina:
        hello = recv(host, "hello")
        assert hello["host"] and hello["you"] == "mahbub"
        people = recv(rina, "people")
        assert [x["username"] for x in people["people"]] == ["mahbub", "rina"] and people["people"][0]["host"]

        # clock sync
        host.send_json({"type": "ping", "t0": 123})
        pong = recv(host, "pong")
        assert pong["t0"] == 123 and abs(pong["server"] - time.time()) < 2

        host.send_json({"type": "play", "position": 10})
        s = recv(rina, "state")
        while not s["playing"]:
            s = recv(rina, "state")
        assert s["position"] == 10 and s["by"] == "mahbub"
        assert 0.3 < s["at"] - s["server_time"] <= 0.7  # everyone starts together a moment later

        rina.send_json({"type": "pause", "position": 12.5})
        s = recv(host, "state")
        while s["playing"]:
            s = recv(host, "state")
        assert s["position"] == 12.5 and s["by"] == "rina"

        rina.send_json({"type": "seek", "position": 30})
        s = recv(host, "state")
        while s["position"] != 30:
            s = recv(host, "state")

        # host-only control
        tc.patch(f"/api/parties/{p['id']}", json={"control": "host"}, headers=family["host"])
        recv(rina, "state")
        rina.send_json({"type": "play", "position": 30})
        assert "Only the host" in recv(rina, "notice")["text"]


def test_wait_for_everyone_while_loading(tc, family):
    p = make_party(tc, family)
    url = f"/api/parties/{p['id']}/ws"
    with tc.websocket_connect(url, headers=family["host"]) as host, \
            tc.websocket_connect(url, headers=family["rina"]) as rina:
        recv(host, "hello")
        host.send_json({"type": "play", "position": 5})
        recv(host, "state")
        rina.send_json({"type": "buffering", "state": True})
        s = recv(host, "state")
        while s["playing"]:
            s = recv(host, "state")
        assert s["waiting_for"] == ["rina"]
        rina.send_json({"type": "buffering", "state": False})
        s = recv(host, "state")
        while not s["playing"]:
            s = recv(host, "state")
        assert s["waiting_for"] == []


def test_chat_reactions_and_history(tc, family):
    p = make_party(tc, family)
    url = f"/api/parties/{p['id']}/ws"
    with tc.websocket_connect(url, headers=family["host"]) as host, \
            tc.websocket_connect(url, headers=family["rina"]) as rina:
        recv(host, "hello")
        rina.send_json({"type": "chat", "text": "  এই সিনটা দারুণ!  "})
        m = recv(host, "chat")
        assert m["username"] == "rina" and m["text"] == "এই সিনটা দারুণ!"
        rina.send_json({"type": "react", "emoji": "🔥"})
        assert recv(host, "react")["emoji"] == "🔥"
        rina.send_json({"type": "react", "emoji": "<script>"})  # not an allowed reaction: dropped
        rina.send_json({"type": "chat", "text": "second"})
        assert recv(host, "chat")["text"] == "second"
    history = tc.get(f"/api/parties/{p['id']}/chat", headers=family["rina"]).json()
    assert [h["text"] for h in history] == ["এই সিনটা দারুণ!", "second"]
    # rejoining shows the history
    with tc.websocket_connect(url, headers=family["rina"]) as again:
        assert [c["text"] for c in recv(again, "hello")["chat"]] == ["এই সিনটা দারুণ!", "second"]


def test_socket_security(tc, family):
    p = make_party(tc, family)
    url = f"/api/parties/{p['id']}/ws"
    tc.cookies.clear()  # only the headers below decide who's asking
    for headers, code in ((family["nabil"], 4404), ({}, 4401),
                          ({**family["rina"], "Origin": "https://evil.example"}, 4403),
                          ({**family["rina"], "X-GharBox-Gateway": "public"}, 4403)):
        with pytest.raises(WebSocketDisconnect) as exc:
            with tc.websocket_connect(url, headers=headers) as ws:
                ws.receive_json()
        assert exc.value.code == code
    # the right origin is fine
    with tc.websocket_connect(url, headers={**family["rina"], "Origin": "http://testserver"}) as ws:
        assert recv(ws, "hello")["you"] == "rina"


def test_ending_a_party(tc, family):
    p = make_party(tc, family)
    url = f"/api/parties/{p['id']}/ws"
    with tc.websocket_connect(url, headers=family["rina"]) as rina:
        recv(rina, "hello")
        assert tc.post(f"/api/parties/{p['id']}/end", headers=family["rina"]).status_code == 403
        tc.post(f"/api/parties/{p['id']}/end", headers=family["host"])
        assert recv(rina, "ended")["by"] == "mahbub"
    assert tc.get("/api/parties", headers=family["rina"]).json() == []
    with pytest.raises(WebSocketDisconnect):
        with tc.websocket_connect(url, headers=family["rina"]) as ws:
            ws.receive_json()


def test_reminders(tc, family):
    p = make_party(tc, family, scheduled_at=(datetime.now(timezone.utc) + timedelta(minutes=8)).isoformat())
    tc.put(f"/api/parties/{p['id']}/rsvp", json={"rsvp": "going"}, headers=family["rina"])
    import asyncio
    from app.db import sessionmaker
    from app.routers.parties import send_reminders

    async def run():
        async with sessionmaker()() as s:
            return await send_reminders(s)

    sent = tc.portal.call(run)
    assert sent == 2  # host and rina
    assert tc.portal.call(run) == 0  # only once
    titles = [n["title"] for n in tc.get("/api/notifications", headers=family["rina"]).json()["items"]]
    assert any(t.startswith("Monpura starts in") and t.endswith("minutes") for t in titles)
    assert asyncio  # keep import used
