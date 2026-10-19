"""iPhone HEIC photos must show in every browser, the right way up, at full size too."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services import jobs
from conftest import jpeg_bytes
from test_api import upload

pillow_heif = pytest.importorskip("pillow_heif")
pillow_heif.register_heif_opener()


def heic_bytes(size=(800, 600), orientation: int | None = None) -> bytes:
    """A HEIC photo: left half red, right half blue, so a turned photo can be told apart."""
    im = Image.new("RGB", size, (220, 30, 30))
    im.paste((30, 30, 220), (size[0] // 2, 0, size[0], size[1]))
    kw = {}
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        kw["exif"] = exif.tobytes()
    buf = io.BytesIO()
    im.save(buf, "HEIF", quality=90, **kw)
    return buf.getvalue()


async def _heic_asset(client, name="IMG_0001.HEIC", **kw):
    data = heic_bytes(**kw)
    asset = (await upload(client, data, name))["asset"]
    await jobs.drain_local()
    assert asset["kind"] == "photo"
    return asset | {"data": data}


async def test_heic_full_size_view_is_a_jpeg(client, admin):
    a = await _heic_asset(client)
    r = await client.get(f"/api/assets/{a['id']}/file", params={"view": "true"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert "IMG_0001.jpg" in r.headers["content-disposition"]
    im = Image.open(io.BytesIO(r.content))
    assert im.format == "JPEG" and im.size == (800, 600)  # full size, not the 1920 px preview
    # cached: the second time is the same file
    assert (await client.get(f"/api/assets/{a['id']}/file", params={"view": "true"})).content == r.content
    # download still gives the untouched HEIC
    raw = await client.get(f"/api/assets/{a['id']}/file", params={"download": "true", "view": "true"})
    assert raw.content == a["data"]
    assert raw.headers["content-type"] != "image/jpeg"


async def test_heic_turned_photo_is_upright_everywhere(client, admin):
    a = await _heic_asset(client, name="turned.heic", orientation=6)
    for path in ("thumb", "preview"):
        im = Image.open(io.BytesIO((await client.get(f"/api/assets/{a['id']}/{path}")).content))
        assert im.height > im.width, path
    full = Image.open(io.BytesIO((await client.get(f"/api/assets/{a['id']}/file?view=true")).content))
    assert full.size == (600, 800)


async def test_other_photos_view_as_they_are(client, admin):
    data = jpeg_bytes()
    a = (await upload(client, data, "x.jpg"))["asset"]
    r = await client.get(f"/api/assets/{a['id']}/file", params={"view": "true"})
    assert r.content == data


async def test_heic_through_a_share_link(client, admin):
    a = await _heic_asset(client)
    link = (await client.post("/api/shares", json={"target_type": "asset", "target_id": a["id"]})).json()
    r = await client.get(f"/api/s/{link['token']}/assets/{a['id']}/file", params={"view": "true"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


async def test_photo_still_gets_a_thumbnail_when_its_details_cant_be_read(client, admin, monkeypatch):
    from app.services import media_tools

    def broken(_path):
        raise ValueError("odd EXIF")
    monkeypatch.setattr(media_tools, "image_info", broken)
    a = await _heic_asset(client)
    assert (await client.get(f"/api/assets/{a['id']}/thumb")).status_code == 200


async def test_missing_thumbnails_are_retried(client, admin):
    from sqlalchemy import update

    from app import db
    from app.models import Asset
    from app.services import storage

    a = await _heic_asset(client)
    # as if the first try had failed (or an older version couldn't read HEIC)
    storage.thumb_path(a["id"]).unlink()
    async with db.sessionmaker()() as session:
        await session.execute(update(Asset).where(Asset.id == a["id"]).values(thumb_ready=False))
        await session.commit()
    assert (await client.get(f"/api/assets/{a['id']}/thumb")).status_code == 404
    assert await jobs.retry_missing_thumbs() == 1
    await jobs.drain_local()
    assert (await client.get(f"/api/assets/{a['id']}/thumb")).status_code == 200
    assert await jobs.retry_missing_thumbs() == 0
