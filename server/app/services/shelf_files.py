"""Reading music, audiobook, ebook and comic files: tags, covers, page lists, chapters.

Everything here is blocking (file I/O, small subprocesses) and is called through
asyncio.to_thread by the scanner and the API.
"""
from __future__ import annotations

import base64
import io
import logging
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from PIL import Image

log = logging.getLogger(__name__)

AUDIO_EXT = {".mp3", ".m4a", ".m4b", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav", ".wma",
             ".ape", ".aiff", ".aif", ".wv", ".alac", ".mka", ".webm"}
EBOOK_EXT = {".epub", ".pdf"}
COMIC_EXT = {".cbz", ".cbr", ".cb7", ".cbt"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
FOLDER_ART = ("cover", "folder", "front", "albumart", "album")
# Codecs every current browser plays as they are. The rest are converted once to AAC.
PLAYABLE = {"mp3", "aac", "flac", "vorbis", "opus", "pcm"}
AUDIO_MIME = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".aac": "audio/aac",
              ".flac": "audio/flac", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
              ".wav": "audio/wav", ".webm": "audio/webm"}
IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
              ".gif": "image/gif", ".bmp": "image/bmp", ".avif": "image/avif"}
MAX_META_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 200_000_000  # long webtoon strips are tall but legitimate


def natural_key(s: str) -> list:
    """'Page 2' sorts before 'Page 10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def clean_name(stem: str) -> str:
    s = re.sub(r"[_]+", " ", stem)
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return s or stem


def _first_int(value) -> int | None:
    if value is None:
        return None
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def _year(value) -> int | None:
    m = re.search(r"(1[5-9]\d{2}|20\d{2})", str(value or ""))
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ covers

def save_cover(data: bytes | None, dest: Path, size: int = 600) -> bool:
    """Any image bytes -> a small WebP. False when the bytes aren't a usable image."""
    if not data or len(data) > MAX_IMAGE_BYTES:
        return False
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size * 2))
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            im.save(tmp, "WEBP", quality=82)
            tmp.replace(dest)
        return True
    except Exception as exc:
        log.debug("cover %s: %s", dest.name, exc)
        return False


def folder_image(folder: Path, stem: str | None = None) -> bytes | None:
    """cover.jpg / folder.jpg next to the files, or an image named like the file."""
    try:
        images = sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT and p.is_file()),
                        key=lambda p: natural_key(p.name))
    except OSError:
        return None
    ranked = [p for p in images if stem and p.stem.lower() == stem.lower()]
    ranked += [p for p in images if p.stem.lower() in FOLDER_ART]
    ranked += [p for p in images if any(w in p.stem.lower() for w in FOLDER_ART)]
    for p in ranked:
        try:
            return p.read_bytes()
        except OSError:
            continue
    return None


# ------------------------------------------------------------------- audio

@dataclass
class AudioInfo:
    title: str | None = None
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    track: int | None = None
    disc: int | None = None
    year: int | None = None
    genre: str | None = None
    composer: str | None = None
    comment: str | None = None
    duration: float | None = None
    codec: str | None = None
    playable: bool = True


_EASY = {"title": "title", "artist": "artist", "albumartist": "album_artist", "album": "album",
         "genre": "genre", "composer": "composer", "comment": "comment", "description": "comment"}
_ASF = {"Title": "title", "Author": "artist", "WM/AlbumArtist": "album_artist", "WM/AlbumTitle": "album",
        "WM/Genre": "genre", "WM/Composer": "composer", "Description": "comment"}


def _codec_of(f) -> str | None:
    name = type(f).__name__.lower()
    if name == "mp4":
        c = (getattr(f.info, "codec", "") or "").lower()
        return "alac" if "alac" in c else "aac" if c.startswith("mp4a") or not c else c
    return {"mp3": "mp3", "easymp3": "mp3", "easymp4": "aac", "flac": "flac", "oggvorbis": "vorbis",
            "oggopus": "opus", "wave": "pcm", "asf": "wma", "aac": "aac", "monkeysaudio": "ape",
            "aiff": "aiff", "wavpack": "wavpack", "oggflac": "flac", "oggspeex": "speex"}.get(name, name)


def audio_info(path: Path) -> AudioInfo:
    info = AudioInfo()
    try:
        import mutagen

        raw = mutagen.File(path)
        if raw is not None:
            info.codec = _codec_of(raw)
            info.duration = float(raw.info.length) if getattr(raw.info, "length", None) else None
            easy = None
            try:
                easy = mutagen.File(path, easy=True)
            except Exception:
                easy = None
            tags = getattr(easy, "tags", None) if easy is not None else None
            mapping = _ASF if type(raw).__name__ == "ASF" else _EASY
            source = raw.tags if type(raw).__name__ == "ASF" else tags
            if source:
                for key, attr in mapping.items():
                    try:
                        val = source.get(key)
                    except Exception:
                        val = None
                    if val:
                        v = val[0] if isinstance(val, list) else val
                        text = str(getattr(v, "value", v)).strip()
                        if text and getattr(info, attr) is None:
                            setattr(info, attr, text)
                for key in ("tracknumber", "WM/TrackNumber"):
                    val = source.get(key) if hasattr(source, "get") else None
                    if val:
                        info.track = _first_int(getattr(val[0], "value", val[0]) if isinstance(val, list) else val)
                for key in ("discnumber", "WM/PartOfSet"):
                    val = source.get(key) if hasattr(source, "get") else None
                    if val:
                        info.disc = _first_int(getattr(val[0], "value", val[0]) if isinstance(val, list) else val)
                for key in ("date", "originaldate", "year", "WM/Year"):
                    val = source.get(key) if hasattr(source, "get") else None
                    if val:
                        info.year = _year(getattr(val[0], "value", val[0]) if isinstance(val, list) else val)
                        if info.year:
                            break
    except Exception as exc:
        log.debug("tags of %s: %s", path.name, exc)
    if info.codec is None or info.duration is None:
        from . import media_tools

        try:
            probed = media_tools.probe(path)
            info.duration = info.duration or probed.duration
            info.codec = info.codec or probed.audio_codec
        except Exception:
            pass
    if info.codec in ("pcm_s16le", "pcm_s24le", "pcm_f32le"):
        info.codec = "pcm"
    info.playable = info.codec in PLAYABLE and path.suffix.lower() in AUDIO_MIME
    return info


def embedded_art(path: Path) -> bytes | None:
    try:
        import mutagen
        from mutagen.flac import Picture

        f = mutagen.File(path)
        if f is None:
            return None
        if getattr(f, "pictures", None):  # FLAC
            return f.pictures[0].data
        tags = f.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):  # ID3
            pics = tags.getall("APIC")
            if pics:
                front = [p for p in pics if p.type == 3]
                return (front or pics)[0].data
        covr = tags.get("covr") if hasattr(tags, "get") else None
        if covr:
            return bytes(covr[0])
        block = tags.get("metadata_block_picture") if hasattr(tags, "get") else None
        if block:
            return Picture(base64.b64decode(block[0])).data
    except Exception as exc:
        log.debug("art of %s: %s", path.name, exc)
    return None


# ------------------------------------------------------------------- EPUB

_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/",
       "c": "urn:oasis:names:tc:opendocument:xmlns:container"}


@dataclass
class BookMeta:
    title: str | None = None
    author: str | None = None
    language: str | None = None
    description: str | None = None
    year: int | None = None
    series: str | None = None
    series_index: float | None = None
    pages: int | None = None
    cover: bytes | None = None
    page_names: list[str] = field(default_factory=list)
    rtl: bool = False


def _read_member(z: zipfile.ZipFile, name: str, limit: int = MAX_META_BYTES) -> bytes:
    info = z.getinfo(name)
    if info.file_size > limit:
        raise ValueError(f"{name} is too large")
    return z.read(info)


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"<[^>]+>", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:4000] or None


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def epub_meta(path: Path) -> BookMeta:
    meta = BookMeta()
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(_read_member(z, "META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", _NS)
        opf_path = rootfile.get("full-path") if rootfile is not None else None
        if not opf_path:
            return meta
        opf = ET.fromstring(_read_member(z, opf_path))
        md = opf.find("opf:metadata", _NS)
        if md is None:
            return meta
        text = lambda tag: (md.findtext(tag, namespaces=_NS) or "").strip() or None  # noqa: E731
        meta.title = text("dc:title")
        creators = [c.text.strip() for c in md.findall("dc:creator", _NS) if c.text and c.text.strip()]
        meta.author = ", ".join(creators[:3]) or None
        meta.language = text("dc:language")
        meta.description = _strip_html(text("dc:description"))
        meta.year = _year(text("dc:date"))
        cover_id = None
        for m in md.findall("opf:meta", _NS):
            name, content, prop = m.get("name"), m.get("content"), m.get("property")
            if name == "cover":
                cover_id = content
            elif name == "calibre:series":
                meta.series = content
            elif name == "calibre:series_index":
                meta.series_index = _float(content)
            elif prop == "belongs-to-collection" and m.text and not meta.series:
                meta.series = m.text.strip()
            elif prop == "group-position" and m.text and meta.series_index is None:
                meta.series_index = _float(m.text.strip())
        manifest = opf.find("opf:manifest", _NS)
        items = manifest.findall("opf:item", _NS) if manifest is not None else []
        href = None
        for it in items:
            if cover_id and it.get("id") == cover_id:
                href = it.get("href")
        if href is None:
            href = next((it.get("href") for it in items if "cover-image" in (it.get("properties") or "")), None)
        if href is None:
            href = next((it.get("href") for it in items if "cover" in (it.get("id", "") + it.get("href", "")).lower()
                         and (it.get("media-type") or "").startswith("image/")), None)
        if href:
            full = str(PurePosixPath(opf_path).parent / unquote(href)).lstrip("./") if "/" in opf_path else unquote(href)
            full = full.replace("\\", "/")
            try:
                meta.cover = _read_member(z, full, MAX_IMAGE_BYTES)
            except (KeyError, ValueError):
                pass
    return meta


# -------------------------------------------------------------------- PDF

def pdf_meta(path: Path, want_cover: bool = True) -> BookMeta:
    meta = BookMeta()
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return meta
        meta.pages = len(reader.pages)
        info = reader.metadata or {}
        meta.title = (str(info.get("/Title") or "").strip() or None)
        meta.author = (str(info.get("/Author") or "").strip() or None)
    except Exception as exc:
        log.debug("pdf %s: %s", path.name, exc)
    if want_cover:
        meta.cover = pdf_page_png(path, 1, 600)
    return meta


def pdf_page_png(path: Path, page: int, size: int) -> bytes | None:
    """Render one page with poppler's pdftoppm, when it's installed."""
    exe = shutil.which("pdftoppm")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "p"
        try:
            subprocess.run([exe, "-f", str(page), "-l", str(page), "-singlefile", "-png", "-scale-to", str(size),
                            str(path), str(out)], check=True, timeout=60, capture_output=True)
            return (out.with_suffix(".png")).read_bytes()
        except Exception as exc:
            log.debug("pdftoppm %s: %s", path.name, exc)
            return None


# ----------------------------------------------------------------- comics

def _is_page(name: str) -> bool:
    p = PurePosixPath(name)
    return (p.suffix.lower() in IMAGE_EXT and not any(part.startswith((".", "__MACOSX")) for part in p.parts))


def _bsdtar() -> str | None:
    return shutil.which("bsdtar")


def _glob_escape(name: str) -> str:
    return re.sub(r"([\[\]\*\?\\])", r"\\\1", name)


def comic_pages(path: Path) -> list[str]:
    """Image entries in reading order. `path` is an archive or a folder of images."""
    if path.is_dir():
        names = [p.name for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT]
    elif zipfile.is_zipfile(path):  # .cbz, and .cbr files that are really zips
        with zipfile.ZipFile(path) as z:
            names = [i.filename for i in z.infolist() if not i.is_dir() and _is_page(i.filename)]
    else:
        exe = _bsdtar()
        if not exe:
            raise RuntimeError("Reading .cbr/.cb7 comics needs bsdtar (libarchive-tools)")
        out = subprocess.run([exe, "-tf", str(path)], check=True, timeout=120, capture_output=True)
        names = [n for n in out.stdout.decode("utf-8", "replace").splitlines() if n and _is_page(n)]
    return sorted(names, key=natural_key)


def comic_page_bytes(path: Path, name: str) -> bytes:
    if path.is_dir():
        target = (path / name).resolve()
        if target.parent != path.resolve():
            raise ValueError("bad page")
        return target.read_bytes()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return _read_member(z, name, MAX_IMAGE_BYTES)
    exe = _bsdtar()
    if not exe:
        raise RuntimeError("bsdtar is not installed")
    out = subprocess.run([exe, "-xOf", str(path), "--", _glob_escape(name)], check=True, timeout=120,
                         capture_output=True)
    if len(out.stdout) > MAX_IMAGE_BYTES:
        raise ValueError("page too large")
    return out.stdout


def _comicinfo(xml: bytes, meta: BookMeta) -> None:
    root = ET.fromstring(xml)
    get = lambda tag: (root.findtext(tag) or "").strip() or None  # noqa: E731
    meta.series = get("Series")
    meta.series_index = _float(get("Number"))
    title, number = get("Title"), get("Number")
    if meta.series and number:
        meta.title = f"{meta.series} #{number}" + (f": {title}" if title else "")
    else:
        meta.title = title or meta.series
    meta.author = get("Writer")
    meta.year = _first_int(get("Year"))
    meta.description = _strip_html(get("Summary"))
    meta.language = get("LanguageISO")
    meta.rtl = (get("Manga") or "").lower() == "yesandrighttoleft"


def comic_meta(path: Path) -> BookMeta:
    meta = BookMeta()
    meta.page_names = comic_pages(path)
    meta.pages = len(meta.page_names)
    try:
        if path.is_dir():
            ci = path / "ComicInfo.xml"
            if ci.is_file():
                _comicinfo(ci.read_bytes()[:MAX_META_BYTES], meta)
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                name = next((n for n in z.namelist() if n.lower().endswith("comicinfo.xml")), None)
                if name:
                    _comicinfo(_read_member(z, name), meta)
    except Exception as exc:
        log.debug("ComicInfo in %s: %s", path.name, exc)
    if meta.page_names:
        try:
            meta.cover = comic_page_bytes(path, meta.page_names[0])
        except Exception as exc:
            log.debug("comic cover %s: %s", path.name, exc)
    return meta


_ISSUE = re.compile(r"^(?P<name>.*?\D)[ _\-#]*(?:v|vol\.?|volume|ch\.?|chapter|issue|#)?[ _]*"
                    r"(?P<num>\d{1,4}(?:\.\d+)?)(?:\s*[\(\[].*)?$", re.I)


def comic_series_from_name(stem: str) -> tuple[str | None, float | None]:
    """'One Piece v01' -> ('One Piece', 1); 'Batman 012 (2016)' -> ('Batman', 12)."""
    m = _ISSUE.match(clean_name(stem))
    if not m:
        return None, None
    name = re.sub(r"[ _\-#]*(?:v|vol\.?|volume|ch\.?|chapter|issue)$", "", m.group("name").strip(" _-#"), flags=re.I)
    return (name.strip() or None), _float(m.group("num"))


def resized_page(data: bytes, width: int | None, quality: int = 82) -> tuple[bytes, str]:
    """A page image, scaled down to `width` (never up), as WebP. Returns (bytes, mime)."""
    with Image.open(io.BytesIO(data)) as im:
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        if width and im.width > width:
            im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
        out = io.BytesIO()
        if im.height > 16383:  # WebP's limit; very long webtoon strips stay JPEG
            im.save(out, "JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
        im.save(out, "WEBP", quality=quality)
        return out.getvalue(), "image/webp"
