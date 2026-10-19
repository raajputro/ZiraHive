"""Quran recitations and the namaz settings and tracker."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services import jobs
from app.services.libraries import guess_kind
from app.services.quran_data import SURAHS, parse_file

_spec = importlib.util.spec_from_file_location("sample_shelf", Path(__file__).parents[2] / "scripts" / "sample_shelf.py")
sample = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sample)


def test_surah_names_in_files():
    assert len(SURAHS) == 114 and sum(s["ayahs"] for s in SURAHS) == 6236
    assert guess_kind("Quran") == "quran"
    assert guess_kind("Quran Tilawat") == "quran"
    assert guess_kind("কুরআন") == "quran"
    assert guess_kind("Music") == "music"
    cases = {"001": (1, None), "018-Kahf": (18, None), "Surah Yaseen": (36, None), "002255": (2, 255),
             "Mishary - Surah Ar-Rahman": (55, None), "Surah Al-Mulk (Sudais)": (67, None),
             "114 An-Nas": (114, None), "Dua Khatm": (None, None)}
    for stem, want in cases.items():
        assert parse_file(stem) == want, stem


async def test_recitations(tmp_path, monkeypatch, client, admin):
    root = tmp_path / "media"
    for n in (1, 36, 67):
        sample.tone(root / "Quran" / "Mishary Alafasy" / f"{n:03d}.mp3", 1, 300 + n)
    for ayah in (1, 2, 3):
        sample.tone(root / "Quran" / "Abdul Basit" / f"001{ayah:03d}.mp3", 1, 400 + ayah)
    sample.tone(root / "Quran" / "Abdul Basit" / "Dua Khatm.mp3", 1, 500)
    sample.tone(root / "Music" / "Band" / "Album" / "01 Song.mp3", 1, 600)
    monkeypatch.setenv("ZIRAHIVE_MEDIA_ROOT", str(root))
    from app.config import get_settings
    get_settings.cache_clear()

    await client.post("/api/libraries/discover")
    await jobs.drain_local()
    kinds = {lib["name"]: lib["kind"] for lib in (await client.get("/api/libraries")).json()}
    assert kinds["Quran"] == "quran" and kinds["Music"] == "music"

    home = (await client.get("/api/quran")).json()
    assert home["has_category"]
    reciters = {r["name"]: r for r in home["reciters"]}
    assert reciters["Mishary Alafasy"]["surahs"] == 3
    assert reciters["Abdul Basit"]["surahs"] == 1 and reciters["Abdul Basit"]["files"] == 4

    basit = (await client.get("/api/quran/reciter", params={"name": "Abdul Basit"})).json()
    assert [s["number"] for s in basit["surahs"]] == [1]
    assert len(basit["surahs"][0]["tracks"]) == 3       # the ayah files, in order
    assert [t["title"] for t in basit["other"]] == ["Dua Khatm"]

    # recitations play like songs, but stay out of Listen
    track = basit["surahs"][0]["tracks"][0]
    r = await client.get(f"/api/music/tracks/{track['id']}/stream", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    songs = (await client.get("/api/music/tracks")).json()
    assert [s["title"] for s in songs] == ["Song"]
    await client.post(f"/api/music/tracks/{track['id']}/played")
    assert [t["id"] for t in (await client.get("/api/quran")).json()["recent"]] == [track["id"]]
    assert (await client.get("/api/quran/reciter", params={"name": "Nobody"})).status_code == 404
    fatiha = (await client.get("/api/quran/surah/1")).json()
    assert [(r["reciter"], len(r["tracks"])) for r in fatiha] == [("Abdul Basit", 3), ("Mishary Alafasy", 1)]
    assert (await client.get("/api/quran/surah/115")).status_code == 404


async def test_add_recitations_from_the_page(tmp_path, client, admin):
    assert (await client.get("/api/quran")).json()["has_category"] is False
    audio = sample.tone(tmp_path / "x.mp3", 1, 300).read_bytes()
    r = await client.put("/api/quran/files", params={"reciter": "Saad Al-Ghamdi", "name": "036 Ya-Sin.mp3"}, content=audio)
    assert r.status_code == 200, r.text
    assert r.json() == {"reciter": "Saad Al-Ghamdi", "name": "036 Ya-Sin.mp3", "size": len(audio)}
    # names can't climb out of the folder
    r = await client.put("/api/quran/files", params={"reciter": "../../etc", "name": "../x.mp3"}, content=audio)
    assert r.status_code == 200 and r.json()["reciter"] == "etc" and r.json()["name"] == "x.mp3"
    assert (await client.put("/api/quran/files", params={"reciter": "A", "name": "notes.txt"}, content=b"hi")).status_code == 400
    assert (await client.post("/api/quran/rescan")).json()["scanning"] == 1
    await jobs.drain_local()
    reciters = {r["name"]: r for r in (await client.get("/api/quran")).json()["reciters"]}
    assert reciters["Saad Al-Ghamdi"]["surahs"] == 1


async def test_namaz_settings_and_tracker(client, admin):
    s = (await client.get("/api/namaz/settings")).json()
    assert s["method"] == "karachi" and s["asr"] == "hanafi" and s["lat"] is None
    body = {**s, "lat": 23.8103, "lng": 90.4125, "place": "Dhaka", "timezone": "Asia/Dhaka",
            "offsets": {**s["offsets"], "maghrib": 3}}
    assert (await client.put("/api/namaz/settings", json=body)).status_code == 200
    again = (await client.get("/api/namaz/settings")).json()
    assert again["place"] == "Dhaka" and again["offsets"]["maghrib"] == 3
    assert (await client.put("/api/namaz/settings", json={**body, "method": "nope"})).status_code == 400
    assert (await client.put("/api/namaz/settings", json={**body, "lng": None})).status_code == 400

    for prayer, status in (("fajr", "ontime"), ("dhuhr", "late"), ("asr", "missed")):
        r = await client.put("/api/namaz/log", json={"day": "2026-10-19", "prayer": prayer, "status": status, "jamaah": True})
        assert r.status_code == 200
    await client.put("/api/namaz/log", json={"day": "2026-10-18", "prayer": "isha", "status": "ontime"})
    log = (await client.get("/api/namaz/log", params={"start": "2026-10-19", "end": "2026-10-19"})).json()
    got = {(e["prayer"], e["status"], e["jamaah"]) for e in log}
    assert got == {("fajr", "ontime", True), ("dhuhr", "late", True), ("asr", "missed", False)}
    await client.put("/api/namaz/log", json={"day": "2026-10-19", "prayer": "fajr", "status": None})
    log = (await client.get("/api/namaz/log", params={"start": "2026-10-01", "end": "2026-10-31"})).json()
    assert len(log) == 3
    assert (await client.put("/api/namaz/log", json={"day": "2026-13-40", "prayer": "fajr", "status": "ontime"})).status_code == 400
    assert (await client.put("/api/namaz/log", json={"day": "2026-10-19", "prayer": "lunch", "status": "ontime"})).status_code == 400


async def test_recitations_never_mix_with_songs(tmp_path, monkeypatch, client, admin):
    """A Quran folder inside the Music folder: its files are recitations, not songs."""
    root = tmp_path / "media"
    sample.tone(root / "Music" / "Band" / "Album" / "01 Song.mp3", 1, 600, {"title": "Song", "artist": "Band", "album": "Album"})
    for n in (1, 112):
        sample.tone(root / "Music" / "Quran" / "Sudais" / f"{n:03d}.mp3", 1, 300 + n,
                    {"title": f"Surah {n}", "artist": "Sudais", "album": "Quran"})
    sample.tone(root / "Music" / "Islamic" / "Tilawat" / "Yasin.mp3", 1, 400)   # a tilawat folder deeper down
    monkeypatch.setenv("ZIRAHIVE_MEDIA_ROOT", str(root))
    from app.config import get_settings
    get_settings.cache_clear()
    await client.post("/api/libraries/discover")
    await jobs.drain_local()

    # Listen: songs only, everywhere
    assert [s["title"] for s in (await client.get("/api/music/tracks")).json()] == ["Song"]
    assert [s["title"] for s in (await client.get("/api/music/tracks", params={"q": "surah"})).json()] == []
    assert [a["title"] for a in (await client.get("/api/music/albums")).json()] == ["Album"]
    assert [a["name"] for a in (await client.get("/api/music/artists")).json()] == ["Band"]
    assert (await client.get("/api/music/artist", params={"name": "Sudais"})).status_code == 404

    # Quran & Namaz: the recitations, by qari
    home = (await client.get("/api/quran")).json()
    assert home["has_category"]
    assert {r["name"]: r["surahs"] for r in home["reciters"]} == {"Sudais": 2, "Tilawat": 1}
    rec = (await client.get("/api/quran/reciter", params={"name": "Sudais"})).json()["surahs"][0]["tracks"][0]
    assert rec["quran"] is True

    # played, favourited, put in a playlist: still never among songs
    await client.post(f"/api/music/tracks/{rec['id']}/played")
    await client.put(f"/api/music/tracks/{rec['id']}/favorite", json={"favorite": True})
    p = (await client.post("/api/music/playlists", json={"name": "Mix", "track_ids": [rec["id"]]})).json()
    assert p["tracks"] == []
    music_home = (await client.get("/api/music/home")).json()
    assert music_home["recently_played"] == [] and music_home["most_played"] == []
    assert (await client.get("/api/music/tracks", params={"favorites": True})).json() == []
    assert [t["id"] for t in (await client.get("/api/quran")).json()["recent"]] == [rec["id"]]

    # notifications: "new songs" counts songs only
    notes = [n["title"] for n in (await client.get("/api/notifications")).json()["items"]]
    assert "1 new song in Music" in notes and "3 new recitations in Quran" in notes
