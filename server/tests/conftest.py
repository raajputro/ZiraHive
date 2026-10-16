from __future__ import annotations

import io
import subprocess
from pathlib import Path

import httpx
import pytest
from PIL import Image


@pytest.fixture
async def app(tmp_path, monkeypatch):
    monkeypatch.setenv("GHARBOX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GHARBOX_REDIS_URL", "")
    monkeypatch.setenv("GHARBOX_DATABASE_URL", "")
    monkeypatch.setenv("GHARBOX_MEDIA_LIBRARIES", "")
    monkeypatch.setenv("GHARBOX_MAX_CHUNK_MB", "1")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    from app.security import login_ip_throttle, login_throttle, share_throttle
    login_ip_throttle._fails.clear()
    login_throttle._fails.clear()
    share_throttle._fails.clear()
    from app.services import activity
    activity._streams.clear()
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application
    get_settings.cache_clear()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin(client):
    r = await client.post("/api/setup", json={"username": "mahbub", "password": "supersecret"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return token


def jpeg_bytes(color=(200, 50, 50), taken="2023:12:24 18:30:00", size=(800, 600)) -> bytes:
    im = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[306] = taken
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def make_video(path: Path, seconds: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size=320x240:rate=15", "-f", "lavfi", "-i",
                    f"sine=duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path
