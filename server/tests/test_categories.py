from __future__ import annotations

import sqlite3

import pytest

from app.services import jobs
from app.services.libraries import guess_kind, pretty_name
from app.services.scanner import parse_episode
from conftest import make_video


# ----------------------------------------------------------- pure helpers

def test_pretty_names_and_kinds():
    assert pretty_name("english_movies") == "English Movies"
    assert pretty_name("Web Series") == "Web Series"
    assert pretty_name("bangla.natok") == "Bangla Natok"
    assert pretty_name("BBC documentaries") == "BBC Documentaries"
    assert guess_kind("Web Series") == "shows"
    assert guess_kind("Bangla Natok") == "shows"
    assert guess_kind("TV Shows") == "shows"
    assert guess_kind("Animation") == "mixed"
    assert guess_kind("Hindi Movies") == "movies"


@pytest.mark.parametrize("path,strict,expected", [
    ("Mirzapur/Season 2/Mirzapur.S02E05.1080p.WEB-DL.mkv", False, ("Mirzapur", 2, 5, None)),
    ("Friends (1994)/Season 1/01 - The Pilot.mkv", False, ("Friends", 1, 1, "The Pilot")),
    ("Breaking.Bad.S01E01.Pilot.720p.mkv", False, ("Breaking Bad", 1, 1, "Pilot")),
    ("Taqdeer/Taqdeer.E03.mkv", False, ("Taqdeer", 1, 3, None)),
    ("Karnaphuli/episode 7.mp4", False, ("Karnaphuli", 1, 7, None)),
    ("Korean/Squid Game/Season 1/Squid.Game.S01E01.Red.Light.mkv", False, ("Squid Game", 1, 1, "Red Light")),
    ("Avatar The Last Airbender/Book 2/Avatar.2x03.mkv", True, ("Avatar The Last Airbender", 2, 3, None)),
    ("The Office (US)/S02/The Office S02E01 The Dundies.mkv", False, ("The Office (US)", 2, 1, "The Dundies")),
])
def test_parse_episode(path, strict, expected):
    ep = parse_episode(path, strict=strict)
    assert (ep.series_title, ep.season, ep.episode, ep.episode_title) == expected


def test_strict_mode_leaves_movies_alone():
    assert parse_episode("Kung Fu Panda (2008).mkv", strict=True) is None
    assert parse_episode("Frozen 2 (2019)/Frozen.2.2019.1080p.mkv", strict=True) is None


# ---------------------------------------------------------- integration

@pytest.fixture
def media_root(tmp_path, monkeypatch):
    # must be requested before `client` so the app starts with this setting
    root = tmp_path / "media"
    root.mkdir()
    monkeypatch.setenv("GHARBOX_MEDIA_ROOT", str(root))
    return root


async def _build_library(root):
    make_video(root / "english_movies" / "Inception (2010)" / "Inception (2010).mp4")
    make_video(root / "Hindi Movies" / "3 Idiots (2009).mp4")
    show = root / "Web Series" / "Mirzapur" / "Season 1"
    for n in (1, 2, 3):
        make_video(show / f"Mirzapur.S01E0{n}.mp4")
    make_video(root / "Web Series" / "Mirzapur" / "Season 2" / "Mirzapur.S02E01.mp4")
    make_video(root / "Animation" / "Kung Fu Panda (2008).mp4")
    make_video(root / "Animation" / "Avatar" / "Book 1" / "Avatar.S01E01.mp4")


async def test_categories_are_discovered_and_split(media_root, client, admin):
    await _build_library(media_root)
    found = (await client.post("/api/libraries/discover")).json()
    await jobs.drain_local()
    names = {lib["name"]: lib["kind"] for lib in found}
    assert names == {"Animation": "mixed", "English Movies": "movies",
                     "Hindi Movies": "movies", "Web Series": "shows"}
    # running discovery again adds nothing
    assert (await client.post("/api/libraries/discover")).json() == []

    libs = {lib["name"]: lib for lib in (await client.get("/api/libraries")).json()}
    assert libs["Web Series"]["item_count"] == 1          # one series
    assert libs["Animation"]["item_count"] == 2           # one movie + one series

    web = (await client.get("/api/titles", params={"library_id": libs["Web Series"]["id"]})).json()
    assert [(t["type"], t["title"], t["episode_count"]) for t in web] == [("series", "Mirzapur", 4)]
    anim = (await client.get("/api/titles", params={"library_id": libs["Animation"]["id"],
                                                      "sort": "title"})).json()
    assert [(t["type"], t["title"]) for t in anim] == [("series", "Avatar"), ("movie", "Kung Fu Panda")]

    # movies list never includes episodes
    movies = {m["title"] for m in (await client.get("/api/media")).json()}
    assert movies == {"Inception", "3 Idiots", "Kung Fu Panda"}

    # search works across categories
    hits = (await client.get("/api/titles", params={"q": "mirz"})).json()
    assert [t["title"] for t in hits] == ["Mirzapur"]


async def test_series_page_next_episode_and_up_next(media_root, client, admin):
    await _build_library(media_root)
    await client.post("/api/libraries/discover")
    await jobs.drain_local()
    sid = (await client.get("/api/titles", params={"q": "Mirzapur"})).json()[0]["id"]
    series = (await client.get(f"/api/series/{sid}")).json()
    assert [s["season"] for s in series["seasons"]] == [1, 2]
    s1 = series["seasons"][0]["episodes"]
    assert [e["episode"] for e in s1] == [1, 2, 3]
    assert series["up_next"]["id"] == s1[0]["id"]
    assert (await client.get(f"/api/series/{sid}/poster")).status_code == 200

    # next_id crosses into the next season
    last_s1 = (await client.get(f"/api/media/{s1[2]['id']}")).json()
    s2e1 = series["seasons"][1]["episodes"][0]
    assert last_s1["next_id"] == s2e1["id"] and last_s1["series_title"] == "Mirzapur"

    # finish episode 1 -> episode 2 is up next and shows in Continue watching
    await client.put(f"/api/media/{s1[0]['id']}/progress", json={"position": 2.0, "duration": 2.0})
    series = (await client.get(f"/api/series/{sid}")).json()
    assert series["up_next"]["id"] == s1[1]["id"]
    cont = (await client.get("/api/media/continue")).json()
    assert [c["id"] for c in cont] == [s1[1]["id"]]
    titles = (await client.get("/api/titles", params={"q": "Mirzapur"})).json()
    assert titles[0]["watched_count"] == 1


async def test_change_kind_reclassifies(media_root, client, admin):
    await _build_library(media_root)
    await client.post("/api/libraries/discover")
    await jobs.drain_local()
    web = next(l for l in (await client.get("/api/libraries")).json() if l["name"] == "Web Series")
    r = await client.patch(f"/api/libraries/{web['id']}", json={"kind": "movies", "name": "Shows"})
    assert r.json()["kind"] == "movies" and r.json()["name"] == "Shows"
    await jobs.drain_local()
    titles = (await client.get("/api/titles", params={"library_id": web["id"]})).json()
    assert {t["type"] for t in titles} == {"movie"} and len(titles) == 4


async def test_reorder_and_missing_folder(media_root, client, admin):
    await _build_library(media_root)
    await client.post("/api/libraries/discover")
    await jobs.drain_local()
    libs = (await client.get("/api/libraries")).json()
    ids = [l["id"] for l in libs][::-1]
    reordered = (await client.put("/api/libraries/order", json={"ids": ids})).json()
    assert [l["id"] for l in reordered] == ids
    # unplug a drive: its titles disappear but come back on the next scan
    hindi = next(l for l in libs if l["name"] == "Hindi Movies")
    (media_root / "Hindi Movies").rename(media_root.parent / "elsewhere")
    await client.post(f"/api/libraries/{hindi['id']}/scan")
    await jobs.drain_local()
    lib = next(l for l in (await client.get("/api/libraries")).json() if l["id"] == hindi["id"])
    assert lib["available"] is False and lib["item_count"] == 0
    (media_root.parent / "elsewhere").rename(media_root / "Hindi Movies")
    await client.post(f"/api/libraries/{hindi['id']}/scan")
    await jobs.drain_local()
    assert "3 Idiots" in {m["title"] for m in (await client.get("/api/media")).json()}


async def test_old_database_is_upgraded(tmp_path, monkeypatch):
    """A database made by the first release (no series columns) gets the new columns."""
    data = tmp_path / "data"
    data.mkdir()
    db = sqlite3.connect(data / "gharbox.db")
    db.executescript("""
        CREATE TABLE libraries (id VARCHAR(32) PRIMARY KEY, name VARCHAR(128), path TEXT UNIQUE,
            kind VARCHAR(16), last_scan_at DATETIME, created_at DATETIME);
        INSERT INTO libraries VALUES ('lib1', 'Movies', '/nowhere', 'movies', NULL, '2026-10-16');
        CREATE TABLE media_items (id VARCHAR(32) PRIMARY KEY, library_id VARCHAR(32), rel_path TEXT,
            title VARCHAR(512), year INTEGER, overview TEXT, size BIGINT, mtime FLOAT,
            container VARCHAR(32), video_codec VARCHAR(32), audio_codec VARCHAR(32), width INTEGER,
            height INTEGER, duration FLOAT, poster_ready BOOLEAN, tmdb_id INTEGER, missing BOOLEAN,
            added_at DATETIME);
    """)
    db.commit()
    db.close()
    monkeypatch.setenv("GHARBOX_DATA_DIR", str(data))
    monkeypatch.setenv("GHARBOX_DATABASE_URL", "")
    from app.config import get_settings
    get_settings.cache_clear()
    from app import db as appdb
    appdb.init_engine(get_settings().db_url)
    await appdb.create_all()
    await appdb.dispose()
    db = sqlite3.connect(data / "gharbox.db")
    lib_cols = {r[1] for r in db.execute("PRAGMA table_info(libraries)")}
    item_cols = {r[1] for r in db.execute("PRAGMA table_info(media_items)")}
    assert "sort_order" in lib_cols
    assert {"series_id", "season", "episode", "episode_title"} <= item_cols
    assert db.execute("SELECT sort_order FROM libraries").fetchone()[0] == 0
    get_settings.cache_clear()


def test_media_folder_shown_as_on_the_pc(monkeypatch, tmp_path):
    from app.config import get_settings
    from app.services.browse import display

    monkeypatch.setenv("GHARBOX_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setenv("GHARBOX_MEDIA_HOST_PATH", "G:/Media/")
    get_settings.cache_clear()
    try:
        assert display(tmp_path / "English Movies") == "G:\\Media\\English Movies"
        assert display(tmp_path) == "G:\\Media"
    finally:
        get_settings.cache_clear()
