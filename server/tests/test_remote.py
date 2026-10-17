"""Remote-access hardening: public gateway, cookies, URL tokens, throttles, security check."""
from __future__ import annotations

from app.services import jobs
from conftest import make_video
from test_api import upload

GATEWAY = {"X-ZiraHive-Gateway": "public"}


async def test_public_gateway_only_reaches_share_links(client, admin):
    asset = (await upload(client, b"hello", "hi.txt"))["asset"]
    share = (await client.post("/api/shares", json={"target_type": "asset", "target_id": asset["id"]})).json()
    token = client.headers["Authorization"]
    # even with a valid sign-in token, the public gateway can't reach the app
    for path in ("/api/auth/me", "/api/files", f"/api/assets/{asset['id']}/file", "/api/health",
                 "/api/setup/status", "/api/users", "/docs"):
        r = await client.get(path, headers={**GATEWAY, "Authorization": token})
        assert r.status_code == 404, path
    r = await client.post("/api/auth/login", json={"username": "mahbub", "password": "supersecret"}, headers=GATEWAY)
    assert r.status_code == 404
    # share links work through it
    assert (await client.get(f"/api/s/{share['token']}", headers=GATEWAY)).status_code == 200
    r = await client.get(f"/api/s/{share['token']}/assets/{asset['id']}/file", headers=GATEWAY)
    assert r.content == b"hello"


async def test_api_docs_off_by_default(client, admin):
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404


async def test_token_in_url_only_for_streams(client, admin, tmp_path):
    asset = (await upload(client, b"secret", "s.txt"))["asset"]
    token = client.headers.pop("Authorization").split()[1]
    client.cookies.clear()
    assert (await client.get(f"/api/assets/{asset['id']}/file", params={"token": token})).status_code == 401
    assert (await client.get("/api/auth/me", params={"token": token})).status_code == 401
    client.headers["Authorization"] = f"Bearer {token}"
    make_video(tmp_path / "m" / "Clip (2020).mp4")
    await client.post("/api/libraries", json={"name": "M", "path": str(tmp_path / "m")})
    await jobs.drain_local()
    mid = (await client.get("/api/media")).json()[0]["id"]
    link = (await client.get(f"/api/media/{mid}/link")).json()["path"]
    client.headers.pop("Authorization")
    r = await client.get(link, headers={"Range": "bytes=0-9"})
    assert r.status_code == 206


async def test_cookie_secure_over_https(client):
    r = await client.post("/api/setup", json={"username": "mahbub", "password": "supersecret"})
    assert "secure" not in r.headers["set-cookie"].lower()  # plain http on the home network
    r = await client.post("/api/auth/login", json={"username": "mahbub", "password": "supersecret"},
                          headers={"Host": "zirahive.tail1234.ts.net"})
    assert "secure" in r.headers["set-cookie"].lower()


async def test_password_guessing_across_usernames_is_limited(client, admin):
    for i in range(30):
        await client.post("/api/auth/login", json={"username": f"guess{i}", "password": "x"})
    r = await client.post("/api/auth/login", json={"username": "mahbub", "password": "supersecret"})
    assert r.status_code == 429


async def test_security_check(client, admin, monkeypatch):
    checks = {c["title"]: c for c in (await client.get("/api/admin/security")).json()}
    assert not checks["Every admin uses two-factor sign-in"]["ok"]
    assert "mahbub" in checks["Every admin uses two-factor sign-in"]["fix"]
    assert checks["The developer API page is off"]["ok"]
    assert checks["Share links can be opened outside your home"]["level"] == "info"
    cfg = (await client.get("/api/config")).json()
    assert cfg["public_url"] == ""
