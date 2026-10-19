"""The duplicate-song check: extra copies leave Listen, the best one stays, nothing is lost."""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from app.services import jobs
from app.services.music_audit import copy_named, norm

_spec = importlib.util.spec_from_file_location("sample_shelf", Path(__file__).parents[2] / "scripts" / "sample_shelf.py")
sample = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sample)


def test_names():
    assert norm("Tumi Robe Nirobe (1)") == norm("Tumi Robe Nirobe") == "tumi robe nirobe"
    assert norm("01 - Tumi Robe Nirobe - Copy") == "tumi robe nirobe"
    assert norm("Tumi Robe Nirobe [320kbps] (Official Audio)") == "tumi robe nirobe"
    assert norm("Tumi Robe Nirobe (Live)") != norm("Tumi Robe Nirobe")
    assert norm("Tumi Robe Nirobe (Remix)") != norm("Tumi Robe Nirobe")
    assert copy_named("Band/Album/Song (1).mp3") and copy_named("Song - Copy.mp3")
    assert not copy_named("Band/Album/Song.mp3")


async def test_duplicates_leave_listen(tmp_path, monkeypatch, client, admin):
    root = tmp_path / "media"
    album = root / "Music" / "Shonar Band" / "Monsoon"
    tags = {"title": "Rain on Tin", "artist": "Shonar Band", "album": "Monsoon"}
    best = sample.tone(album / "01 Rain on Tin.flac", 6, 300, tags)                       # lossless: stays
    sample.tone(album / "01 Rain on Tin (1).mp3", 6, 300, tags)                           # same song, mp3
    shutil.copy(best, album / "01 Rain on Tin - Copy.flac")                               # identical file
    sample.tone(album / "02 Rain on Tin (Live).mp3", 6, 300, {**tags, "title": "Rain on Tin (Live)"})  # a different version
    sample.tone(album / "03 Evening Tea.mp3", 6, 500, {**tags, "title": "Evening Tea"})
    sample.tone(root / "Music" / "Old Tapes" / "Opening.mp3", 4, 600)                     # untagged
    sample.tone(root / "Music" / "Old Tapes" / "Opening (1).mp3", 4, 600)                 # untagged copy, same folder
    sample.tone(root / "Music" / "Other Tapes" / "Opening.mp3", 4, 650)                   # untagged, another folder: not a copy
    monkeypatch.setenv("ZIRAHIVE_MEDIA_ROOT", str(root))
    from app.config import get_settings
    get_settings.cache_clear()
    await client.post("/api/libraries/discover")
    await jobs.drain_local()

    songs = (await client.get("/api/music/tracks")).json()
    titles = sorted(s["title"] for s in songs)
    assert titles == ["Evening Tea", "Opening", "Opening", "Rain on Tin", "Rain on Tin (Live)"]
    kept = next(s for s in songs if s["title"] == "Rain on Tin")
    assert kept["codec"] == "flac"

    groups = (await client.get("/api/music/duplicates")).json()
    by_keep = {g["keep"]["path"]: sorted(c["path"] for c in g["copies"]) for g in groups}
    assert by_keep == {
        "Shonar Band/Monsoon/01 Rain on Tin.flac": ["Shonar Band/Monsoon/01 Rain on Tin (1).mp3",
                                                     "Shonar Band/Monsoon/01 Rain on Tin - Copy.flac"],
        "Old Tapes/Opening.mp3": ["Old Tapes/Opening (1).mp3"],
    }
    # ZiraHive could write here, so the copies were moved aside, not deleted
    music = root / "Music"
    assert not (album / "01 Rain on Tin (1).mp3").exists()
    assert (music / ".zirahive-duplicates" / "Shonar Band" / "Monsoon" / "01 Rain on Tin (1).mp3").exists()
    assert all(c["moved"] for g in groups for c in g["copies"])

    # a later scan doesn't bring them back, and the check finds nothing new
    await client.post("/api/libraries/discover")
    lib = next(l for l in (await client.get("/api/libraries")).json() if l["name"] == "Music")
    await client.post(f"/api/libraries/{lib['id']}/scan")
    await jobs.drain_local()
    assert len((await client.get("/api/music/tracks")).json()) == 5
    assert (await client.post("/api/music/duplicates/check")).json()["hidden"] == 0

    # "keep both": the copy comes back and stays
    copy = next(c for g in groups for c in g["copies"] if c["path"].endswith("(1).mp3") and "Rain" in c["path"])
    assert (await client.post(f"/api/music/duplicates/{copy['id']}/keep")).status_code == 204
    assert (album / "01 Rain on Tin (1).mp3").exists()
    assert len((await client.get("/api/music/tracks")).json()) == 6
    assert (await client.post("/api/music/duplicates/check")).json()["hidden"] == 0
    assert (await client.post(f"/api/music/duplicates/{copy['id']}/keep")).status_code == 404


async def test_plays_and_playlists_move_to_the_kept_copy(tmp_path, monkeypatch, client, admin):
    root = tmp_path / "media"
    folder = root / "Music" / "Singles"
    a = sample.tone(folder / "Song.mp3", 3, 300, {"title": "Song", "artist": "X"})
    monkeypatch.setenv("ZIRAHIVE_MEDIA_ROOT", str(root))
    from app.config import get_settings
    get_settings.cache_clear()
    await client.post("/api/libraries/discover")
    await jobs.drain_local()
    first = (await client.get("/api/music/tracks")).json()[0]
    # the copy arrives later, gets played and put in a playlist before the check runs
    shutil.copy(a, folder / "Song (1).mp3")
    from app import db
    from app.models import Track, Library
    from sqlalchemy import select
    async with db.sessionmaker()() as s:
        lib = (await s.scalars(select(Library).where(Library.kind == "music"))).first()
        copy = Track(library_id=lib.id, rel_path="Singles/Song (1).mp3", title="Song", artist="X",
                     duration=first["duration"], size=(folder / "Song (1).mp3").stat().st_size, codec="mp3")
        s.add(copy)
        await s.commit()
        copy_id = copy.id
    await client.put(f"/api/music/tracks/{copy_id}/favorite", json={"favorite": True})
    await client.post(f"/api/music/tracks/{copy_id}/played")
    p = (await client.post("/api/music/playlists", json={"name": "Mix", "track_ids": [copy_id]})).json()
    assert (await client.post("/api/music/duplicates/check")).json()["hidden"] == 1
    songs = (await client.get("/api/music/tracks")).json()
    assert len(songs) == 1 and songs[0]["id"] == first["id"]
    assert songs[0]["favorite"] and songs[0]["plays"] == 1
    mix = (await client.get(f"/api/music/playlists/{p['id']}")).json()
    assert [t["id"] for t in mix["tracks"]] == [first["id"]]
    # the copy can't be streamed as a song of its own any more
    assert (await client.get(f"/api/music/tracks/{copy_id}/stream")).status_code == 404
