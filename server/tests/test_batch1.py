"""Sharing, versions, albums, memories, 2FA, roles, audit, notifications, admin activity."""
from __future__ import annotations

import pyotp

from app.services import jobs
from conftest import jpeg_bytes, make_video
from test_api import upload


async def login(client, username, password, code=None):
    body = {"username": username, "password": password}
    if code:
        body["code"] = code
    return await client.post("/api/auth/login", json=body)


async def as_user(client, username="rina", password="password12"):
    """Create a family member and return headers for them."""
    await client.post("/api/users", json={"username": username, "password": password})
    token = (await login(client, username, password)).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------- versions

async def test_document_versions_and_restore(client, admin):
    v1 = (await upload(client, b"draft one", "Budget.xlsx", folder="/Docs"))["asset"]
    v2 = (await upload(client, b"draft two", "Budget.xlsx", folder="/Docs"))["asset"]
    v3 = (await upload(client, b"draft three", "Budget.xlsx", folder="/Docs"))["asset"]
    assert v1["id"] == v2["id"] == v3["id"]  # same file, new versions
    listing = (await client.get("/api/files", params={"folder": "/Docs"})).json()["assets"]
    assert [a["filename"] for a in listing] == ["Budget.xlsx"]
    assert (await client.get(f"/api/assets/{v1['id']}/file")).content == b"draft three"
    versions = (await client.get(f"/api/assets/{v1['id']}/versions")).json()
    assert len(versions) == 2
    oldest = versions[-1]
    old = await client.get(f"/api/assets/{v1['id']}/versions/{oldest['id']}/file")
    assert old.content == b"draft one"
    r = await client.post(f"/api/assets/{v1['id']}/versions/{oldest['id']}/restore")
    assert r.status_code == 200
    assert (await client.get(f"/api/assets/{v1['id']}/file")).content == b"draft one"
    contents = set()
    for v in (await client.get(f"/api/assets/{v1['id']}/versions")).json():
        contents.add((await client.get(f"/api/assets/{v1['id']}/versions/{v['id']}/file")).content)
    assert contents == {b"draft two", b"draft three"}
    # versions count towards storage used
    me = (await client.get("/api/auth/me")).json()
    assert me["used_bytes"] == len(b"draft one") + len(b"draft two") + len(b"draft three")
    # deleting forever removes every version
    await client.delete(f"/api/assets/{v1['id']}")
    await client.delete(f"/api/trash/{v1['id']}")
    assert (await client.get("/api/auth/me")).json()["used_bytes"] == 0


# ----------------------------------------------------- previews & memories

async def test_preview_and_on_this_day(client, admin):
    big = jpeg_bytes(size=(3000, 2000), taken="2021:03:15 10:00:00")
    a = (await upload(client, big, "big.jpg"))["asset"]
    await upload(client, jpeg_bytes((5, 5, 5), taken="2023:03:15 12:00:00"), "b.jpg")
    await upload(client, jpeg_bytes((6, 6, 6), taken="2023:03:16 12:00:00"), "c.jpg")
    await jobs.drain_local()
    r = await client.get(f"/api/assets/{a['id']}/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert len(r.content) < len(big)
    memories = (await client.get("/api/photos/on-this-day", params={"day": "2026-03-15"})).json()
    assert [(m["year"], m["years_ago"], len(m["items"])) for m in memories] == [(2023, 3, 1), (2021, 5, 1)]


# -------------------------------------------------------------- share links

async def test_share_single_file_with_password_and_expiry(client, admin):
    asset = (await upload(client, b"secret plan", "plan.pdf"))["asset"]
    other = (await upload(client, b"not shared", "other.pdf"))["asset"]
    share = (await client.post("/api/shares", json={"target_type": "asset", "target_id": asset["id"],
                                                    "password": "open sesame", "expires_days": 7})).json()
    token = share["token"]
    anon = {"Authorization": ""}
    client.cookies.clear()
    info = (await client.get(f"/api/s/{token}", headers=anon)).json()
    assert info["needs_password"] and info["title"] == "plan.pdf" and info["owner"] == "mahbub"
    assert (await client.get(f"/api/s/{token}/items", headers=anon)).status_code == 401
    assert (await client.post(f"/api/s/{token}/unlock", json={"password": "nope"}, headers=anon)).status_code == 401
    key = (await client.post(f"/api/s/{token}/unlock", json={"password": "open sesame"}, headers=anon)).json()["key"]
    items = (await client.get(f"/api/s/{token}/items", params={"key": key}, headers=anon)).json()
    assert [a["filename"] for a in items["assets"]] == ["plan.pdf"]
    r = await client.get(f"/api/s/{token}/assets/{asset['id']}/file", params={"key": key}, headers=anon)
    assert r.content == b"secret plan"
    # the link can't be used to reach other files, and the key only opens this link
    r = await client.get(f"/api/s/{token}/assets/{other['id']}/file", params={"key": key}, headers=anon)
    assert r.status_code == 404
    second = (await client.post("/api/shares", json={"target_type": "asset", "target_id": other["id"],
                                                     "password": "x"})).json()
    assert (await client.get(f"/api/s/{second['token']}/items", params={"key": key}, headers=anon)).status_code == 401
    assert [s["label"] for s in (await client.get("/api/shares")).json()] == ["other.pdf", "plan.pdf"]
    # revoke
    await client.delete(f"/api/shares/{share['id']}")
    assert (await client.get(f"/api/s/{token}", headers=anon)).status_code == 404


async def test_share_folder_and_view_only(client, admin):
    await upload(client, jpeg_bytes(size=(2400, 1600)), "trip1.jpg", folder="/Trips/Sylhet")
    await upload(client, b"itinerary", "plan.txt", folder="/Trips/Sylhet/Notes")
    await upload(client, b"private", "salary.pdf", folder="/Private")
    await jobs.drain_local()
    share = (await client.post("/api/shares", json={"target_type": "folder", "target_id": "/Trips",
                                                    "allow_download": False})).json()
    t = share["token"]
    root = (await client.get(f"/api/s/{t}/items")).json()
    assert root["folders"] == ["/Sylhet"] and root["assets"] == []
    sub = (await client.get(f"/api/s/{t}/items", params={"path": "/Sylhet"})).json()
    photo = sub["assets"][0]
    assert sub["folders"] == ["/Sylhet/Notes"] and photo["filename"] == "trip1.jpg"
    # view-only: no downloads, photos come back as a preview instead of the original
    assert (await client.get(f"/api/s/{t}/assets/{photo['id']}/file", params={"download": True})).status_code == 403
    inline = await client.get(f"/api/s/{t}/assets/{photo['id']}/file")
    assert inline.headers["content-type"] == "image/webp"
    assert (await client.get(f"/api/s/{t}/items", params={"path": "/../Private"})).status_code == 400
    private = (await client.get("/api/files", params={"folder": "/Private"})).json()["assets"][0]
    assert (await client.get(f"/api/s/{t}/assets/{private['id']}/file")).status_code == 404


async def test_expired_link(client, admin):
    from app.db import sessionmaker
    from app.models import ShareLink
    from datetime import datetime, timedelta, timezone
    asset = (await upload(client, b"old", "old.txt"))["asset"]
    share = (await client.post("/api/shares", json={"target_type": "asset", "target_id": asset["id"],
                                                    "expires_days": 1})).json()
    async with sessionmaker()() as s:
        link = await s.get(ShareLink, share["id"])
        link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await s.commit()
    assert (await client.get(f"/api/s/{share['token']}")).status_code == 404


# ------------------------------------------------------------------ albums

async def test_shared_album_between_family_members(client, admin):
    mine = (await upload(client, jpeg_bytes((10, 20, 30)), "eid1.jpg"))["asset"]
    private = (await upload(client, jpeg_bytes((40, 50, 60)), "private.jpg"))["asset"]
    rina = await as_user(client)
    rina_id = (await client.get("/api/auth/me", headers=rina)).json()["id"]
    album = (await client.post("/api/albums", json={"title": "Eid 2026", "asset_ids": [mine["id"]]})).json()
    # not shared yet: Rina can't see it or its photos
    assert (await client.get(f"/api/albums/{album['id']}", headers=rina)).status_code == 404
    assert (await client.get(f"/api/assets/{mine['id']}/file", headers=rina)).status_code == 404
    await client.put(f"/api/albums/{album['id']}/members", json={"members": [{"user_id": rina_id, "can_add": True}]})
    seen = (await client.get(f"/api/albums/{album['id']}", headers=rina)).json()
    assert [i["filename"] for i in seen["items"]] == ["eid1.jpg"] and not seen["is_owner"]
    assert (await client.get(f"/api/assets/{mine['id']}/file", headers=rina)).status_code == 200
    assert (await client.get(f"/api/assets/{private['id']}/file", headers=rina)).status_code == 404
    # Rina got a notification, and can add her own photo but not someone else's
    notes = (await client.get("/api/notifications", headers=rina)).json()
    assert notes["unread"] == 1 and "Eid 2026" in notes["items"][0]["title"]
    hers = (await upload_as(client, rina, jpeg_bytes((70, 80, 90)), "rina.jpg"))["asset"]
    r = await client.post(f"/api/albums/{album['id']}/items", json={"asset_ids": [private["id"]]}, headers=rina)
    assert r.status_code == 400
    r = await client.post(f"/api/albums/{album['id']}/items", json={"asset_ids": [hers["id"]]}, headers=rina)
    assert r.json()["item_count"] == 2
    # the owner now sees Rina's photo through the album
    assert (await client.get(f"/api/assets/{hers['id']}/file")).status_code == 200
    # she can't rename or delete the owner's album
    assert (await client.patch(f"/api/albums/{album['id']}", json={"title": "x"}, headers=rina)).status_code == 403
    assert len((await client.get("/api/albums", headers=rina)).json()) == 1
    # owner removes her: access is gone again
    await client.put(f"/api/albums/{album['id']}/members", json={"members": []})
    assert (await client.get(f"/api/assets/{mine['id']}/file", headers=rina)).status_code == 404


async def upload_as(client, headers, data, name):
    saved = client.headers.get("Authorization")
    client.headers["Authorization"] = headers["Authorization"]
    try:
        return await upload(client, data, name)
    finally:
        client.headers["Authorization"] = saved


async def test_public_album_link(client, admin):
    a = (await upload(client, jpeg_bytes((1, 1, 1)), "a.jpg"))["asset"]
    b = (await upload(client, jpeg_bytes((2, 2, 2)), "b.jpg"))["asset"]
    album = (await client.post("/api/albums", json={"title": "Wedding", "asset_ids": [a["id"]]})).json()
    share = (await client.post("/api/shares", json={"target_type": "album", "target_id": album["id"]})).json()
    items = (await client.get(f"/api/s/{share['token']}/items")).json()["assets"]
    assert [i["id"] for i in items] == [a["id"]]
    assert (await client.get(f"/api/s/{share['token']}/assets/{b['id']}/file")).status_code == 404


# ------------------------------------------------------------- two-factor

async def test_two_factor_login_and_recovery_codes(client, admin):
    setup = (await client.post("/api/auth/2fa/setup")).json()
    assert setup["uri"].startswith("otpauth://totp/ZiraHive:mahbub") and "<svg" in setup["qr_svg"]
    assert (await client.post("/api/auth/2fa/enable", json={"code": "000000"})).status_code == 400
    totp = pyotp.TOTP(setup["secret"])
    codes = (await client.post("/api/auth/2fa/enable", json={"code": totp.now()})).json()["recovery_codes"]
    assert len(codes) == 10
    r = await login(client, "mahbub", "supersecret")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "2fa_required"
    assert (await login(client, "mahbub", "supersecret", "123456")).status_code == 401
    assert (await login(client, "mahbub", "supersecret", totp.now())).status_code == 200
    # a recovery code works once
    assert (await login(client, "mahbub", "supersecret", codes[0])).status_code == 200
    assert (await login(client, "mahbub", "supersecret", codes[0])).status_code == 401
    # turning it off needs the password
    assert (await client.post("/api/auth/2fa/disable", json={"password": "wrong"})).status_code == 400
    assert (await client.post("/api/auth/2fa/disable", json={"password": "supersecret"})).status_code == 204
    assert (await login(client, "mahbub", "supersecret")).status_code == 200


async def test_admin_can_reset_lost_2fa(client, admin):
    rina = await as_user(client)
    setup = (await client.post("/api/auth/2fa/setup", headers=rina)).json()
    await client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(setup["secret"]).now()}, headers=rina)
    rina_id = (await client.get("/api/auth/me", headers=rina)).json()["id"]
    await client.patch(f"/api/users/{rina_id}", json={"reset_2fa": True})
    assert (await login(client, "rina", "password12")).status_code == 200


# ------------------------------------------------------ sessions and roles

async def test_password_change_signs_out_other_devices(client, admin):
    phone = (await login(client, "mahbub", "supersecret")).json()["token"]
    r = await client.post("/api/auth/password", json={"current_password": "supersecret",
                                                       "new_password": "evenmoresecret"})
    client.headers["Authorization"] = f"Bearer {r.json()['token']}"
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.get("/api/auth/me", headers={"Authorization": f"Bearer {phone}"})).status_code == 401


async def test_logout_everywhere(client, admin):
    await client.post("/api/auth/logout-all")
    client.cookies.clear()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_roles_and_quota(client, admin):
    rina = await as_user(client)
    rina_id = (await client.get("/api/auth/me", headers=rina)).json()["id"]
    r = await client.patch(f"/api/users/{rina_id}", json={"quota_gb": 0.000001})  # ~1 KB
    assert r.json()["quota_bytes"] == 1073
    r = await client.post("/api/uploads", json={"filename": "big.bin", "size": 5000}, headers=rina)
    assert r.status_code == 507
    await client.patch(f"/api/users/{rina_id}", json={"clear_quota": True, "is_admin": True})
    assert (await client.get("/api/users", headers=rina)).status_code == 200
    me_id = (await client.get("/api/auth/me")).json()["id"]
    assert (await client.patch(f"/api/users/{me_id}", json={"is_admin": False})).status_code == 400
    # admin resets her password
    await client.patch(f"/api/users/{rina_id}", json={"new_password": "brandnew123"})
    assert (await login(client, "rina", "brandnew123")).status_code == 200
    assert (await client.get("/api/auth/me", headers=rina)).status_code == 401  # old session ended


async def test_login_throttle(client, admin):
    for _ in range(10):
        await login(client, "mahbub", "wrong")
    assert (await login(client, "mahbub", "supersecret")).status_code == 429


# ------------------------------------------------- audit, notifications, admin

async def test_audit_log(client, admin):
    await login(client, "mahbub", "wrong")
    await client.post("/api/users", json={"username": "rina", "password": "password12"})
    actions = [e["action"] for e in (await client.get("/api/admin/audit")).json()]
    assert actions[:3] == ["user_created", "login_failed", "setup"]


async def test_notifications(client, admin, tmp_path):
    await client.put("/api/auth/me/settings", json={"ntfy_url": "http://127.0.0.1:9/never"})  # push fails quietly
    await client.post("/api/events/backup", json={"uploaded": 12, "skipped": 30, "failed": 1, "device": "iPhone"})
    movies = tmp_path / "m"
    make_video(movies / "Clip (2020).mp4")
    await client.post("/api/libraries", json={"name": "Movies", "path": str(movies)})
    await jobs.drain_local()
    n = (await client.get("/api/notifications")).json()
    titles = [i["title"] for i in n["items"]]
    assert "1 new video in Movies" in titles
    assert "Upload needs attention: 1 file failed from iPhone" in titles
    assert n["unread"] == 2
    await client.post("/api/notifications/read")
    assert (await client.get("/api/notifications")).json()["unread"] == 0


async def test_admin_activity_shows_streams(client, admin, tmp_path):
    movies = tmp_path / "m"
    make_video(movies / "Clip (2020).mp4")
    await client.post("/api/libraries", json={"name": "Movies", "path": str(movies)})
    await jobs.drain_local()
    mid = (await client.get("/api/media")).json()[0]["id"]
    await client.get(f"/api/media/{mid}/stream", headers={"Range": "bytes=0-99"})
    act = (await client.get("/api/admin/activity")).json()
    assert [(s["username"], s["title"]) for s in act["streams"]] == [("mahbub", "Clip")]
    assert act["disks"] and act["disks"][0]["label"] == "Backups and app data"
    rina = await as_user(client)
    assert (await client.get("/api/admin/activity", headers=rina)).status_code == 403


# ------------------------------------------------------------ copies vs dedupe

async def test_files_keep_copies_but_backup_skips_duplicates(client, admin):
    data = b"same contract"
    a = await upload(client, data, "contract.pdf", folder="/Work")
    b = await upload(client, data, "contract.pdf", folder="/Archive", dedupe=False)
    assert b["status"] == "complete" and b["asset"]["id"] != a["asset"]["id"]
    assert len((await client.get("/api/files", params={"folder": "/Archive"})).json()["assets"]) == 1
    # camera-roll style upload (default) still recognises it
    c = await upload(client, data, "IMG_9999.pdf", folder="/Camera")
    assert c["status"] == "exists"
    # deleting one copy leaves the other
    await client.delete(f"/api/assets/{a['asset']['id']}")
    await client.delete(f"/api/trash/{a['asset']['id']}")
    assert (await client.get(f"/api/assets/{b['asset']['id']}/file")).content == data


async def test_unique_hash_rule_is_migrated_away(tmp_path, monkeypatch):
    """A v0.1 SQLite database (one copy per hash) keeps its rows and foreign keys."""
    import sqlite3
    data = tmp_path / "data"
    data.mkdir()
    db = sqlite3.connect(data / "zirahive.db")
    db.executescript("""
        CREATE TABLE users (id VARCHAR(32) PRIMARY KEY, username VARCHAR(64), password_hash VARCHAR(255),
            is_admin BOOLEAN, quota_bytes BIGINT, created_at DATETIME);
        INSERT INTO users VALUES ('u1', 'mahbub', 'x', 1, NULL, '2026-10-16');
        CREATE TABLE assets (id VARCHAR(32) PRIMARY KEY, owner_id VARCHAR(32) REFERENCES users(id) ON DELETE CASCADE,
            folder VARCHAR(1024), filename VARCHAR(512), size BIGINT, mime VARCHAR(128), kind VARCHAR(16),
            sha256 VARCHAR(64), storage_path TEXT, thumb_ready BOOLEAN, width INTEGER, height INTEGER,
            duration FLOAT, taken_at DATETIME, device_asset_id VARCHAR(255), deleted_at DATETIME,
            created_at DATETIME, UNIQUE (owner_id, sha256));
        CREATE INDEX ix_assets_owner_folder ON assets (owner_id, folder);
        INSERT INTO assets VALUES ('a1','u1','/','x.txt',1,'text/plain','document','abc','mahbub/x.txt',0,
            NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-16');
    """)
    db.commit()
    db.close()
    monkeypatch.setenv("ZIRAHIVE_DATA_DIR", str(data))
    monkeypatch.setenv("ZIRAHIVE_DATABASE_URL", "")
    from app.config import get_settings
    get_settings.cache_clear()
    from app import db as appdb
    appdb.init_engine(get_settings().db_url)
    await appdb.create_all()
    await appdb.dispose()
    db = sqlite3.connect(data / "zirahive.db")
    sql = db.execute("SELECT sql FROM sqlite_master WHERE name='assets'").fetchone()[0]
    assert "UNIQUE (owner_id, sha256)" not in sql
    assert db.execute("SELECT filename FROM assets").fetchall() == [("x.txt",)]
    fk_targets = {r[2] for t in ("album_items", "asset_versions", "albums")
                  for r in db.execute(f"PRAGMA foreign_key_list({t})")}
    assert "assets_v1" not in fk_targets and "assets" in fk_targets
    db.execute("INSERT INTO assets (id, owner_id, folder, filename, size, mime, kind, sha256, storage_path, "
               "thumb_ready, created_at) VALUES ('a2','u1','/b','x.txt',1,'t','document','abc','p',0,'2026-10-16')")
    get_settings.cache_clear()


async def test_backup_report_success_and_quiet_runs(client, admin):
    await client.post("/api/events/backup", json={"uploaded": 0, "skipped": 50, "failed": 0})  # nothing new: silent
    await client.post("/api/events/backup", json={"uploaded": 8, "skipped": 2, "failed": 0, "device": "Android phone"})
    titles = [i["title"] for i in (await client.get("/api/notifications")).json()["items"]]
    assert titles == ["Backed up 8 photos and videos from Android phone"]
