"""Batch 7: passkeys, voice chat signalling, plugins, linked servers."""
from __future__ import annotations

import base64
import hashlib
import json
import os

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

ORIGIN = "https://zirahive.example.ts.net"
HOST = {"Origin": ORIGIN, "Host": "zirahive.example.ts.net"}


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftKey:
    """A passkey the way a phone keeps it: an EC key pair, a credential id, a counter."""

    def __init__(self, rp_id: str = "zirahive.example.ts.net"):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.rp_id, self.count, self.user_handle = rp_id, 0, None

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def create(self, options: dict, origin: str = ORIGIN) -> dict:
        self.user_handle = options["user"]["id"]
        client = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": origin}).encode()
        auth = (hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x45]) + self.count.to_bytes(4, "big")
                + bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + self._cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(client), "attestationObject": b64u(att), "transports": ["internal"]}}

    def get(self, options: dict, origin: str = ORIGIN) -> dict:
        self.count += 1
        client = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": origin}).encode()
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05]) + self.count.to_bytes(4, "big")
        sig = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(client), "authenticatorData": b64u(auth),
                             "signature": b64u(sig), "userHandle": self.user_handle}}


async def add_passkey(client, key: SoftKey, name="Pixel 7") -> dict:
    o = (await client.post("/api/auth/passkeys/register/options", headers=HOST)).json()
    assert o["options"]["rp"]["id"] == "zirahive.example.ts.net"
    assert o["options"]["authenticatorSelection"]["residentKey"] == "required"
    r = await client.post("/api/auth/passkeys/register", headers=HOST,
                          json={"state": o["state"], "credential": key.create(o["options"]), "name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def passkey_login(client, key: SoftKey, origin=ORIGIN):
    o = (await client.post("/api/auth/passkeys/login/options", headers=HOST)).json()
    assert "allowCredentials" not in o["options"] or not o["options"]["allowCredentials"]
    return await client.post("/api/auth/passkeys/login", headers=HOST,
                             json={"state": o["state"], "credential": key.get(o["options"], origin)})


async def test_passkey_sign_in(client, admin):
    key = SoftKey()
    pk = await add_passkey(client, key)
    assert pk["name"] == "Pixel 7" and pk["rp_id"] == "zirahive.example.ts.net"
    assert [p["name"] for p in (await client.get("/api/auth/passkeys")).json()] == ["Pixel 7"]
    notes = (await client.get("/api/notifications")).json()["items"]
    assert any("passkey" in n["title"] for n in notes)

    client.headers.pop("Authorization")
    client.cookies.clear()
    r = await passkey_login(client, key)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == "mahbub" and r.headers.get("set-cookie")
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert me.status_code == 200

    # a copied or replayed answer doesn't work, nor does another key or another site's answer
    o = (await client.post("/api/auth/passkeys/login/options", headers=HOST)).json()
    answer = key.get(o["options"])
    assert (await client.post("/api/auth/passkeys/login", headers=HOST,
                              json={"state": o["state"], "credential": answer})).status_code == 200
    assert (await client.post("/api/auth/passkeys/login", headers=HOST,
                              json={"state": o["state"], "credential": answer})).status_code == 400
    stranger = SoftKey()
    stranger.user_handle = key.user_handle
    assert (await passkey_login(client, stranger)).status_code == 401
    phished = await passkey_login(client, key, origin="https://zirahive-login.example.com")
    assert phished.status_code == 401


async def test_passkeys_need_a_secure_address_and_can_be_removed(client, admin):
    r = await client.post("/api/auth/passkeys/register/options",
                          headers={"Origin": "http://192.168.0.5:8080", "Host": "192.168.0.5:8080"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "passkey_insecure"
    local = await client.post("/api/auth/passkeys/register/options",
                              headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"})
    assert local.status_code == 200
    other = await client.post("/api/auth/passkeys/register/options",
                              headers={"Origin": "https://evil.example", "Host": "zirahive.example.ts.net"})
    assert other.status_code == 400

    key = SoftKey()
    pk = await add_passkey(client, key)
    assert (await client.delete(f"/api/auth/passkeys/{pk['id']}")).status_code == 204
    client.headers.pop("Authorization")
    client.cookies.clear()
    assert (await passkey_login(client, key)).status_code == 401


# ------------------------------------------------------------ plugins

import hmac  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402

from app.services import plugins  # noqa: E402
from test_batch6 import upload  # noqa: E402

HELLO_PY = '''
import json
from pathlib import Path

async def on_event(event, ctx):
    if event.name == "file.uploaded" and event.data["filename"] == "boom.txt":
        raise RuntimeError("boom")
    out = Path(ctx.settings["log"])
    out.write_text(out.read_text() + json.dumps({"event": event.name, "data": event.data}) + "\\n"
                   if out.exists() else json.dumps({"event": event.name, "data": event.data}) + "\\n")

async def handle(request, ctx):
    return {"hello": ctx.user.username, "path": ctx.path, "greeting": ctx.settings["greeting"]}
'''


def make_plugin(app_data: Path, pid: str, manifest: dict, code: str) -> Path:
    folder = app_data / "plugins" / pid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(json.dumps(manifest))
    (folder / "plugin.py").write_text(code)
    return folder


async def test_plugins_list_turn_on_events_and_pages(client, admin, tmp_path):
    data = tmp_path / "data"
    log = tmp_path / "events.jsonl"
    make_plugin(data, "hello", {"id": "hello", "name": "Hello", "events": ["file.uploaded", "user.created"],
                                "settings": [{"key": "log", "label": "Log file", "default": str(log)},
                                             {"key": "greeting", "label": "Greeting", "default": "nomoskar"},
                                             {"key": "token", "label": "Token", "type": "secret"}]}, HELLO_PY)
    make_plugin(data, "broken", {"id": "wrong-id", "name": "Broken"}, "")
    make_plugin(data, "webhook", {"id": "webhook", "name": "Fake"}, "raise SystemExit")  # can't replace built-ins
    (data / "plugins" / "hello" / "__pycache__").mkdir()

    found = {p["id"]: p for p in (await client.get("/api/admin/plugins")).json()}
    assert found["webhook"]["builtin"] and found["webhook"]["name"] == "Webhook" and found["telegram"]["builtin"]
    assert not found["hello"]["builtin"] and not found["hello"]["enabled"]
    assert "match the folder name" in found["broken"]["error"]
    assert not log.exists()  # nothing of a plugin's code runs until it's turned on

    # settings: secrets are never sent back; an empty one keeps what was saved
    r = await client.put("/api/admin/plugins/hello", json={"settings": {"greeting": "salaam", "token": "s3cret"}})
    tok = next(s for s in r.json()["settings"] if s["key"] == "token")
    assert tok["value"] is None and tok["has_value"]
    await client.put("/api/admin/plugins/hello", json={"settings": {"token": ""}})
    assert (await client.put("/api/admin/plugins/broken", json={"enabled": True})).status_code == 400

    # off: no events, no pages
    await upload(client, "first.txt", b"one", folder="/Docs")
    await plugins.drain()
    assert not log.exists()
    assert (await client.get("/api/plugins/hello/anything")).status_code == 404

    r = await client.put("/api/admin/plugins/hello", json={"enabled": True})
    assert r.json()["enabled"] and r.json()["has_pages"]
    await upload(client, "second.txt", b"two", folder="/Docs")
    await client.post("/api/users", json={"username": "rina", "password": "password12"})
    await plugins.drain()
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert [e["event"] for e in events] == ["file.uploaded", "user.created"]
    assert events[0]["data"]["filename"] == "second.txt" and events[0]["data"]["owner"] == "mahbub"
    assert events[1]["data"] == {"username": "rina", "by": "mahbub", "is_admin": False}

    page = await client.get("/api/plugins/hello/stats/today")
    assert page.json() == {"hello": "mahbub", "path": "stats/today", "greeting": "salaam"}

    # a plugin's mistake doesn't break uploads; it's shown in Settings
    up = await upload(client, "boom.txt", b"boom", folder="/Docs")
    assert up["filename"] == "boom.txt"
    await plugins.drain()
    hello = next(p for p in (await client.get("/api/admin/plugins")).json() if p["id"] == "hello")
    assert "boom" in hello["last_error"]

    # only admins manage plugins
    client.headers["Authorization"] = "Bearer " + (await client.post(
        "/api/auth/login", json={"username": "rina", "password": "password12"})).json()["token"]
    assert (await client.get("/api/admin/plugins")).status_code == 403
    assert (await client.get("/api/plugins/hello/x")).json()["hello"] == "rina"


async def test_webhook_plugin_signs_what_it_sends(client, admin, monkeypatch):
    sent = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(plugins.Context, "http", lambda self, **kw: httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    await client.put("/api/admin/plugins/webhook", json={"enabled": True, "settings": {
        "url": "http://ha.local/api/webhook/zirahive", "secret": "k3y", "events": "file.uploaded"}})
    r = await client.post("/api/admin/plugins/webhook/test")
    assert r.json() == {"ok": True, "error": None}
    await upload(client, "note.txt", b"hello", folder="/Docs")
    await client.post("/api/users", json={"username": "rina", "password": "password12"})  # not chosen
    await plugins.drain()
    assert [req.headers["x-zirahive-event"] for req in sent] == ["plugin.test", "file.uploaded"]
    req = sent[1]
    expected = "sha256=" + hmac.new(b"k3y", req.content, hashlib.sha256).hexdigest()
    assert req.headers["x-zirahive-signature"] == expected
    assert json.loads(req.content)["data"]["filename"] == "note.txt"

    # a receiver that fails is reported by the test button
    monkeypatch.setattr(plugins.Context, "http", lambda self, **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    r = (await client.post("/api/admin/plugins/webhook/test")).json()
    assert not r["ok"] and "answered 500" in r["error"]


async def test_telegram_messages():
    import importlib.util
    spec = importlib.util.spec_from_file_location("tg", plugins.BUILTIN_DIR / "telegram" / "plugin.py")
    tg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tg)
    s = {"new_media": True, "backups": True, "parties": False}
    added = plugins.Event("media.added", {"library": "Hindi Movies", "count": 7, "titles": list("ABCDEFG")})
    assert tg.message(added, s) == "🎬 7 new in Hindi Movies: A, B, C, D, E and 2 more"
    assert tg.message(plugins.Event("backup.finished", {"status": "ok"}), s) is None
    assert "failed" in tg.message(plugins.Event("backup.finished", {"status": "failed", "message": "disk"}), s)
    assert tg.message(plugins.Event("party.created", {"host": "a", "title": "b"}), s) is None


# ------------------------------------------------------------ linked servers

from app.routers import links as links_router  # noqa: E402
from conftest import make_video  # noqa: E402


async def test_linked_servers(app, client, admin, tmp_path, monkeypatch):
    """This server shares a category with 'another' ZiraHive, which here is itself: the whole
    protocol (code, token, proxying, limits) runs in one process."""
    def in_process(link):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=link.url,
                                 headers={"Authorization": f"ZiraHive-Link {link.token}"})
    monkeypatch.setattr(links_router, "client_for", in_process)

    make_video(tmp_path / "shared" / "Monpura (2009).mp4", seconds=3)
    make_video(tmp_path / "shared" / "Late Night (2020).mp4", seconds=2)
    make_video(tmp_path / "shared" / "Bhai Bhai" / "Bhai Bhai S01E01.mp4", seconds=2)
    make_video(tmp_path / "private" / "Home Video (2021).mp4", seconds=2)
    libs = {}
    for name, kind in (("shared", "mixed"), ("private", "movies")):
        r = await client.post("/api/libraries", json={"name": name.title(), "path": str(tmp_path / name), "kind": kind})
        libs[name] = r.json()["id"]
    await jobs_drain()
    media = {m["title"]: m for m in (await client.get("/api/media")).json()}
    for title in ("Monpura", "Home Video"):
        await client.put(f"/api/media/{media[title]['id']}/rating", json={"age_rating": 7})
    await client.put(f"/api/media/{media['Late Night']['id']}/rating", json={"age_rating": 18})
    series_id = next(t["id"] for t in (await client.get("/api/titles")).json() if t["type"] == "series")
    await client.put(f"/api/series/{series_id}/rating", json={"age_rating": 7})

    # the host makes an invite for the shared category, up to 13+
    r = await client.post("/api/admin/link-guests", json={"name": "Rahim's house", "library_ids": [libs["shared"]],
                                                         "max_age": 13, "url": "http://test"})
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    assert code.startswith("zh1.")
    assert "code" not in (await client.get("/api/admin/link-guests")).json()[0] or \
        (await client.get("/api/admin/link-guests")).json()[0]["code"] is None
    bad = await client.post("/api/admin/link-guests", json={"name": "x", "library_ids": ["nope"], "url": "http://test"})
    assert bad.status_code == 400

    # the other side adds the code
    assert (await client.post("/api/admin/links", json={"code": "hello there, not a code"})).status_code == 400
    r = await client.post("/api/admin/links", json={"code": code})
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["name"] == "ZiraHive" and [lib["name"] for lib in link["libraries"]] == ["Shared"]
    lid = link["id"]

    # only the shared category, and only what suits 13+ (Late Night is 18+)
    titles = (await client.get(f"/api/links/{lid}/titles", params={"library_id": libs["shared"]})).json()
    assert sorted(t["title"] for t in titles) == ["Bhai Bhai", "Monpura"]
    assert (await client.get(f"/api/links/{lid}/titles", params={"library_id": libs["private"]})).status_code == 404
    assert (await client.get(f"/api/links/{lid}/media/{media['Home Video']['id']}")).status_code == 404
    assert (await client.get(f"/api/links/{lid}/media/{media['Late Night']['id']}/stream")).status_code == 404

    film = next(t for t in titles if t["title"] == "Monpura")
    m = (await client.get(f"/api/links/{lid}/media/{film['id']}")).json()
    assert m["base"] == f"/api/links/{lid}/media/{film['id']}" and m["position"] == 0
    part = await client.get(f"{m['base']}/stream", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100 and part.headers["content-range"].startswith("bytes 0-99/")
    assert (await client.get(f"{m['base']}/poster")).status_code == 200
    tracks = (await client.get(f"{m['base']}/tracks")).json()
    assert tracks["audio"]
    pl = await client.get(f"{m['base']}/hls/360p/0/index.m3u8")
    assert pl.status_code == 200 and "seg/0.ts" in pl.text
    seg = await client.get(f"{m['base']}/hls/360p/0/seg/0.ts")
    assert seg.status_code == 200 and seg.content[0] == 0x47
    assert (await client.get(f"{m['base']}/offline")).status_code == 404  # only the listed kinds of file

    show = next(t for t in titles if t["type"] == "series")
    s = (await client.get(f"/api/links/{lid}/series/{show['id']}")).json()
    assert s["seasons"][0]["episodes"][0]["base"].startswith(f"/api/links/{lid}/media/")

    # progress is kept here, per person
    await client.put(f"{m['base']}/progress", json={"position": 1.5, "duration": 3, "title": "Monpura"})
    assert (await client.get(f"/api/links/{lid}/media/{film['id']}")).json()["position"] == 1.5

    # a child here (7+) sees less, even though the link allows 13+
    await client.post("/api/users", json={"username": "nabil", "password": "kidpassword"})
    kid = next(u for u in (await client.get("/api/users")).json() if u["username"] == "nabil")
    await client.patch(f"/api/users/{kid['id']}", json={"max_age": 7})
    tok = (await client.post("/api/auth/login", json={"username": "nabil", "password": "kidpassword"})).json()["token"]
    kid_h = {"Authorization": f"Bearer {tok}"}
    links = (await client.get("/api/links", headers=kid_h)).json()
    assert links[0]["ok"] and links[0]["url"] is None  # not shown to non-admins
    kid_titles = (await client.get(f"/api/links/{lid}/titles", params={"library_id": libs["shared"]}, headers=kid_h)).json()
    assert sorted(t["title"] for t in kid_titles) == ["Bhai Bhai", "Monpura"]
    assert (await client.post("/api/admin/links", json={"code": code}, headers=kid_h)).status_code == 403

    # the fed API answers only link tokens, and not the normal sign-in
    assert (await client.get("/api/fed/info")).status_code == 401
    assert (await client.get("/api/fed/info", headers={"Authorization": "ZiraHive-Link nope"})).status_code == 401

    # removing the invite on the host ends it
    guest_id = (await client.get("/api/admin/link-guests")).json()[0]["id"]
    assert (await client.delete(f"/api/admin/link-guests/{guest_id}")).status_code == 204
    r = await client.get(f"/api/links/{lid}/titles", params={"library_id": libs["shared"]})
    assert r.status_code == 502 and "removed" in r.json()["detail"]
    assert (await client.get("/api/links")).json()[0]["ok"] is False


async def test_public_gateway_reaches_only_share_links_and_fed(client, admin):
    pub = {"X-ZiraHive-Gateway": "public"}
    assert (await client.get("/api/auth/me", headers=pub)).status_code == 404
    assert (await client.get("/api/fed/info", headers=pub)).status_code == 401  # reached, but needs a link token


async def jobs_drain():
    from app.services import jobs
    await jobs.drain_local()


# ------------------------------------------------------------ renamed from GharBox

def test_old_setting_names_still_work(monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.delenv("ZIRAHIVE_LAN_URL", raising=False)
    monkeypatch.setenv("GHARBOX_LAN_URL", "http://192.168.0.9:8080")
    get_settings.cache_clear()
    try:
        assert get_settings().lan_url == "http://192.168.0.9:8080"
    finally:
        import os
        os.environ.pop("ZIRAHIVE_LAN_URL", None)  # copied there by the old-name support, not by monkeypatch
        get_settings.cache_clear()


async def test_old_sign_in_cookie_and_data_marker(client, admin, tmp_path):
    from app.services.browse import marked

    client.headers.pop("Authorization")
    client.cookies.clear()
    client.cookies.set("gharbox_token", admin)
    assert (await client.get("/api/auth/me")).status_code == 200
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / ".gharbox-data").write_text("")
    assert marked(tmp_path / "old") and not marked(tmp_path)


async def test_a_removed_link_doesnt_block_the_others(client, admin, tmp_path):
    lib = (await client.post("/api/libraries", json={"name": "Films", "path": str(tmp_path), "kind": "movies"})).json()
    good = (await client.post("/api/admin/link-guests", json={"name": "a", "library_ids": [lib["id"]], "url": "http://test"})).json()
    from app.routers.federation import read_code
    _, token = read_code(good["code"])
    for _ in range(40):  # a server keeps asking with a removed link's token
        assert (await client.get("/api/fed/info", headers={"Authorization": "ZiraHive-Link removed-token-xxxxxxxxxx"})).status_code in (401, 429)
    assert (await client.get("/api/fed/info", headers={"Authorization": f"ZiraHive-Link {token}"})).status_code == 200
