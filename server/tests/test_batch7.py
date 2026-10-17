"""Batch 7: passkeys, voice chat signalling, plugins, linked servers."""
from __future__ import annotations

import base64
import hashlib
import json
import os

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

ORIGIN = "https://gharbox.example.ts.net"
HOST = {"Origin": ORIGIN, "Host": "gharbox.example.ts.net"}


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftKey:
    """A passkey the way a phone keeps it: an EC key pair, a credential id, a counter."""

    def __init__(self, rp_id: str = "gharbox.example.ts.net"):
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
    assert o["options"]["rp"]["id"] == "gharbox.example.ts.net"
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
    assert pk["name"] == "Pixel 7" and pk["rp_id"] == "gharbox.example.ts.net"
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
    phished = await passkey_login(client, key, origin="https://gharbox-login.example.com")
    assert phished.status_code == 401


async def test_passkeys_need_a_secure_address_and_can_be_removed(client, admin):
    r = await client.post("/api/auth/passkeys/register/options",
                          headers={"Origin": "http://192.168.0.5:8080", "Host": "192.168.0.5:8080"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "passkey_insecure"
    local = await client.post("/api/auth/passkeys/register/options",
                              headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"})
    assert local.status_code == 200
    other = await client.post("/api/auth/passkeys/register/options",
                              headers={"Origin": "https://evil.example", "Host": "gharbox.example.ts.net"})
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
        "url": "http://ha.local/api/webhook/gharbox", "secret": "k3y", "events": "file.uploaded"}})
    r = await client.post("/api/admin/plugins/webhook/test")
    assert r.json() == {"ok": True, "error": None}
    await upload(client, "note.txt", b"hello", folder="/Docs")
    await client.post("/api/users", json={"username": "rina", "password": "password12"})  # not chosen
    await plugins.drain()
    assert [req.headers["x-gharbox-event"] for req in sent] == ["plugin.test", "file.uploaded"]
    req = sent[1]
    expected = "sha256=" + hmac.new(b"k3y", req.content, hashlib.sha256).hexdigest()
    assert req.headers["x-gharbox-signature"] == expected
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
