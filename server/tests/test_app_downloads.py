"""The Android app is hosted by ZiraHive: the admin uploads it, phones check the version."""
from __future__ import annotations

import io
import json
import zipfile


def apk(code: int, name: str, with_version: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00binary")
        z.writestr("classes.dex", b"dex\n035")
        if with_version:
            z.writestr("assets/zirahive-version.json", json.dumps({"version_code": code, "version_name": name}))
    return buf.getvalue()


async def test_no_app_yet(client):
    assert (await client.get("/api/app/android")).status_code == 404
    assert (await client.get("/api/app/android/apk")).status_code == 404


async def test_upload_and_download(client, admin):
    r = await client.put("/api/admin/app/android", content=apk(105, "1.0.5"))
    assert r.status_code == 200, r.text
    assert r.json()["version_code"] == 105
    client.headers.pop("Authorization")  # a new phone isn't signed in yet
    client.cookies.clear()
    info = (await client.get("/api/app/android")).json()
    assert info["version_name"] == "1.0.5" and info["size"] > 0
    d = await client.get("/api/app/android/apk")
    assert d.status_code == 200 and d.content == apk(105, "1.0.5")
    assert d.headers["content-type"] == "application/vnd.android.package-archive"
    assert "ZiraHive-1.0.5.apk" in d.headers["content-disposition"]


async def test_rejects_wrong_files_and_older_versions(client, admin):
    assert (await client.put("/api/admin/app/android", content=b"not a zip")).status_code == 400
    assert (await client.put("/api/admin/app/android", content=apk(5, "x", with_version=False))).status_code == 400
    assert (await client.put("/api/admin/app/android", content=apk(110, "1.1.0"))).status_code == 200
    r = await client.put("/api/admin/app/android", content=apk(105, "1.0.5"))
    assert r.status_code == 409
    assert (await client.get("/api/app/android")).json()["version_code"] == 110


async def test_only_admins_upload(client, admin):
    await client.post("/api/users", json={"username": "rina", "password": "supersecret"})
    client.headers.pop("Authorization")
    t = (await client.post("/api/auth/login", json={"username": "rina", "password": "supersecret"})).json()["token"]
    client.headers["Authorization"] = f"Bearer {t}"
    assert (await client.put("/api/admin/app/android", content=apk(1, "1"))).status_code == 403
