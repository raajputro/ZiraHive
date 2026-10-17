"""The PC sync client against a real ZiraHive server (in-process)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "sync-client"))

from zirahive_sync import engine  # noqa: E402
from zirahive_sync.api import Api  # noqa: E402
from zirahive_sync.config import Pair  # noqa: E402


@pytest.fixture
async def setup(app, client, admin, tmp_path, monkeypatch):
    monkeypatch.setenv("ZIRAHIVE_SYNC_HOME", str(tmp_path / "appdata"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(engine, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(engine, "trash_local", lambda p: p.rename(tmp_path / f"recycled-{p.name}"))
    api = Api("http://test", admin, transport=httpx.ASGITransport(app=app))
    await api.configure()
    local = tmp_path / "pc"
    local.mkdir()
    pair = Pair(local=str(local), remote="/PC Sync")
    yield api, pair, local, client, tmp_path
    await api.close()


async def remote_files(api: Api) -> dict[str, str]:
    tree = await api.tree("/PC Sync")
    return {f["path"]: f for f in tree["files"]}


async def put_remote(client, path: str, data: bytes):
    folder, _, name = ("/PC Sync/" + path).rpartition("/")
    up = (await client.post("/api/uploads", json={"filename": name, "size": len(data), "folder": folder,
                                                  "dedupe": False, "replace": True})).json()
    if up.get("status") == "uploading":
        up = (await client.patch(f"/api/uploads/{up['id']}", content=data, headers={"Upload-Offset": "0"})).json()
    return up["asset"]


async def content(client, asset) -> bytes:
    return (await client.get(f"/api/assets/{asset['id']}/file")).content


async def test_two_way_sync(setup):
    api, pair, local, client, tmp = setup
    (local / "notes.txt").write_text("from the PC")
    (local / "Tax" / "2025").mkdir(parents=True)
    (local / "Tax" / "2025" / "return.pdf").write_bytes(b"%PDF-1.4 pc")
    (local / "Empty folder").mkdir()
    (local / "desktop.ini").write_text("ignored")
    await put_remote(client, "phone/photo.jpg", b"\xff\xd8 from the phone")

    r = await engine.sync_pair(api, pair)
    assert sorted(r.uploaded) == ["Tax/2025/return.pdf", "notes.txt"] and r.downloaded == ["phone/photo.jpg"]
    remote = await remote_files(api)
    assert set(remote) == {"Tax/2025/return.pdf", "notes.txt", "phone/photo.jpg"}
    assert (local / "phone" / "photo.jpg").read_bytes() == b"\xff\xd8 from the phone"
    assert "Empty folder" in (await api.tree("/PC Sync"))["folders"]

    # nothing changed: nothing happens
    r = await engine.sync_pair(api, pair)
    assert r.changes == 0 and not r.conflicts

    # edit on the PC: uploaded, ZiraHive keeps the old copy as a version
    (local / "notes.txt").write_text("from the PC, edited")
    r = await engine.sync_pair(api, pair)
    assert r.uploaded == ["notes.txt"]
    note = (await remote_files(api))["notes.txt"]
    assert await content(client, note) == b"from the PC, edited"
    assert len((await client.get(f"/api/assets/{note['id']}/versions")).json()) == 1

    # edit in ZiraHive (e.g. from the phone): downloaded
    await put_remote(client, "phone/photo.jpg", b"\xff\xd8 edited on the phone")
    r = await engine.sync_pair(api, pair)
    assert r.downloaded == ["phone/photo.jpg"]
    assert (local / "phone" / "photo.jpg").read_bytes() == b"\xff\xd8 edited on the phone"

    # delete on the PC: goes to the ZiraHive trash
    (local / "Tax" / "2025" / "return.pdf").unlink()
    r = await engine.sync_pair(api, pair)
    assert r.trashed_remote == ["Tax/2025/return.pdf"]
    assert "return.pdf" in {a["filename"] for a in (await client.get("/api/trash")).json()}

    # delete in ZiraHive: goes to the Recycle Bin on the PC
    await client.delete(f"/api/assets/{(await remote_files(api))['phone/photo.jpg']['id']}")
    r = await engine.sync_pair(api, pair)
    assert r.trashed_local == ["phone/photo.jpg"] and not (local / "phone" / "photo.jpg").exists()
    assert (tmp / "recycled-photo.jpg").exists()

    # changed on both sides: both copies are kept
    (local / "notes.txt").write_text("PC version")
    await put_remote(client, "notes.txt", b"ZiraHive version")
    r = await engine.sync_pair(api, pair)
    assert r.conflicts == ["notes.txt"]
    assert (local / "notes.txt").read_text() == "ZiraHive version"
    copies = [p for p in local.iterdir() if p.name.startswith("notes (PC copy")]
    assert len(copies) == 1 and copies[0].read_text() == "PC version"
    assert any(k.startswith("notes (PC copy") for k in await remote_files(api))
    r = await engine.sync_pair(api, pair)
    assert r.changes == 0


async def test_safety_guards(setup):
    api, pair, local, client, tmp = setup
    for i in range(6):
        (local / f"file{i}.txt").write_text(f"file {i}")
    await engine.sync_pair(api, pair)
    assert len(await remote_files(api)) == 6

    # the PC folder disappears (unplugged drive): nothing is touched
    moved = tmp / "elsewhere"
    local.rename(moved)
    r = await engine.sync_pair(api, pair)
    assert r.stopped and "isn't there" in r.stopped and len(await remote_files(api)) == 6
    moved.rename(local)

    # most files deleted at once: paused until allowed
    for i in range(5):
        (local / f"file{i}.txt").unlink()
    r = await engine.sync_pair(api, pair)
    assert r.stopped and "5 of 6" in r.stopped and len(await remote_files(api)) == 6
    api.allow_mass_delete = True
    r = await engine.sync_pair(api, pair)
    assert len(r.trashed_remote) == 5 and set(await remote_files(api)) == {"file5.txt"}

    # names ZiraHive can't keep are reported, not lost
    if os.name != "nt":
        (local / "what?.txt").write_text("x")
        r = await engine.sync_pair(api, pair)
        assert any("what?.txt" in s for s in r.skipped)


async def test_device_token_and_signed_out(app, client, admin):
    api = Api("http://test", transport=httpx.ASGITransport(app=app))
    token = await api.login("mahbub", "supersecret")
    assert token and (await api.me())["username"] == "mahbub"
    log = (await client.get("/api/admin/audit")).json()
    assert any(e["action"] == "device_linked" for e in log)
    # sign out everywhere ends the device sign-in too
    await client.post("/api/auth/logout-all")
    from zirahive_sync.api import SignedOut
    with pytest.raises(SignedOut):
        await api.tree("/")
    await api.close()
