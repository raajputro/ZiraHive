"""Batch 4: music, audiobooks, ebooks and comics."""
from __future__ import annotations

import asyncio
import importlib.util
import shutil
from pathlib import Path

import pytest

from app.services import jobs
from app.services.libraries import guess_kind
from app.services.shelf_files import comic_series_from_name, natural_key

_spec = importlib.util.spec_from_file_location("sample_shelf", Path(__file__).parents[2] / "scripts" / "sample_shelf.py")
sample = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sample)


def test_kinds_and_names():
    assert guess_kind("Music") == "music"
    assert guess_kind("Bangla Songs") == "music"
    assert guess_kind("Rabindra Sangeet") == "music"
    assert guess_kind("Audiobooks") == "audiobooks"
    assert guess_kind("Ebooks") == "books"
    assert guess_kind("Kids Comics") == "comics"
    assert guess_kind("Manga") == "comics"
    assert guess_kind("Animation") == "mixed"
    assert comic_series_from_name("One Piece v01") == ("One Piece", 1)
    assert comic_series_from_name("Batman 012 (2016)") == ("Batman", 12)
    assert comic_series_from_name("Saga #54") == ("Saga", 54)
    assert sorted(["p10", "p9", "p1"], key=natural_key) == ["p1", "p9", "p10"]


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    root = tmp_path / "media"
    sample.make_all(root)
    monkeypatch.setenv("GHARBOX_MEDIA_ROOT", str(root))
    return root


async def _libs(client) -> dict[str, dict]:
    await client.post("/api/libraries/discover")
    await jobs.drain_local()
    return {lib["name"]: lib for lib in (await client.get("/api/libraries")).json()}


async def test_music_library(media_root, client, admin):
    libs = await _libs(client)
    assert {n: l["kind"] for n, l in libs.items()} == {"Music": "music", "Audiobooks": "audiobooks",
                                                       "Ebooks": "books", "Comics": "comics"}
    assert libs["Music"]["item_count"] == 3  # albums

    albums = {a["title"]: a for a in (await client.get("/api/music/albums", params={"sort": "title"})).json()}
    assert set(albums) == {"Live at Home", "Monsoon Songs", "Singles"}
    monsoon = albums["Monsoon Songs"]
    assert (monsoon["artist"], monsoon["year"], monsoon["genre"], monsoon["track_count"]) == ("Shonar Band", 2021, "Folk", 3)
    assert monsoon["cover_ready"] and albums["Live at Home"]["cover_ready"]  # embedded art, cover.jpg
    assert albums["Live at Home"]["artist"] == "Old Tapes"  # untagged: from the folder names
    assert (await client.get(f"/api/music/albums/{monsoon['id']}/cover")).headers["content-type"] == "image/webp"

    detail = (await client.get(f"/api/music/albums/{monsoon['id']}")).json()
    assert [(t["track_no"], t["title"]) for t in detail["tracks"]] == [(1, "Rain on Tin"), (2, "Rickshaw Bell"), (3, "Evening Tea")]
    song = detail["tracks"][0]

    # streaming with seeking
    r = await client.get(f"/api/music/tracks/{song['id']}/stream", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.headers["content-type"] == "audio/mpeg" and len(r.content) == 100

    artists = {a["name"]: a for a in (await client.get("/api/music/artists")).json()}
    assert artists["Shonar Band"]["album_count"] == 1 and artists["Shonar Band"]["track_count"] == 3
    artist = (await client.get("/api/music/artist", params={"name": "Shonar Band"})).json()
    assert len(artist["albums"]) == 1 and len(artist["tracks"]) == 3

    found = (await client.get("/api/music/tracks", params={"q": "rickshaw"})).json()
    assert [t["title"] for t in found] == ["Rickshaw Bell"]

    # favourites and plays
    assert (await client.put(f"/api/music/tracks/{song['id']}/favorite", json={"favorite": True})).status_code == 204
    for _ in range(2):
        await client.post(f"/api/music/tracks/{song['id']}/played")
    favs = (await client.get("/api/music/tracks", params={"favorites": True})).json()
    assert [t["title"] for t in favs] == ["Rain on Tin"] and favs[0]["plays"] == 2
    home = (await client.get("/api/music/home")).json()
    assert home["favorite_count"] == 1 and home["recently_played"][0]["id"] == song["id"]
    assert home["most_played"][0]["plays"] == 2 and len(home["recent_albums"]) == 3


async def test_unplayable_audio_is_converted(media_root, client, admin):
    await _libs(client)
    wma = (await client.get("/api/music/tracks", params={"q": "Old Radio"})).json()[0]
    assert wma["codec"] == "wma" and wma["playable"] is False
    first = await client.get(f"/api/music/tracks/{wma['id']}/stream")
    assert first.status_code == 409  # converting has started
    for _ in range(100):
        ready = (await client.get(f"/api/music/tracks/{wma['id']}/prepare")).json()
        if ready["ready"] or ready["failed"]:
            break
        await asyncio.sleep(0.1)
    assert ready == {"ready": True, "failed": False}
    r = await client.get(f"/api/music/tracks/{wma['id']}/stream")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content[:2] == b"\xff\xfb"

    # a browser that can't play a file after all asks for a converted copy
    song = (await client.get("/api/music/tracks", params={"q": "Rain on Tin"})).json()[0]
    assert (await client.get(f"/api/music/tracks/{song['id']}/prepare")).json()["ready"] is True
    for _ in range(100):
        r = (await client.get(f"/api/music/tracks/{song['id']}/prepare", params={"force": True})).json()
        if r["ready"]:
            break
        await asyncio.sleep(0.1)
    r = await client.get(f"/api/music/tracks/{song['id']}/stream", params={"converted": True})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"


async def test_playlists(media_root, client, admin):
    await _libs(client)
    songs = (await client.get("/api/music/tracks", params={"sort": "title"})).json()
    ids = [s["id"] for s in songs]
    p = (await client.post("/api/music/playlists", json={"name": "Road trip", "track_ids": ids[:2] + ["nope"]})).json()
    assert [t["id"] for t in p["tracks"]] == ids[:2] and p["track_count"] == 2
    p = (await client.post(f"/api/music/playlists/{p['id']}/tracks", json={"track_ids": [ids[3]]})).json()
    assert [t["id"] for t in p["tracks"]] == ids[:2] + [ids[3]]
    p = (await client.patch(f"/api/music/playlists/{p['id']}", json={"name": "Long drive",
                                                                     "track_ids": [ids[3], ids[0]]})).json()
    assert p["name"] == "Long drive" and [t["id"] for t in p["tracks"]] == [ids[3], ids[0]]
    assert len((await client.get("/api/music/playlists")).json()) == 1

    # someone else can't see or change it
    await client.post("/api/users", json={"username": "rina", "password": "rinapassword"})
    token = (await client.post("/api/auth/login", json={"username": "rina", "password": "rinapassword"})).json()["token"]
    other = {"Authorization": f"Bearer {token}"}
    assert (await client.get(f"/api/music/playlists/{p['id']}", headers=other)).status_code == 404
    assert (await client.get("/api/music/playlists", headers=other)).json() == []
    assert (await client.delete(f"/api/music/playlists/{p['id']}")).status_code == 204


async def test_audiobooks(media_root, client, admin):
    await _libs(client)
    books = {b["title"]: b for b in (await client.get("/api/books", params={"kind": "audiobook"})).json()}
    assert set(books) == {"Short Stories", "The River Journey"}
    stories = (await client.get(f"/api/books/{books['Short Stories']['id']}")).json()
    assert (stories["author"], stories["narrator"]) == ("Rabindra Thakur", "Amio Reader")
    assert [p["title"] for p in stories["parts"]] == ["The Postmaster", "Kabuliwala", "Subha"]
    assert stories["parts"][1]["start"] == pytest.approx(stories["parts"][0]["duration"])
    assert stories["cover_ready"] and stories["downloadable"] is False

    river = (await client.get(f"/api/books/{books['The River Journey']['id']}")).json()
    assert [c["title"] for c in river["chapters"]] == ["Chapter 1: Departure", "Chapter 2: The Delta", "Chapter 3: Home"]
    assert river["chapters"][1]["start"] == pytest.approx(4, abs=0.1) and len(river["parts"]) == 1

    r = await client.get(f"/api/books/{stories['id']}/audio/2", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.headers["content-type"] == "audio/mpeg"
    assert (await client.get(f"/api/books/{stories['id']}/audio/3")).status_code == 404

    # listening progress, continue listening, finishing
    await client.put(f"/api/books/{stories['id']}/progress", json={"position": 6.5, "fraction": 0.53})
    cont = (await client.get("/api/books/continue", params={"kind": "audiobook"})).json()
    assert [b["id"] for b in cont] == [stories["id"]] and cont[0]["progress"]["position"] == 6.5
    done = (await client.put(f"/api/books/{stories['id']}/progress", json={"position": 12, "fraction": 1})).json()
    assert done["finished"] is True
    assert (await client.get("/api/books/continue")).json() == []


async def test_ebooks_and_comics(media_root, client, admin):
    libs = await _libs(client)
    reading = {b["title"]: b for b in (await client.get("/api/books", params={"kind": "reading"})).json()}
    assert {"The River Journey", "Delta Tales: Book One", "Cooking with Mustard Oil", "Sky Rider #1: Issue 1",
            "Moon Cat #1: Issue 1", "Hero Academy: Chapter 001"} <= set(reading)
    if shutil.which("bsdtar"):
        assert "Tiger Tales 01" in reading

    # EPUB: metadata, cover, the file for the reader, series order
    river = (await client.get(f"/api/books/{reading['The River Journey']['id']}")).json()
    assert (river["format"], river["author"], river["language"], river["year"]) == ("epub", "Nadi Writer", "en", 2020)
    assert river["description"] == "A short sample book about the river journey." and river["downloadable"]
    f = await client.get(f"/api/books/{river['id']}/file")
    assert f.headers["content-type"] == "application/epub+zip" and f.content[:2] == b"PK"
    dl = await client.get(f"/api/books/{river['id']}/file", params={"download": True})
    assert dl.headers["content-disposition"].startswith("attachment")
    one = (await client.get(f"/api/books/{reading['Delta Tales: Book One']['id']}")).json()
    assert one["series_name"] == "Delta Tales" and one["next_in_series"] == reading["Delta Tales: Book Two"]["id"]
    series = (await client.get("/api/books", params={"series": "Delta Tales"})).json()
    assert [b["series_index"] for b in series] == [1, 2]

    # PDF
    pdf = (await client.get(f"/api/books/{reading['Cooking with Mustard Oil']['id']}")).json()
    assert (pdf["format"], pdf["pages"], pdf["author"]) == ("pdf", 4, "Sample Author")
    if shutil.which("pdftoppm"):
        assert pdf["cover_ready"]

    # CBZ: page order, right-to-left manga, scaled pages, cached
    sky = (await client.get(f"/api/books/{reading['Sky Rider #1: Issue 1']['id']}")).json()
    assert (sky["kind"], sky["pages"], sky["series_name"], sky["rtl"]) == ("comic", 12, "Sky Rider", False)
    moon = (await client.get(f"/api/books/{reading['Moon Cat #1: Issue 1']['id']}")).json()
    assert moon["rtl"] is True
    page = await client.get(f"/api/books/{sky['id']}/pages/10", params={"w": 720})
    assert page.status_code == 200 and page.headers["content-type"] == "image/webp"
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(page.content))
    assert im.width == 500  # smaller than 720: never scaled up
    again = await client.get(f"/api/books/{sky['id']}/pages/10", params={"w": 700})
    assert again.content == page.content  # same size bucket, from the cache
    assert (await client.get(f"/api/books/{sky['id']}/pages/13")).status_code == 404
    assert (await client.get(f"/api/books/{sky['id']}/pages/0")).status_code == 404

    # folder of pages
    hero = reading["Hero Academy: Chapter 001"]
    assert (hero["format"], hero["pages"], hero["series_name"]) == ("images", 4, "Hero Academy")
    assert (await client.get(f"/api/books/{hero['id']}/pages/4")).status_code == 200
    assert (await client.get(f"/api/books/{hero['id']}/file")).status_code == 400

    if shutil.which("bsdtar"):
        tiger = reading["Tiger Tales 01"]
        assert (await client.get(f"/api/books/{tiger['id']}/pages/2")).headers["content-type"] == "image/webp"

    # reading progress with an EPUB location
    cfi = "epubcfi(/6/4!/4/2/1:0)"
    await client.put(f"/api/books/{river['id']}/progress", json={"position": 0, "locator": cfi, "fraction": 0.25})
    again = (await client.get(f"/api/books/{river['id']}")).json()
    assert again["progress"]["locator"] == cfi and again["progress"]["fraction"] == 0.25
    cont = (await client.get("/api/books/continue", params={"kind": "reading"})).json()
    assert [b["id"] for b in cont] == [river["id"]]
    assert (await client.delete(f"/api/books/{river['id']}/progress")).status_code == 204
    assert (await client.get("/api/books/continue")).json() == []

    # categories of other kinds don't show up in Watch
    assert (await client.get("/api/titles", params={"library_id": libs["Comics"]["id"]})).json() == []


async def test_age_limits_and_rescans(media_root, client, admin):
    libs = await _libs(client)
    await client.post("/api/users", json={"username": "kid", "password": "kidpassword1"})
    users = (await client.get("/api/users")).json()
    kid = next(u for u in users if u["username"] == "kid")
    await client.patch(f"/api/users/{kid['id']}", json={"max_age": 7})
    token = (await client.post("/api/auth/login", json={"username": "kid", "password": "kidpassword1"})).json()["token"]
    as_kid = {"Authorization": f"Bearer {token}"}

    # unrated categories are hidden from limited profiles
    assert (await client.get("/api/books", headers=as_kid)).json() == []
    assert (await client.get("/api/music/albums", headers=as_kid)).json() == []
    comic = (await client.get("/api/books", params={"kind": "comic"})).json()[0]
    assert (await client.get(f"/api/books/{comic['id']}/pages/1", headers=as_kid)).status_code == 404

    await client.patch(f"/api/libraries/{libs['Comics']['id']}", json={"age_rating": 7})
    kids_books = (await client.get("/api/books", headers=as_kid)).json()
    assert kids_books and {b["kind"] for b in kids_books} == {"comic"}
    assert (await client.get(f"/api/books/{comic['id']}/pages/1", headers=as_kid)).status_code == 200

    # a deleted file is marked missing on the next scan; a new one appears
    (media_root / "Comics" / "Moon Cat v01.cbz").unlink()
    sample.cbz(media_root / "Comics" / "Star Fox 01.cbz", "Star Fox", 1, info=False)
    await client.post(f"/api/libraries/{libs['Comics']['id']}/scan")
    await jobs.drain_local()
    titles = {b["title"] for b in (await client.get("/api/books", params={"kind": "comic"})).json()}
    assert "Moon Cat #1: Issue 1" not in titles and "Star Fox 01" in titles

    # switching a category's kind starts it over
    r = await client.patch(f"/api/libraries/{libs['Ebooks']['id']}", json={"kind": "comics"})
    assert r.status_code == 200
    await jobs.drain_local()
    assert len((await client.get("/api/books", params={"library_id": libs["Ebooks"]["id"]})).json()) == 4

    notes = (await client.get("/api/notifications")).json()
    assert any("new songs in Music" in n["title"] for n in notes["items"])
