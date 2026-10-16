from __future__ import annotations

import hashlib

from app.services import jobs
from app.services.scanner import parse_movie_name
from app.services.storage import normalize_folder
from conftest import jpeg_bytes, make_video


async def upload(client, data: bytes, filename: str, folder="/", chunk=400_000, sha=True,
                 **extra):
    body = {"filename": filename, "size": len(data), "folder": folder, **extra}
    if sha:
        body["sha256"] = hashlib.sha256(data).hexdigest()
    r = await client.post("/api/uploads", json=body)
    assert r.status_code == 201, r.text
    res = r.json()
    if res["status"] == "exists":
        return res
    offset = 0
    while offset < len(data):
        piece = data[offset: offset + chunk]
        r = await client.patch(f"/api/uploads/{res['id']}", content=piece,
                               headers={"Upload-Offset": str(offset)})
        assert r.status_code == 200, r.text
        res = r.json()
        offset = res["offset"]
    return res


# ------------------------------------------------------------------ auth

async def test_setup_then_login(client):
    assert (await client.get("/api/setup/status")).json() == {"needs_setup": True}
    r = await client.post("/api/setup", json={"username": "Mahbub", "password": "supersecret"})
    assert r.status_code == 200 and r.json()["user"]["is_admin"]
    assert (await client.post("/api/setup", json={"username": "x2", "password": "supersecret"})
            ).status_code == 409
    assert (await client.post("/api/auth/login", json={"username": "mahbub", "password": "nope"})
            ).status_code == 401
    r = await client.post("/api/auth/login", json={"username": "MAHBUB", "password": "supersecret"})
    assert r.status_code == 200
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert me.json()["username"] == "mahbub"


async def test_requires_auth(client):
    assert (await client.get("/api/files")).status_code == 401
    assert (await client.get("/api/files", headers={"Authorization": "Bearer junk"})).status_code == 401


async def test_users_are_isolated(client, admin):
    r = await client.post("/api/users", json={"username": "rina", "password": "password12"})
    assert r.status_code == 201
    await upload(client, b"admin secret notes", "notes.txt")
    other = (await client.post("/api/auth/login",
                               json={"username": "rina", "password": "password12"})).json()["token"]
    listing = await client.get("/api/files", headers={"Authorization": f"Bearer {other}"})
    assert listing.json()["assets"] == []
    admin_files = (await client.get("/api/files")).json()["assets"]
    r = await client.get(f"/api/assets/{admin_files[0]['id']}/file",
                         headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 404
    # non-admins can't manage users
    assert (await client.get("/api/users", headers={"Authorization": f"Bearer {other}"})
            ).status_code == 403


# ---------------------------------------------------------------- uploads

async def test_chunked_upload_and_download(client, admin):
    data = bytes(range(256)) * 5000  # 1.28 MB, several chunks
    res = await upload(client, data, "blob.bin", folder="Backups/2024")
    assert res["status"] == "complete"
    asset = res["asset"]
    assert asset["folder"] == "/Backups/2024" and asset["size"] == len(data)
    r = await client.get(f"/api/assets/{asset['id']}/file")
    assert r.content == data
    r = await client.get(f"/api/assets/{asset['id']}/file", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == data[100:200]
    assert r.headers["content-range"] == f"bytes 100-199/{len(data)}"
    root = (await client.get("/api/files")).json()
    assert root["folders"] == ["/Backups"]
    sub = (await client.get("/api/files", params={"folder": "/Backups"})).json()
    assert sub["folders"] == ["/Backups/2024"]


async def test_resume_after_interruption(client, admin):
    data = b"x" * 900_000
    r = await client.post("/api/uploads", json={"filename": "a.bin", "size": len(data)})
    uid = r.json()["id"]
    await client.patch(f"/api/uploads/{uid}", content=data[:300_000], headers={"Upload-Offset": "0"})
    # client "crashes" and asks where to continue
    assert (await client.get(f"/api/uploads/{uid}")).json()["offset"] == 300_000
    # sending from a stale offset is rejected
    r = await client.patch(f"/api/uploads/{uid}", content=data[:10], headers={"Upload-Offset": "0"})
    assert r.status_code == 409
    r = await client.patch(f"/api/uploads/{uid}", content=data[300_000:],
                           headers={"Upload-Offset": "300000"})
    assert r.json()["status"] == "complete"


async def test_dedup_by_hash(client, admin):
    data = b"same bytes" * 1000
    first = await upload(client, data, "one.txt")
    digest = hashlib.sha256(data).hexdigest()
    check = await client.post("/api/uploads/check", json={"sha256": [digest, "0" * 64]})
    assert check.json()["existing"] == [digest]
    again = await upload(client, data, "copy.txt")
    assert again["status"] == "exists" and again["asset"]["id"] == first["asset"]["id"]
    # without a client hash the server still detects the duplicate at the end
    again = await upload(client, data, "copy2.txt", sha=False)
    assert again["status"] == "exists"
    assert len((await client.get("/api/files")).json()["assets"]) == 1


async def test_checksum_mismatch_rejected(client, admin):
    data = b"hello world"
    r = await client.post("/api/uploads", json={"filename": "h.txt", "size": len(data),
                                                 "sha256": "a" * 64})
    r = await client.patch(f"/api/uploads/{r.json()['id']}", content=data,
                           headers={"Upload-Offset": "0"})
    assert r.status_code == 422


async def test_oversized_chunk_rejected(client, admin):
    r = await client.post("/api/uploads", json={"filename": "big.bin", "size": 5})
    r = await client.patch(f"/api/uploads/{r.json()['id']}", content=b"123456789",
                           headers={"Upload-Offset": "0"})
    assert r.status_code == 413


async def test_name_clash_keeps_both(client, admin):
    a = await upload(client, b"first", "report.pdf")
    b = await upload(client, b"second", "report.pdf")
    assert a["asset"]["filename"] == "report.pdf"
    assert b["asset"]["filename"] == "report (1).pdf"


async def test_path_traversal_blocked(client, admin):
    r = await client.post("/api/uploads", json={"filename": "x.txt", "size": 1,
                                                 "folder": "../../etc"})
    assert r.status_code == 400
    assert normalize_folder("a//b/./c/") == "/a/b/c"


async def test_empty_file(client, admin):
    r = await client.post("/api/uploads", json={"filename": "empty.txt", "size": 0})
    assert r.json()["status"] == "complete"


# --------------------------------------------------------- files & trash

async def test_rename_move_trash_restore(client, admin):
    asset = (await upload(client, b"doc", "tax.pdf"))["asset"]
    assert asset["kind"] == "document"
    r = await client.patch(f"/api/assets/{asset['id']}", json={"folder": "/Docs", "filename": "tax-2024.pdf"})
    assert r.json()["folder"] == "/Docs" and r.json()["filename"] == "tax-2024.pdf"
    assert (await client.get(f"/api/assets/{asset['id']}/file")).content == b"doc"
    await client.delete(f"/api/assets/{asset['id']}")
    assert (await client.get("/api/files", params={"folder": "/Docs"})).json()["assets"] == []
    assert len((await client.get("/api/trash")).json()) == 1
    await client.post(f"/api/trash/{asset['id']}/restore")
    assert len((await client.get("/api/files", params={"folder": "/Docs"})).json()["assets"]) == 1
    await client.delete(f"/api/assets/{asset['id']}")
    assert (await client.delete(f"/api/trash/{asset['id']}")).status_code == 204
    assert (await client.get(f"/api/assets/{asset['id']}")).status_code == 404


async def test_delete_folder_moves_contents_to_trash(client, admin):
    await upload(client, b"1", "a.txt", folder="/Old/Sub")
    await client.post("/api/folders", json={"path": "/Old/Empty"})
    assert (await client.delete("/api/folders", params={"path": "/Old"})).status_code == 204
    assert (await client.get("/api/files")).json()["folders"] == []
    assert len((await client.get("/api/trash")).json()) == 1


# ----------------------------------------------------------------- photos

async def test_photo_processing_and_timeline(client, admin, tmp_path):
    p1 = await upload(client, jpeg_bytes(taken="2023:12:24 18:30:00"), "IMG_1.jpg", folder="/Camera")
    p2 = await upload(client, jpeg_bytes((10, 200, 10), taken="2024:06:01 09:00:00"), "IMG_2.jpg",
                      folder="/Camera")
    video = make_video(tmp_path / "clip.mp4").read_bytes()
    v = await upload(client, video, "VID_1.mp4", folder="/Camera",
                     taken_at="2022-01-01T10:00:00Z")
    await jobs.drain_local()
    page = (await client.get("/api/photos", params={"limit": 2})).json()
    ids = [i["id"] for i in page["items"]]
    assert ids == [p2["asset"]["id"], p1["asset"]["id"]]  # newest first, by EXIF date
    assert page["items"][0]["width"] == 800 and page["items"][0]["thumb_ready"]
    page2 = (await client.get("/api/photos", params={"cursor": page["next_cursor"]})).json()
    assert [i["id"] for i in page2["items"]] == [v["asset"]["id"]]
    assert page2["next_cursor"] is None
    vid = page2["items"][0]
    assert vid["kind"] == "video" and vid["duration"] and vid["thumb_ready"]
    thumb = await client.get(f"/api/assets/{vid['id']}/thumb")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"


async def test_cookie_and_query_token_auth(client, admin):
    asset = (await upload(client, jpeg_bytes(), "x.jpg"))["asset"]
    await jobs.drain_local()
    token = client.headers.pop("Authorization").split()[1]
    r = await client.get(f"/api/assets/{asset['id']}/thumb", params={"token": token})
    assert r.status_code == 200


# ------------------------------------------------------------------ media

def test_parse_movie_names():
    assert parse_movie_name("The.Matrix.1999.1080p.BluRay.x264.mkv") == ("The Matrix", 1999)
    assert parse_movie_name("Inception (2010).mp4") == ("Inception", 2010)
    assert parse_movie_name("Blade Runner 2049 (2017).mkv") == ("Blade Runner 2049", 2017)
    assert parse_movie_name("Aynabaji.2016.720p.WEB-DL.mkv") == ("Aynabaji", 2016)
    assert parse_movie_name("Some_Movie_1080p_x265.mkv") == ("Some Movie", None)


async def test_library_scan_stream_and_progress(client, admin, tmp_path):
    movies = tmp_path / "movies"
    (movies / "Inception (2010)").mkdir(parents=True)
    make_video(movies / "Inception (2010)" / "Inception (2010).mp4", seconds=3)
    make_video(movies / "sample.mp4")  # samples are ignored
    r = await client.post("/api/libraries", json={"name": "Movies", "path": str(movies)})
    assert r.status_code == 201, r.text
    await jobs.drain_local()
    libs = (await client.get("/api/libraries")).json()
    assert libs[0]["item_count"] == 1
    items = (await client.get("/api/media")).json()
    m = items[0]
    assert (m["title"], m["year"]) == ("Inception", 2010)
    assert m["browser_playable"] and m["poster_ready"] and m["duration"] > 2
    r = await client.get(f"/api/media/{m['id']}/stream", headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206 and len(r.content) == 1024
    assert r.headers["content-type"] == "video/mp4"
    assert (await client.get(f"/api/media/{m['id']}/poster")).status_code == 200
    await client.put(f"/api/media/{m['id']}/progress", json={"position": 1.2})
    assert (await client.get(f"/api/media/{m['id']}")).json()["position"] == 1.2
    # rescan with no changes keeps the same item; deleting the file marks it missing
    (movies / "Inception (2010)" / "Inception (2010).mp4").unlink()
    await client.post(f"/api/libraries/{libs[0]['id']}/scan")
    await jobs.drain_local()
    assert (await client.get("/api/media")).json() == []


async def test_library_path_must_exist(client, admin):
    r = await client.post("/api/libraries", json={"name": "X", "path": "/does/not/exist"})
    assert r.status_code == 400


async def test_admin_stats(client, admin):
    await upload(client, jpeg_bytes(), "a.jpg")
    s = (await client.get("/api/admin/stats")).json()
    assert s["photos"] == 1 and s["users"] == 1 and s["disk_free"] > 0


async def test_signed_stream_link(client, admin, tmp_path):
    movies = tmp_path / "m"
    movies.mkdir()
    make_video(movies / "Clip (2020).mp4")
    await client.post("/api/libraries", json={"name": "M", "path": str(movies)})
    await jobs.drain_local()
    mid = (await client.get("/api/media")).json()[0]["id"]
    path = (await client.get(f"/api/media/{mid}/link")).json()["path"]
    client.headers.pop("Authorization")
    client.cookies.clear()
    assert (await client.get(f"/api/media/{mid}/stream")).status_code == 401
    r = await client.get(path, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
