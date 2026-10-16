"""Batch 2: tracks, transcoding to HLS, subtitles, offline copies, skip intro, age limits."""
from __future__ import annotations

import json
import subprocess

from app.services import jobs
from conftest import make_rich_video, make_video


async def add_library(client, path, name="Movies", kind="movies"):
    r = await client.post("/api/libraries", json={"name": name, "path": str(path), "kind": kind})
    assert r.status_code == 201, r.text
    await jobs.drain_local()
    return r.json()


async def rich_movie(client, tmp_path):
    make_rich_video(tmp_path / "movies" / "Dhaka Nights (2024)")
    lib = await add_library(client, tmp_path / "movies")
    return lib, (await client.get("/api/media")).json()[0]


async def test_tracks_and_chapter_markers(client, admin, tmp_path):
    _, m = await rich_movie(client, tmp_path)
    assert not m["browser_playable"]  # AC-3 audio in MKV
    assert (m["intro_start"], m["intro_end"]) == (0, 5) and m["credits_start"] == 15
    t = (await client.get(f"/api/media/{m['id']}/tracks")).json()
    assert [a["label"] for a in t["audio"]] == ["Bangla", "English"]
    subs = {s["id"]: s for s in t["subtitles"]}
    assert subs["e0"]["label"] == "Bangla" and subs["e0"]["usable"]
    assert subs["x0"]["label"] == "English"
    assert t["qualities"] == ["360p"] and t["encoder"] in ("libx264", "h264_nvenc")


async def test_subtitles_as_webvtt(client, admin, tmp_path):
    _, m = await rich_movie(client, tmp_path)
    emb = await client.get(f"/api/media/{m['id']}/subtitles/e0.vtt")
    assert emb.status_code == 200 and emb.text.startswith("WEBVTT") and "আমি বাংলায়" in emb.text
    side = await client.get(f"/api/media/{m['id']}/subtitles/x0.vtt")
    assert "Hello from the side file" in side.text
    assert (await client.get(f"/api/media/{m['id']}/subtitles/e9.vtt")).status_code == 404


def _probe(data: bytes, tmp_path) -> dict:
    f = tmp_path / "seg.ts"
    f.write_bytes(data)
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(f)],
                         capture_output=True, check=True).stdout
    return json.loads(out)


async def test_hls_playlist_segments_and_seeking(client, admin, tmp_path):
    _, m = await rich_movie(client, tmp_path)
    base = f"/api/media/{m['id']}/hls/360p/1"
    pl = (await client.get(f"{base}/index.m3u8")).text
    assert pl.startswith("#EXTM3U") and pl.count("#EXTINF") == 4 and "#EXT-X-ENDLIST" in pl
    first = await client.get(f"{base}/seg/0.ts")
    assert first.status_code == 200 and first.content[0] == 0x47  # MPEG-TS sync byte
    info = _probe(first.content, tmp_path)
    kinds = sorted(s["codec_type"] for s in info["streams"])
    assert kinds == ["audio", "video"]
    assert {s["codec_name"] for s in info["streams"]} == {"h264", "aac"}
    assert 5.0 <= float(info["format"]["duration"]) <= 7.0
    # jump to the last segment: ffmpeg restarts there and keeps the film's timeline
    last = await client.get(f"{base}/seg/3.ts")
    start = float(_probe(last.content, tmp_path)["format"]["start_time"])
    assert 17.5 <= start <= 19.9
    assert (await client.get(f"{base}/seg/9.ts")).status_code == 404
    act = (await client.get("/api/admin/activity")).json()
    assert act["transcodes"][0]["quality"] == "360p" and act["transcodes"][0]["viewers"] == ["mahbub"]


async def test_transcode_limit(client, admin, tmp_path, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "max_transcodes", 1)
    _, m = await rich_movie(client, tmp_path)
    assert (await client.get(f"/api/media/{m['id']}/hls/360p/0/seg/0.ts")).status_code == 200
    r = await client.get(f"/api/media/{m['id']}/hls/360p/1/seg/0.ts")
    assert r.status_code == 503 and "too many" in r.json()["detail"]


async def test_offline_copy(client, admin, tmp_path):
    _, m = await rich_movie(client, tmp_path)
    r = await client.post(f"/api/media/{m['id']}/offline", json={"quality": "360p"})
    assert r.status_code == 202
    await jobs.drain_local()
    copies = (await client.get(f"/api/media/{m['id']}/offline")).json()
    assert copies[0]["status"] == "ready" and copies[0]["progress"] == 1.0 and copies[0]["size"] > 0
    f = await client.get(f"/api/offline/{copies[0]['id']}/file")
    assert f.content[4:8] == b"ftyp"
    assert 'filename="Dhaka Nights (2024) 360p.mp4"' in f.headers["content-disposition"]
    notes = [n["title"] for n in (await client.get("/api/notifications")).json()["items"]]
    assert "Dhaka Nights is ready to download" in notes
    # asking again reuses the same copy
    again = (await client.post(f"/api/media/{m['id']}/offline", json={"quality": "360p"})).json()
    assert again["id"] == copies[0]["id"]
    assert (await client.delete(f"/api/offline/{copies[0]['id']}")).status_code == 204


async def test_series_intro_and_credits_markers(client, admin, tmp_path):
    for e in (1, 2):
        make_video(tmp_path / "shows" / "Mirzapur" / "Season 1" / f"Mirzapur.S01E0{e}.mp4", seconds=6)
    await add_library(client, tmp_path / "shows", "Web Series", "shows")
    sid = (await client.get("/api/titles")).json()[0]["id"]
    r = await client.put(f"/api/series/{sid}/markers", json={"intro_start": 1, "intro_end": 3, "credits_before_end": 2})
    assert r.json()["intro_end"] == 3
    ep = r.json()["seasons"][0]["episodes"][0]
    assert (ep["intro_start"], ep["intro_end"]) == (1, 3)
    assert abs(ep["credits_start"] - (ep["duration"] - 2)) < 0.01
    bad = await client.put(f"/api/series/{sid}/markers", json={"intro_start": 5, "intro_end": 3})
    assert bad.status_code == 400


async def test_kids_profile_age_limits(client, admin, tmp_path):
    make_video(tmp_path / "anim" / "Kung Fu Panda (2008).mp4")
    make_video(tmp_path / "anim" / "Coco (2017).mp4")
    lib = await add_library(client, tmp_path / "anim", "Animation")
    await client.post("/api/users", json={"username": "nabil", "password": "kidpassword"})
    kid_id = next(u["id"] for u in (await client.get("/api/users")).json() if u["username"] == "nabil")
    await client.patch(f"/api/users/{kid_id}", json={"max_age": 7})
    kid = {"Authorization": "Bearer " + (await client.post("/api/auth/login", json={
        "username": "nabil", "password": "kidpassword"})).json()["token"]}
    # unrated titles are hidden from a limited profile
    assert (await client.get("/api/titles", headers=kid)).json() == []
    # the category is marked suitable for 7+: both show up
    await client.patch(f"/api/libraries/{lib['id']}", json={"age_rating": 7})
    titles = {t["title"]: t for t in (await client.get("/api/titles", headers=kid)).json()}
    assert set(titles) == {"Kung Fu Panda", "Coco"} and titles["Coco"]["age"] == 7
    # one title is overridden to 13+: hidden everywhere for the kid, fine for the admin
    coco = titles["Coco"]["id"]
    await client.put(f"/api/media/{coco}/rating", json={"age_rating": 13})
    assert [t["title"] for t in (await client.get("/api/titles", headers=kid)).json()] == ["Kung Fu Panda"]
    for path in (f"/api/media/{coco}", f"/api/media/{coco}/stream", f"/api/media/{coco}/tracks",
                 f"/api/media/{coco}/hls/360p/0/index.m3u8", f"/api/media/{coco}/poster"):
        assert (await client.get(path, headers=kid)).status_code == 404, path
    assert (await client.get(f"/api/media/{coco}")).json()["age"] == 13
    # lifting the limit shows everything again
    await client.patch(f"/api/users/{kid_id}", json={"max_age": -1})
    assert len((await client.get("/api/titles", headers=kid)).json()) == 2


def test_certificates_map_to_ages():
    from app.services.ratings import cert_age, effective_age, pick_certification
    assert [cert_age(c) for c in ("U", "UA", "A", "PG-13", "TV-MA", "13+", "NR", None)] == [0, 13, 18, 13, 18, 13, None, None]
    assert effective_age(None, "PG", 16, None, 0) == 7  # the title's own certificate wins
    assert effective_age(None, None, None, None, 7) == 7
    results = [{"iso_3166_1": "US", "release_dates": [{"certification": "PG-13"}]},
               {"iso_3166_1": "IN", "release_dates": [{"certification": ""}, {"certification": "UA"}]}]
    assert pick_certification(results, "movie") == "UA"
    assert pick_certification([{"iso_3166_1": "US", "rating": "TV-14"}], "tv") == "TV-14"
