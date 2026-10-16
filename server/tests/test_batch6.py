"""Batch 6: words inside files (text and OCR), search, the scanner."""
from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.services import jobs, textsearch

needs_ocr = pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
BN_FONT = next(iter(sorted((Path(__file__).parents[2] / "web" / "node_modules" / "@fontsource" / "hind-siliguri" / "files")
                           .glob("*bengali-500-normal.woff"))), None) if (Path(__file__).parents[2] / "web" / "node_modules").is_dir() else None
EN_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def picture_of_text(lines: list[str], font_path: str | None = None, size=(1400, 600), fmt="PNG") -> bytes:
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(font_path or EN_FONT, 48) if (font_path or Path(EN_FONT).exists()) else None
    for i, line in enumerate(lines):
        d.text((50, 50 + i * 90), line, font=font, fill="black")
    out = io.BytesIO()
    im.save(out, fmt)
    return out.getvalue()


def text_pdf(text: str) -> bytes:
    """A minimal real PDF with a text layer."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def docx(text: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()


async def upload(client, name: str, data: bytes, folder: str = "/Papers") -> dict:
    up = (await client.post("/api/uploads", json={"filename": name, "size": len(data), "folder": folder, "dedupe": False})).json()
    if up.get("status") == "uploading":
        up = (await client.patch(f"/api/uploads/{up['id']}", content=data, headers={"Upload-Offset": "0"})).json()
    return up["asset"]


def test_which_files_are_read(monkeypatch):
    assert textsearch.wanted("report.pdf", "/", "document")
    assert textsearch.wanted("notes.docx", "/", "document")
    assert textsearch.wanted("Screenshot_2026.png", "/Camera", "photo")
    assert textsearch.wanted("receipt.jpg", "/", "photo")
    assert not textsearch.wanted("IMG_2041.jpg", "/Camera", "photo")  # holiday photos: not in "documents" mode
    assert not textsearch.wanted("song.mp3", "/", "other")
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "ocr", "all")
    assert textsearch.wanted("IMG_2041.jpg", "/Camera", "photo")
    monkeypatch.setattr(get_settings(), "ocr", "off")
    assert not textsearch.wanted("report.pdf", "/", "document")


@needs_ocr
async def test_search_inside_files(client, admin):
    await upload(client, "tax-2025.pdf", text_pdf("National Board of Revenue return 4471"))
    await upload(client, "letter.docx", docx("Dear landlord, the rent for Dhanmondi is paid"))
    await upload(client, "notes.txt", "Remember to renew the passport at Agargaon".encode())
    await upload(client, "Screenshot_bill.png", picture_of_text(["DESCO electricity bill", "Total due 1450 Taka"]))
    scanned = Image.open(io.BytesIO(picture_of_text(["Land deed copy", "Mouza Savar plot 77"], size=(1240, 1754))))
    buf = io.BytesIO()
    scanned.save(buf, "PDF")
    await upload(client, "deed-scan.pdf", buf.getvalue())
    await upload(client, "IMG_2041.jpg", picture_of_text(["Beach sign Kuakata"], fmt="JPEG"), folder="/Camera")
    if BN_FONT:
        await upload(client, "বিল.png", picture_of_text(["বিদ্যুৎ বিল জমা দেওয়া হয়েছে"], str(BN_FONT)))
    await jobs.drain_local()

    async def find(q):
        return {h["asset"]["filename"]: h for h in (await client.get("/api/search", params={"q": q})).json()}

    assert "tax-2025.pdf" in await find("4471")                     # PDF with text
    assert "letter.docx" in await find("dhanmondi")                 # Word, any case
    assert "notes.txt" in await find("Agargaon")
    hit = (await find("electricity"))["Screenshot_bill.png"]        # OCR of a screenshot
    assert hit["in_text"] and "electricity bill" in hit["snippet"].lower()
    assert "deed-scan.pdf" in await find("Savar")                   # OCR of a scanned PDF
    assert await find("Kuakata") == {}                              # camera photos aren't read
    assert "tax-2025.pdf" in await find("tax-20")                   # names count too
    if BN_FONT:
        hit = (await find("বিদ্যুৎ"))["বিল.png"]                     # Bangla
        assert "বিদ্যুৎ বিল" in hit["snippet"]
    text = (await client.get(f"/api/assets/{hit['asset']['id']}/text")).json()
    assert text["method"] == "ocr" and text["text"]

    # trashed files and other people's files don't show
    await client.delete(f"/api/assets/{(await find('4471'))['tax-2025.pdf']['asset']['id']}")
    assert await find("4471") == {}
    await client.post("/api/users", json={"username": "rina", "password": "rinapassword"})
    token = (await client.post("/api/auth/login", json={"username": "rina", "password": "rinapassword"})).json()["token"]
    other = (await client.get("/api/search", params={"q": "electricity"}, headers={"Authorization": f"Bearer {token}"})).json()
    assert other == []


@needs_ocr
async def test_scanner_makes_a_searchable_pdf(client, admin):
    scan = (await client.post("/api/scans")).json()
    page1 = picture_of_text(["Bank statement October", "Account ending 9921"], size=(1240, 1754), fmt="JPEG")
    page2 = picture_of_text(["Page two", "Closing balance 52000"], size=(1240, 1754), fmt="JPEG")
    assert (await client.put(f"/api/scans/{scan['id']}/pages/1", content=page1)).status_code == 204
    assert (await client.put(f"/api/scans/{scan['id']}/pages/2", content=page2)).status_code == 204
    assert (await client.put(f"/api/scans/{scan['id']}/pages/3", content=b"not a picture")).status_code == 415
    asset = (await client.post(f"/api/scans/{scan['id']}/finish", json={"title": "Bank statement"})).json()
    assert (asset["filename"], asset["folder"], asset["kind"]) == ("Bank statement.pdf", "/Scans", "document")

    pdf = (await client.get(f"/api/assets/{asset['id']}/file")).content
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2
    assert "9921" in reader.pages[0].extract_text()  # the text layer makes it searchable anywhere
    hits = (await client.get("/api/search", params={"q": "closing balance"})).json()
    assert [h["asset"]["id"] for h in hits] == [asset["id"]]
    assert (await client.post(f"/api/scans/{scan['id']}/finish", json={"title": "again"})).status_code == 400


async def test_text_backfill(client, admin, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "ocr", "off")
    await upload(client, "old.txt", b"written before search existed")
    await jobs.drain_local()
    assert (await client.get("/api/search", params={"q": "before search"})).json() == []
    monkeypatch.setattr(get_settings(), "ocr", "documents")
    assert await jobs.text_backfill(None) == 1
    assert len((await client.get("/api/search", params={"q": "before search"})).json()) == 1
    assert await jobs.text_backfill(None) == 0


async def test_pick_category_folders_from_drives(client, admin, tmp_path):
    """Media stays where it is: any folder on a listed drive can be a category; nothing else can."""
    drives = tmp_path / "drives"
    for letter in ("e", "f"):
        (drives / letter).mkdir()
    (drives / "f" / ".gharbox-no-drive").write_text("")  # a drive not listed in .env
    (drives / "e" / "Movies" / "English").mkdir(parents=True)
    (drives / "e" / "Movies" / "Web Series").mkdir(parents=True)
    (drives / "e" / "$RECYCLE.BIN").mkdir()
    (drives / "e" / "Songs").mkdir()

    top = (await client.get("/api/admin/folders")).json()
    labels = [f["label"] for f in top["folders"]]
    assert "E:" in labels and "F:" not in labels and top["path"] is None
    e = next(f for f in top["folders"] if f["label"] == "E:")
    inside = (await client.get("/api/admin/folders", params={"path": e["path"]})).json()
    assert [f["name"] for f in inside["folders"]] == ["Movies", "Songs"] and inside["parent"] is None
    assert next(f for f in inside["folders"] if f["name"] == "Songs")["guess"] == "music"
    movies = (await client.get("/api/admin/folders", params={"path": inside["folders"][0]["path"]})).json()
    series = next(f for f in movies["folders"] if f["name"] == "Web Series")
    assert series["label"] == "E:\\Movies\\Web Series" and series["guess"] == "shows"
    assert movies["parent"] == e["path"]

    lib = (await client.post("/api/libraries", json={"name": "Web Series", "path": series["path"], "kind": "shows"})).json()
    assert lib["display_path"] == "E:\\Movies\\Web Series"

    # GharBox's own data folder on a shared drive: hidden, refused, and skipped by scans
    data_on_e = drives / "e" / "GharBoxData"
    (data_on_e / "storage" / "rina").mkdir(parents=True)
    (data_on_e / ".gharbox-data").write_text("")
    (data_on_e / "storage" / "rina" / "private.mp4").write_bytes(b"x")
    inside = (await client.get("/api/admin/folders", params={"path": e["path"]})).json()
    assert "GharBoxData" not in [f["name"] for f in inside["folders"]]
    assert (await client.post("/api/libraries", json={"name": "X", "path": str(data_on_e / "storage")})).status_code == 400
    whole = (await client.post("/api/libraries", json={"name": "All of E", "path": e["path"], "kind": "movies"})).json()
    from app.services import jobs
    await jobs.drain_local()
    assert all("private" not in m["title"] for m in (await client.get("/api/media")).json())
    await client.delete(f"/api/libraries/{whole['id']}")

    # GharBox's own data, system folders and ../ tricks can't be picked
    from app.config import get_settings
    for bad in (str(get_settings().data_dir.parent.parent / "etc"), "/etc", str(drives / "e" / ".." / ".." / "..")):
        assert (await client.post("/api/libraries", json={"name": "X", "path": bad})).status_code == 400
    assert (await client.get("/api/admin/folders", params={"path": "/etc"})).status_code == 404

    # members can't browse the server's drives
    await client.post("/api/users", json={"username": "rina", "password": "rinapassword"})
    token = (await client.post("/api/auth/login", json={"username": "rina", "password": "rinapassword"})).json()["token"]
    assert (await client.get("/api/admin/folders", headers={"Authorization": f"Bearer {token}"})).status_code == 403

