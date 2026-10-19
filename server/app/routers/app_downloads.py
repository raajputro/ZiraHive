"""The Android app, hosted by ZiraHive itself (it isn't on a store).

The admin uploads a new APK in Settings; every phone running the app sees the newer version
number and offers to install it. The APK carries its version in assets/zirahive-version.json,
written by the build, so nothing has to be typed in.

The download and the version are public: the app holds nothing private, and someone setting up
a new phone needs to get it before they can sign in.
"""
from __future__ import annotations

import asyncio
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..config import get_settings
from ..models import User
from ..security import admin_user

router = APIRouter(prefix="/api", tags=["app"])

MAX_APK = 300 * 1024 * 1024
VERSION_FILE = "assets/zirahive-version.json"


def _dir() -> Path:
    return get_settings().data_dir / "apps"


def _apk() -> Path:
    return _dir() / "zirahive-android.apk"


def _info_path() -> Path:
    return _dir() / "zirahive-android.json"


def read_version(apk: Path) -> dict:
    """{version_code, version_name} from inside the APK, or ValueError when it isn't ours."""
    try:
        with zipfile.ZipFile(apk) as z:
            names = set(z.namelist())
            if "AndroidManifest.xml" not in names or VERSION_FILE not in names:
                raise ValueError("That isn't a ZiraHive app file (.apk from the ZiraHive build).")
            data = json.loads(z.read(VERSION_FILE))
    except zipfile.BadZipFile:
        raise ValueError("That isn't an app file (.apk).") from None
    code, name = data.get("version_code"), data.get("version_name")
    if not isinstance(code, int) or code < 1 or not isinstance(name, str):
        raise ValueError("The app file's version is missing.")
    return {"version_code": code, "version_name": name}


def current() -> dict | None:
    try:
        info = json.loads(_info_path().read_text())
    except (OSError, ValueError):
        return None
    return info if _apk().exists() else None


@router.get("/app/android")
async def android_version() -> dict:
    info = current()
    if info is None:
        raise HTTPException(404, "No Android app has been added to this ZiraHive yet")
    return info


@router.get("/app/android/apk")
async def android_apk():
    info = current()
    if info is None:
        raise HTTPException(404, "No Android app has been added to this ZiraHive yet")
    return FileResponse(_apk(), media_type="application/vnd.android.package-archive",
                        filename=f"ZiraHive-{info['version_name']}.apk")


@router.put("/admin/app/android")
async def upload_android(request: Request, _: User = Depends(admin_user)) -> dict:
    """The new APK as the request body. It replaces the old one only once it checks out."""
    folder = _dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".upload-{os.getpid()}-{id(request)}.apk"
    size = 0
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_APK:
                    raise HTTPException(413, "That file is too big to be the app")
                f.write(chunk)
        try:
            info = await asyncio.to_thread(read_version, tmp)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        old = current()
        if old and old["version_code"] > info["version_code"]:
            raise HTTPException(409, f"This ZiraHive already has a newer app ({old['version_name']}); phones would not install an older one.")
        info |= {"size": size, "added_at": datetime.now(timezone.utc).isoformat()}
        os.replace(tmp, _apk())
        _info_path().write_text(json.dumps(info))
        return info
    finally:
        tmp.unlink(missing_ok=True)
