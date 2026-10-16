"""Audio browsers can't play (WMA, ALAC, APE, AIFF, ...) is converted once to MP3 and cached.
MP3 because every browser plays it, including ones without AAC (e.g. Chromium on Linux). The web
app also asks for a converted copy when a browser fails to play a file it should have managed.

The first request starts the conversion in the background and answers "not ready"; the web app
asks again every few seconds. Short songs are ready almost at once; a long audiobook part takes
a minute or two.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from ..config import get_settings
from . import storage

log = logging.getLogger(__name__)

_running: dict[str, asyncio.Task] = {}
_failed: dict[str, float] = {}
_slots = asyncio.Semaphore(2)
RETRY_AFTER_FAIL = 600


def ready_path(src: Path, key: str) -> Path | None:
    dest = storage.audio_cache_path(key)
    try:
        if dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime:
            os.utime(dest)  # keeps it from the cleanup of unused copies
            return dest
    except OSError:
        pass
    return None


async def _convert(src: Path, dest: Path, key: str) -> None:
    async with _slots:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.stem + ".part.mp3")
        # constant bitrate keeps seeking exact in every browser
        cmd = [get_settings().ffmpeg_bin, "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0",
               "-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-ac", "2", "-id3v2_version", "0", str(tmp)]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode == 0 and tmp.is_file():
            tmp.replace(dest)
            _failed.pop(key, None)
        else:
            tmp.unlink(missing_ok=True)
            _failed[key] = time.monotonic()
            log.warning("converting %s failed: %s", src.name, err.decode(errors="replace")[-300:])


def status(src: Path, key: str) -> tuple[bool, bool]:
    """(ready, failed). Starts the conversion when it isn't ready and isn't running."""
    if ready_path(src, key):
        return True, False
    failed_at = _failed.get(key)
    if failed_at and time.monotonic() - failed_at < RETRY_AFTER_FAIL:
        return False, True
    task = _running.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_convert(src, storage.audio_cache_path(key), key))
        _running[key] = task
        task.add_done_callback(lambda _t: _running.pop(key, None))
    return False, False


def purge_unused(days: int = 60) -> int:
    """Delete converted audio and comic pages nobody has opened for a while."""
    cutoff = time.time() - days * 86400
    removed = 0
    for folder in (storage.audio_cache_path("x").parent, get_settings().cache_dir / "pages"):
        if not folder.is_dir():
            continue
        for p in folder.rglob("*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                pass
    return removed
