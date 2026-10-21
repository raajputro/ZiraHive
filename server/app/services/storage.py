"""Paths, folder normalisation and file-type helpers for backed-up files."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from ..config import get_settings

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tif",
             ".tiff", ".dng", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".3gp", ".wmv", ".mts", ".m2ts",
             ".ts", ".flv", ".mpg", ".mpeg"}
DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".csv",
           ".odt", ".ods", ".odp", ".rtf", ".epub", ".json", ".xml", ".html"}

mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")

_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f\\]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


def kind_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in PHOTO_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    if ext in DOC_EXT:
        return "document"
    return "other"


def mime_for(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def safe_name(name: str) -> str:
    """A filename that is safe on Windows and Linux (the server may run on either)."""
    name = _BAD_CHARS.sub("_", name.replace("/", "_")).strip().strip(".")
    if not name or name.split(".")[0].lower() in _RESERVED:
        name = f"_{name or 'file'}"
    return name[:200]


def normalize_folder(folder: str | None) -> str:
    """'Documents//Tax/' -> '/Documents/Tax'. Rejects '..' so nobody escapes their space."""
    folder = (folder or "/").replace("\\", "/")
    parts = []
    for part in folder.split("/"):
        part = part.strip()
        if part in ("", "."):
            continue
        if part == "..":
            raise HTTPException(400, "Invalid folder path")
        parts.append(safe_name(part))
    return "/" + "/".join(parts)


def parent_folders(folder: str) -> list[str]:
    """'/a/b/c' -> ['/a', '/a/b', '/a/b/c']"""
    parts = [p for p in folder.split("/") if p]
    return ["/" + "/".join(parts[: i + 1]) for i in range(len(parts))]


def user_root(username: str) -> Path:
    return get_settings().storage_dir / safe_name(username)


def unique_target(username: str, folder: str, filename: str) -> tuple[Path, str]:
    """Pick a readable, non-clashing path: storage/<user>/<folder>/<name> (n).ext

    Files are stored under readable names so you can still browse your backups in
    Explorer even if ZiraHive is not running.
    """
    base_dir = user_root(username).joinpath(*[p for p in folder.split("/") if p])
    base_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(filename)
    stem, ext = Path(name).stem, Path(name).suffix
    candidate = base_dir / name
    n = 1
    while candidate.exists():
        candidate = base_dir / f"{stem} ({n}){ext}"
        n += 1
    rel = candidate.relative_to(get_settings().storage_dir)
    return candidate, str(PurePosixPath(*rel.parts))


def abs_storage_path(rel: str) -> Path:
    root = get_settings().storage_dir.resolve()
    path = (root / rel).resolve()
    if root not in path.parents:
        raise HTTPException(400, "Invalid storage path")
    return path


def thumb_path(asset_id: str) -> Path:
    return get_settings().cache_dir / "thumbs" / f"{asset_id}.webp"


def poster_path(media_id: str) -> Path:
    return get_settings().cache_dir / "posters" / f"{media_id}.webp"


def series_poster_path(series_id: str) -> Path:
    return get_settings().cache_dir / "posters" / f"series-{series_id}.webp"


def version_target(username: str, asset_id: str, filename: str) -> tuple[Path, str]:
    """Where an older copy of a document is kept: storage/.versions/<user>/<asset>/<time>-<name>"""
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    folder = get_settings().storage_dir / ".versions" / safe_name(username) / asset_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp}-{safe_name(filename)}"
    rel = path.relative_to(get_settings().storage_dir)
    return path, str(PurePosixPath(*rel.parts))


def preview_path(asset_id: str) -> Path:
    return get_settings().cache_dir / "previews" / f"{asset_id}.webp"


def fullview_path(asset_id: str) -> Path:
    """Full-size JPEG of a HEIC/HEIF photo, for browsers that can't open HEIC."""
    return get_settings().cache_dir / "fullview" / f"{asset_id}.jpg"


def cover_path(kind: str, item_id: str) -> Path:
    """Album and book covers: covers/album-<id>.webp, covers/book-<id>.webp"""
    return get_settings().cache_dir / "covers" / f"{kind}-{item_id}.webp"


def audio_cache_path(key: str) -> Path:
    """Audio converted once to MP3 for browsers (WMA, ALAC, APE, ...)."""
    return get_settings().cache_dir / "audio" / f"{key}.mp3"


def page_cache_path(book_id: str, page: int, width: int) -> Path:
    return get_settings().cache_dir / "pages" / book_id / f"{page}-{width}"
