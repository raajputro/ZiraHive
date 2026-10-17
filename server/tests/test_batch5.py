"""Batch 5: vault, offsite backup, language, sync change feed."""
from __future__ import annotations

import base64
import os

B = lambda n: base64.b64encode(os.urandom(n)).decode()  # noqa: E731


async def _login(client, username, password):
    token = (await client.post("/api/auth/login", json={"username": username, "password": password})).json()["token"]
    return {"Authorization": f"Bearer {token}"}


async def test_language_setting(client, admin):
    me = (await client.get("/api/auth/me")).json()
    assert me["language"] is None
    r = await client.put("/api/auth/me/settings", json={"language": "bn"})
    assert r.json()["language"] == "bn"
    await client.put("/api/auth/me/settings", json={"ntfy_url": "https://ntfy.sh/x-test"})  # leaves language alone
    me = (await client.get("/api/auth/me")).json()
    assert (me["language"], me["ntfy_url"]) == ("bn", "https://ntfy.sh/x-test")
    assert (await client.put("/api/auth/me/settings", json={"language": "fr"})).status_code == 422


async def test_vault_keeps_only_ciphertext_and_is_private(client, admin):
    assert (await client.get("/api/vault")).json() == {"set_up": False, "kdf": None, "salt": None, "iterations": None,
                                                     "wrapped_key": None, "recovery_wrapped_key": None,
                                                     "item_count": 0, "bytes": 0}
    assert (await client.post("/api/vault/items", json={"size": 100, "chunk_size": 65536, "wrapped_key": B(60),
                                                        "meta": B(40)})).status_code == 409
    keys = {"salt": B(16), "iterations": 600000, "wrapped_key": B(60), "recovery_wrapped_key": B(60)}
    v = (await client.post("/api/vault", json=keys)).json()
    assert v["set_up"] and v["wrapped_key"] == keys["wrapped_key"] and v["iterations"] == 600000
    assert (await client.post("/api/vault", json=keys)).status_code == 409

    blob = os.urandom(150_000)
    item = (await client.post("/api/vault/items", json={"size": len(blob), "chunk_size": 65536,
                                                        "wrapped_key": B(60), "meta": B(80)})).json()
    assert item["complete"] is False
    # resumable: two pieces, a wrong offset is refused with the right one
    r = await client.patch(f"/api/vault/items/{item['id']}/data", content=blob[:100_000], headers={"Upload-Offset": "0"})
    assert r.json()["received"] == 100_000
    r = await client.patch(f"/api/vault/items/{item['id']}/data", content=blob[100_000:], headers={"Upload-Offset": "5"})
    assert r.status_code == 409 and r.headers["Upload-Offset"] == "100000"
    head = await client.head(f"/api/vault/items/{item['id']}/data")
    assert head.headers["Upload-Offset"] == "100000"
    r = await client.patch(f"/api/vault/items/{item['id']}/data", content=blob[100_000:], headers={"Upload-Offset": "100000"})
    assert r.json()["complete"] is True
    assert (await client.patch(f"/api/vault/items/{item['id']}/data", content=b"x",
                               headers={"Upload-Offset": str(len(blob))})).status_code == 409

    got = await client.get(f"/api/vault/items/{item['id']}/data")
    assert got.content == blob and got.headers["content-type"] == "application/octet-stream"
    part = await client.get(f"/api/vault/items/{item['id']}/data", headers={"Range": "bytes=65552-131103"})
    assert part.status_code == 206 and part.content == blob[65552:131104]
    assert (await client.put(f"/api/vault/items/{item['id']}/thumb", content=os.urandom(2000))).status_code == 204
    assert len((await client.get(f"/api/vault/items/{item['id']}/thumb")).content) == 2000
    listed = (await client.get("/api/vault/items")).json()
    assert [i["id"] for i in listed] == [item["id"]] and listed[0]["has_thumb"]
    assert (await client.get("/api/vault")).json()["bytes"] == len(blob)
    assert (await client.get("/api/auth/me")).json()["used_bytes"] >= len(blob)  # counts toward the quota

    # another person, even an admin's family member, sees nothing of it
    await client.post("/api/users", json={"username": "rina", "password": "rinapassword"})
    other = await _login(client, "rina", "rinapassword")
    assert (await client.get("/api/vault", headers=other)).json()["set_up"] is False
    assert (await client.get(f"/api/vault/items/{item['id']}/data", headers=other)).status_code == 404
    assert (await client.delete(f"/api/vault/items/{item['id']}", headers=other)).status_code == 404

    # a new passphrase needs the account password
    new = {"salt": B(16), "iterations": 700000, "wrapped_key": B(60)}
    assert (await client.put("/api/vault/keys", json={**new, "password": "wrong"})).status_code == 403
    v = (await client.put("/api/vault/keys", json={**new, "password": "supersecret"})).json()
    assert v["wrapped_key"] == new["wrapped_key"] and v["recovery_wrapped_key"] == keys["recovery_wrapped_key"]

    # rename (new encrypted name), delete
    meta = B(90)
    assert (await client.patch(f"/api/vault/items/{item['id']}", json={"meta": meta})).json()["meta"] == meta
    assert (await client.delete(f"/api/vault/items/{item['id']}")).status_code == 204
    assert (await client.get("/api/vault/items")).json() == []

    # forgot everything: emptying needs the password
    assert (await client.request("DELETE", "/api/vault", json={"password": "nope"})).status_code == 403
    assert (await client.request("DELETE", "/api/vault", json={"password": "supersecret"})).status_code == 204
    assert (await client.get("/api/vault")).json()["set_up"] is False
    log = (await client.get("/api/admin/audit")).json()
    assert {"vault_created", "vault_keys_changed", "vault_reset"} <= {e["action"] for e in log}


# ------------------------------------------------------------------ offsite backup

import shutil  # noqa: E402

import pytest  # noqa: E402

from app.services import jobs  # noqa: E402

needs_restic = pytest.mark.skipif(not shutil.which("restic"), reason="restic not installed")


@needs_restic
async def test_offsite_backup_to_a_disk(client, admin, tmp_path):
    from app.config import get_settings

    assert (await client.get("/api/admin/backup")).json()["configured"] is False
    assert (await client.put("/api/admin/backup", json={"repository": "ftp://nope"})).status_code == 422
    assert (await client.put("/api/admin/backup", json={"repository": "/x", "env": {"EVIL": "1"}})).status_code == 422

    # something worth keeping: a document and a vault file
    up = (await client.post("/api/uploads", json={"filename": "will.txt", "size": 11, "folder": "/Papers"})).json()
    await client.patch(f"/api/uploads/{up['id']}", content=b"my will: ok", headers={"Upload-Offset": "0"})

    repo = tmp_path / "usb" / "zirahive"
    r = await client.put("/api/admin/backup", json={"repository": str(repo), "hour": 20})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created"] is True and len(out["password"]) >= 30 and out["restic"].startswith("restic")
    assert (repo / "config").is_file()
    assert (await client.get("/api/admin/backup")).json()["password"] is None  # shown once...
    assert len((await client.get("/api/admin/backup/password")).json()["password"]) >= 30  # ...and on request

    assert (await client.post("/api/admin/backup/run")).status_code == 202
    await jobs.drain_local()
    runs = (await client.get("/api/admin/backup")).json()["runs"]
    assert runs[0]["status"] == "ok", runs[0]["message"]
    assert runs[0]["snapshot_id"] and runs[0]["files_new"] >= 2

    # the repository is encrypted: the document's text isn't in it anywhere
    for f in repo.rglob("*"):
        if f.is_file():
            assert b"my will: ok" not in f.read_bytes()

    snaps = (await client.get("/api/admin/backup/snapshots")).json()
    assert len(snaps) == 1 and str(get_settings().data_dir) in snaps[0]["paths"][0]

    # it really restores: the file and a readable database copy come back
    from app.models import BackupConfig
    from app.db import sessionmaker
    from app.services import offsite
    async with sessionmaker()() as session:
        cfg = await session.get(BackupConfig, "main")
        target = tmp_path / "restored"
        rc, _, err = await offsite.restic(cfg, "restore", "latest", "--target", str(target))
        assert rc == 0, err
    restored = list(target.rglob("will.txt"))
    assert restored and restored[0].read_bytes() == b"my will: ok"
    # the database copy: SQLite's file, or a pg_dump when running on PostgreSQL
    assert list(target.rglob("backup-staging/zirahive.db")) or list(target.rglob("backup-staging/zirahive.pgdump"))
    assert not list(target.rglob("cache/thumbs"))  # caches are left out

    assert (await client.post("/api/admin/backup/check")).status_code == 202
    await jobs.drain_local()
    runs = (await client.get("/api/admin/backup")).json()["runs"]
    assert runs[0]["kind"] == "check" and runs[0]["status"] == "ok"

    # same place, wrong password: refused clearly
    r = await client.put("/api/admin/backup", json={"repository": str(repo), "password": "a-totally-different-password"})
    assert r.status_code == 400 and "different password" in r.json()["detail"]


@needs_restic
async def test_backup_schedule_and_failure_notice(client, admin, tmp_path):
    from datetime import datetime, timezone

    from app.db import sessionmaker
    from app.services import offsite

    async with sessionmaker()() as session:
        assert await offsite.due(session) is False  # not set up
    await client.put("/api/admin/backup", json={"repository": str(tmp_path / "repo"), "hour": 3})
    async with sessionmaker()() as session:
        assert await offsite.due(session) is True  # never ran
    # the place disappears (unplugged disk): the run fails and admins hear about it
    shutil.rmtree(tmp_path / "repo")
    (tmp_path / "repo").write_text("not a folder")
    await client.post("/api/admin/backup/run")
    await jobs.drain_local()
    runs = (await client.get("/api/admin/backup")).json()["runs"]
    assert runs[0]["status"] == "failed" and runs[0]["message"]
    notes = (await client.get("/api/notifications")).json()["items"]
    assert any(n["title"] == "Offsite backup failed" for n in notes)
    async with sessionmaker()() as session:
        later = datetime.now(timezone.utc).replace(microsecond=0)
        assert await offsite.due(session, later) is False  # not straight away...
