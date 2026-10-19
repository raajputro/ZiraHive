"""One folder, one category: with Docker the media folder is reachable both as the media folder
(/media) and through its drive (/drives/g/Media), and both must count as the same folder."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import db
from app.models import Library
from app.services import browse, jobs
from conftest import make_video


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    # the conftest drive "T:" is tmp_path, so T:\Media is both the media folder and inside T:
    root = tmp_path / "Media"
    root.mkdir()
    monkeypatch.setenv("ZIRAHIVE_MEDIA_ROOT", str(root))
    monkeypatch.setenv("ZIRAHIVE_MEDIA_HOST_PATH", "T:/Media")
    return root


def _via_drive(tmp_path, *parts) -> str:
    return str(tmp_path / "drives" / "t" / "Media" / "/".join(parts))


async def test_same_folder_two_ways(media_root, tmp_path, client):
    via_media = str(media_root / "English Movies")
    via_drive = _via_drive(tmp_path, "English Movies")
    assert browse.same_folder_key(via_media) == browse.same_folder_key(via_drive)
    assert browse.same_folder_key(via_drive.replace("English", "english")) == browse.same_folder_key(via_media)
    assert browse.preferred(via_drive) == via_media
    assert browse.preferred(_via_drive(tmp_path)) == str(media_root)
    elsewhere = str(tmp_path / "drives" / "t" / "Other")
    assert browse.preferred(elsewhere) == elsewhere
    assert browse.same_folder_key(elsewhere) != browse.same_folder_key(via_media)


async def test_choosing_a_discovered_folder_through_its_drive_is_refused(media_root, tmp_path, client, admin):
    make_video(media_root / "English Movies" / "Inception (2010).mp4")
    await client.post("/api/libraries/discover")
    await jobs.drain_local()
    r = await client.post("/api/libraries", json={"name": "English", "path": _via_drive(tmp_path, "English Movies")})
    assert r.status_code == 409
    assert len((await client.get("/api/libraries")).json()) == 1


async def test_folder_inside_media_picked_first_is_stored_by_media_path(media_root, tmp_path, client, admin):
    make_video(media_root / "Hindi Movies" / "3 Idiots (2009).mp4")
    r = await client.post("/api/libraries", json={"name": "Hindi", "path": _via_drive(tmp_path, "Hindi Movies")})
    assert r.status_code == 201, r.text
    await jobs.drain_local()
    # discovery now recognises it instead of adding a second "Hindi Movies"
    assert (await client.post("/api/libraries/discover")).json() == []
    libs = (await client.get("/api/libraries")).json()
    assert [(l["name"], l["item_count"]) for l in libs] == [("Hindi", 1)]
    async with db.sessionmaker()() as session:
        assert (await session.scalars(select(Library.path))).all() == [str(media_root / "Hindi Movies")]


async def test_existing_duplicates_are_merged_keeping_progress(media_root, tmp_path, client, admin):
    folder = media_root / "English Movies"
    make_video(folder / "Inception (2010).mp4")
    make_video(folder / "Dune (2021).mp4")
    await client.post("/api/libraries/discover")
    # the duplicate an older version allowed: the same folder, saved through the drive
    async with db.sessionmaker()() as session:
        dup = Library(name="English Movies", path=_via_drive(tmp_path, "English Movies"), sort_order=0)
        session.add(dup)
        await session.commit()
        dup_id = dup.id
    await jobs.enqueue("scan_library", dup_id)
    await jobs.drain_local()
    libs = (await client.get("/api/libraries")).json()
    assert [l["name"] for l in libs].count("English Movies") == 2
    keep_id = next(l["id"] for l in libs if l["id"] != dup_id)

    def ids(lib_id):
        return client.get("/api/titles", params={"library_id": lib_id})

    keep_titles = {t["title"]: t["id"] for t in (await ids(keep_id)).json()}
    dup_titles = {t["title"]: t["id"] for t in (await ids(dup_id)).json()}
    # progress watched through the duplicate (Dune), and through both (Inception: the later one wins)
    await client.put(f"/api/media/{keep_titles['Inception']}/progress", json={"position": 0.5, "duration": 2.0})
    await client.put(f"/api/media/{dup_titles['Inception']}/progress", json={"position": 1.0, "duration": 2.0})
    await client.put(f"/api/media/{dup_titles['Dune']}/progress", json={"position": 0.7, "duration": 2.0})

    await client.post("/api/libraries/discover")  # "Find new folders" folds them together
    await jobs.drain_local()
    libs = (await client.get("/api/libraries")).json()
    assert [(l["id"], l["name"], l["item_count"]) for l in libs] == [(keep_id, "English Movies", 2)]
    for title, pos in (("Inception", 1.0), ("Dune", 0.7)):
        media = (await client.get(f"/api/media/{keep_titles[title]}")).json()
        assert media["position"] == pos
    assert (await client.get(f"/api/media/{dup_titles['Dune']}")).status_code == 404
