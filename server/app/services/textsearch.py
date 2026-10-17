"""Words inside files: text from PDFs, Word, OpenDocument and plain text files, and OCR
(Tesseract, Bangla and English) for scans, screenshots and pictures of documents.
Files then searches inside them."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from ..config import get_settings

log = logging.getLogger(__name__)

MAX_TEXT = 200_000
MAX_OCR_PAGES = 40
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".srt", ".html", ".htm", ".xml"}
OFFICE_XML = {".docx": "word/document.xml", ".pptx": None, ".xlsx": "xl/sharedStrings.xml",
              ".odt": "content.xml", ".ods": "content.xml", ".odp": "content.xml"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".gif"}
_DOCLIKE = re.compile(r"scan|screenshot|screen shot|receipt|invoice|document|doc|bill|cert|id[ _-]?card|passport|"
                      r"nid|license|licence|memo|letter|statement|whatsapp image", re.I)


def tesseract() -> str | None:
    return shutil.which("tesseract")


def wanted(filename: str, folder: str, kind: str) -> bool:
    """Which files get their words read, depending on ZIRAHIVE_OCR."""
    mode = get_settings().ocr
    ext = PurePosixPath(filename).suffix.lower()
    if mode == "off":
        return False
    if ext == ".pdf" or ext in TEXT_EXT or ext in OFFICE_XML:
        return True
    if ext not in IMAGE_EXT:
        return False
    if mode == "all":
        return True
    # pictures that are probably of documents: screenshots, PNGs, scans, things put in Files folders
    return ext in (".png", ".tif", ".tiff") or bool(_DOCLIKE.search(f"{folder}/{filename}"))


def _clean(text: str) -> str:
    text = text.replace("\x00", " ").replace("\x0c", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_TEXT]


def _xml_text(data: bytes) -> str:
    s = data.decode("utf-8", "replace")
    s = re.sub(r"</(w:p|text:p|a:p|si)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    import html

    return html.unescape(s)


def ocr_image(path: Path) -> str:
    exe = tesseract()
    if not exe:
        return ""
    src = path
    with tempfile.TemporaryDirectory() as tmp:
        if path.suffix.lower() in (".heic", ".heif", ".webp", ".gif"):
            from PIL import Image

            try:
                from pillow_heif import register_heif_opener

                register_heif_opener()
            except Exception:
                pass
            src = Path(tmp) / "page.png"
            with Image.open(path) as im:
                im.convert("RGB").save(src)
        try:
            out = subprocess.run([exe, str(src), "stdout", "-l", get_settings().ocr_languages, "--psm", "3"],
                                 capture_output=True, timeout=180, check=True)
            return out.stdout.decode("utf-8", "replace")
        except Exception as exc:
            log.info("OCR of %s failed: %s", path.name, exc)
            return ""


def _pdf_pages_ocr(path: Path, pages: int) -> str:
    exe = shutil.which("pdftoppm")
    if not exe or not tesseract():
        return ""
    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        for n in range(1, min(pages, MAX_OCR_PAGES) + 1):
            out = Path(tmp) / f"p{n}"
            try:
                subprocess.run([exe, "-f", str(n), "-l", str(n), "-r", "200", "-gray", "-singlefile", "-png", str(path),
                                str(out)], check=True, timeout=120, capture_output=True)
            except Exception:
                continue
            parts.append(ocr_image(out.with_suffix(".png")))
    return "\n\n".join(parts)


def extract(path: Path) -> tuple[str, str, int | None]:
    """(text, method, pages). method: text (the file had text), ocr, or none."""
    ext = path.suffix.lower()
    if ext in TEXT_EXT:
        data = path.read_bytes()[:MAX_TEXT * 2]
        text = data.decode("utf-8", "replace")
        if ext in (".html", ".htm", ".xml"):
            text = re.sub(r"<[^>]+>", " ", text)
        return _clean(text), "text", None
    if ext in OFFICE_XML:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if ext == ".pptx":
                slides = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n))
                text = "\n".join(_xml_text(z.read(n)) for n in slides[:200])
            else:
                text = _xml_text(z.read(OFFICE_XML[ext])) if OFFICE_XML[ext] in names else ""
        return _clean(text), "text", None
    if ext == ".pdf":
        pages = None
        text = ""
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted:
                reader.decrypt("")
            pages = len(reader.pages)
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:500])
        except Exception as exc:
            log.info("PDF text of %s: %s", path.name, exc)
        if pages and len(text.strip()) >= 25 * min(pages, 5):
            return _clean(text), "text", pages
        # little or no text: a scan. Read the pages.
        ocr = _pdf_pages_ocr(path, pages or 1)
        return _clean(ocr or text), "ocr" if ocr.strip() else "none", pages
    if ext in IMAGE_EXT:
        text = _clean(ocr_image(path))
        # a few stray letters from a holiday photo are noise, not text
        return (text, "ocr", None) if len(re.findall(r"\w{2,}", text)) >= 3 else ("", "none", None)
    return "", "none", None


def snippet(text: str, query: str, width: int = 160) -> str | None:
    i = text.lower().find(query.lower())
    if i < 0:
        return None
    start = max(0, i - width // 2)
    end = min(len(text), i + len(query) + width // 2)
    s = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("…" if start > 0 else "") + s + ("…" if end < len(text) else "")
