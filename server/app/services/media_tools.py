"""Thin wrappers around Pillow, ffprobe and ffmpeg."""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from ..config import get_settings

log = logging.getLogger(__name__)

try:  # HEIC/HEIF support (iPhone photos)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - optional dependency
    log.info("pillow-heif not installed; HEIC thumbnails disabled")

THUMB_SIZE = 512
_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306


@dataclass
class ProbeResult:
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    container: str | None = None
    creation_time: datetime | None = None


def image_info(path: Path) -> tuple[int | None, int | None, datetime | None]:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        width, height = im.size
        taken = None
        try:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(_EXIF_DATETIME_ORIGINAL) or exif.get(_EXIF_DATETIME)
            if raw:
                taken = datetime.strptime(str(raw).strip("\x00"), "%Y:%m:%d %H:%M:%S")
        except Exception:
            taken = None
    return width, height, taken


def make_image_thumb(src: Path, dest: Path, size: int = THUMB_SIZE) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.save(dest, "WEBP", quality=80)


def probe(path: Path) -> ProbeResult:
    s = get_settings()
    cmd = [s.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format",
           "-show_streams", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True, timeout=60).stdout
        data = json.loads(out or b"{}")
    except Exception as exc:
        log.warning("ffprobe failed for %s: %s", path, exc)
        return ProbeResult()
    res = ProbeResult()
    fmt = data.get("format", {})
    try:
        res.duration = float(fmt.get("duration")) if fmt.get("duration") else None
    except ValueError:
        pass
    res.container = (fmt.get("format_name") or "").split(",")[0] or None
    for st in data.get("streams", []):
        if st.get("codec_type") == "video" and res.video_codec is None and \
                st.get("disposition", {}).get("attached_pic") != 1:
            res.video_codec = st.get("codec_name")
            res.width, res.height = st.get("width"), st.get("height")
        elif st.get("codec_type") == "audio" and res.audio_codec is None:
            res.audio_codec = st.get("codec_name")
    ct = (fmt.get("tags") or {}).get("creation_time")
    if ct:
        try:
            res.creation_time = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        except ValueError:
            pass
    return res


def make_video_thumb(src: Path, dest: Path, at_seconds: float, size: int = THUMB_SIZE) -> bool:
    """Grab one frame with ffmpeg and save it as a WebP thumbnail."""
    s = get_settings()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.jpg")
    cmd = [s.ffmpeg_bin, "-y", "-v", "error", "-ss", f"{max(at_seconds, 0):.2f}", "-i", str(src),
           "-frames:v", "1", "-vf", f"scale='min({size * 2},iw)':-2", str(tmp)]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        make_image_thumb(tmp, dest, size)
        return True
    except Exception as exc:
        log.warning("ffmpeg thumbnail failed for %s: %s", src, exc)
        return False
    finally:
        tmp.unlink(missing_ok=True)


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
