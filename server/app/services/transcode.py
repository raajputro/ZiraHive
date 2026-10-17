"""On-the-fly transcoding to HLS, and smaller MP4 copies for offline viewing.

How streaming works (same idea as Jellyfin):
- The player gets a playlist listing every 6-second segment of the whole film up front, so the
  seek bar shows the real length and you can jump anywhere.
- Segments are made by ffmpeg only when asked for. Asking for a segment far from what's being
  encoded restarts ffmpeg at that point (-ss), with timestamps kept on the film's timeline so
  subtitles and the seek bar stay in sync.
- Forced keyframes every 6 s make every segment exactly 6 s, matching the playlist.
- ffmpeg is paused when it's far ahead of the viewer and stopped when nobody is watching.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings

log = logging.getLogger(__name__)

SEGMENT = 6.0
# name: (max height, video kbit/s, audio kbit/s)
QUALITIES: dict[str, tuple[int, int, int]] = {
    "1080p": (1080, 8000, 192),
    "720p": (720, 4000, 160),
    "480p": (480, 1500, 128),
    "360p": (360, 700, 96),
}
AHEAD_PAUSE = 30   # pause ffmpeg when this many segments ahead of the viewer
AHEAD_RESUME = 12  # ...and continue when the viewer gets this close
IDLE_STOP = 90     # seconds without a request before a session is stopped and cleaned up
WAIT_SEGMENT = 45  # seconds to wait for a segment before giving up


class TooBusy(Exception):
    pass


def qualities_for(height: int | None) -> list[str]:
    """Qualities worth offering for a source: nothing bigger than the source itself."""
    h = height or 1080
    out = [q for q, (qh, _, _) in QUALITIES.items() if qh <= max(h, 360)]
    return out or ["360p"]


def segment_count(duration: float) -> int:
    return max(1, math.ceil(duration / SEGMENT))


def playlist(duration: float, query: str = "") -> str:
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{math.ceil(SEGMENT)}",
             "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS"]
    n = segment_count(duration)
    for i in range(n):
        length = min(SEGMENT, duration - i * SEGMENT) if i == n - 1 else SEGMENT
        lines += [f"#EXTINF:{max(length, 0.1):.3f},", f"seg/{i}.ts{query}"]
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ encoder choice

_encoder: str | None = None


def encoder() -> str:
    """'h264_nvenc' when an NVIDIA GPU works inside the container, else 'libx264'."""
    global _encoder
    if _encoder:
        return _encoder
    mode = get_settings().hw_accel.lower()
    _encoder = "libx264"
    if mode in ("auto", "nvenc"):
        test = [get_settings().ffmpeg_bin, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
                "-c:v", "h264_nvenc", "-f", "null", "-"]
        try:
            if subprocess.run(test, capture_output=True, timeout=20).returncode == 0:
                _encoder = "h264_nvenc"
        except Exception:
            pass
        if mode == "nvenc" and _encoder != "h264_nvenc":
            log.warning("ZIRAHIVE_HW_ACCEL=nvenc but the NVIDIA encoder doesn't work here; using the CPU")
    log.info("video encoder: %s", _encoder)
    return _encoder


def video_args(quality: str, src_height: int | None, keyframes_every: float | None = SEGMENT) -> list[str]:
    qh, vb, _ = QUALITIES[quality]
    height = min(qh, src_height or qh)
    height -= height % 2
    args = ["-vf", f"scale=-2:{height}", "-pix_fmt", "yuv420p"]
    if encoder() == "h264_nvenc":
        args += ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "24", "-b:v", f"{vb}k",
                 "-maxrate", f"{vb}k", "-bufsize", f"{vb * 2}k", "-profile:v", "high", "-no-scenecut", "1"]
        if keyframes_every:
            args += ["-forced-idr", "1"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", f"{vb}k",
                 "-bufsize", f"{vb * 2}k", "-profile:v", "high", "-level", "4.1", "-sc_threshold", "0"]
    if keyframes_every:
        args += ["-force_key_frames", f"expr:gte(t,n_forced*{keyframes_every:g})"]
    return args


def audio_args(quality: str, audio_index: int) -> list[str]:
    _, _, ab = QUALITIES[quality]
    return ["-map", f"0:a:{audio_index}?", "-c:a", "aac", "-ac", "2", "-b:a", f"{ab}k"]


# ------------------------------------------------------------- HLS sessions

@dataclass
class Session:
    key: str
    media_id: str
    title: str
    source: Path
    duration: float
    height: int | None
    quality: str
    audio: int
    folder: Path
    proc: asyncio.subprocess.Process | None = None
    start_segment: int = 0
    last_requested: int = 0
    last_access: float = field(default_factory=time.monotonic)
    paused: bool = False
    viewers: set[str] = field(default_factory=set)

    def latest_written(self) -> int:
        best = self.start_segment - 1
        try:
            for name in os.listdir(self.folder):
                if name.endswith(".ts") and name[:-3].isdigit():
                    best = max(best, int(name[:-3]))
        except FileNotFoundError:
            pass
        return best

    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None


class TranscodeManager:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._janitor: asyncio.Task | None = None

    @property
    def root(self) -> Path:
        return get_settings().cache_dir / "transcode"

    def start_janitor(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)  # leftovers from a previous run
        self._janitor = asyncio.create_task(self._janitor_loop())

    async def shutdown(self) -> None:
        if self._janitor:
            self._janitor.cancel()
        for s in list(self.sessions.values()):
            await self._stop(s)
        self.sessions.clear()
        self._locks.clear()

    def session(self, media_id: str, title: str, source: Path, duration: float, height: int | None,
                quality: str, audio: int, viewer: str) -> Session:
        key = f"{media_id}-{quality}-a{audio}"
        s = self.sessions.get(key)
        if s is None:
            active = sum(1 for x in self.sessions.values() if x.running())
            if active >= get_settings().max_transcodes:
                raise TooBusy()
            s = Session(key=key, media_id=media_id, title=title, source=source, duration=duration,
                        height=height, quality=quality, audio=audio, folder=self.root / key)
            s.folder.mkdir(parents=True, exist_ok=True)
            self.sessions[key] = s
        s.viewers.add(viewer)
        return s

    async def segment(self, s: Session, n: int) -> Path:
        path = s.folder / f"{n}.ts"
        s.last_access, s.last_requested = time.monotonic(), n
        async with self._locks.setdefault(s.key, asyncio.Lock()):
            if not path.exists():
                latest = s.latest_written()
                coming_soon = s.running() and s.start_segment <= n <= latest + 4
                if not coming_soon:
                    await self._start(s, n)
            self._throttle(s)
        deadline = time.monotonic() + WAIT_SEGMENT
        while not path.exists():
            if not s.running() and not path.exists():
                await asyncio.sleep(0.3)  # the rename may land just after exit
                if path.exists():
                    break
                raise RuntimeError(f"transcoding stopped before segment {n}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"segment {n} took too long")
            await asyncio.sleep(0.15)
        s.last_access = time.monotonic()
        return path

    def _throttle(self, s: Session) -> None:
        if not s.running():
            return
        ahead = s.latest_written() - s.last_requested
        if not s.paused and ahead > AHEAD_PAUSE:
            s.proc.send_signal(signal.SIGSTOP)
            s.paused = True
        elif s.paused and ahead < AHEAD_RESUME:
            s.proc.send_signal(signal.SIGCONT)
            s.paused = False

    async def _start(self, s: Session, n: int) -> None:
        await self._stop(s, keep_files=True)
        start = n * SEGMENT
        cmd = [get_settings().ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-ss", f"{start:.3f}", "-i", str(s.source), "-map", "0:v:0",
               *video_args(s.quality, s.height), *audio_args(s.quality, s.audio),
               "-sn", "-dn", "-output_ts_offset", f"{start:.3f}",
               "-f", "hls", "-hls_time", f"{SEGMENT:g}", "-hls_list_size", "0", "-hls_segment_type", "mpegts",
               "-start_number", str(n), "-hls_flags", "temp_file+independent_segments",
               "-hls_segment_filename", str(s.folder / "%d.ts"), str(s.folder / "ffmpeg.m3u8")]
        s.proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                      stderr=asyncio.subprocess.PIPE)
        s.start_segment, s.paused = n, False
        log.info("transcoding %s at %s from %.0fs with %s", s.title, s.quality, start, encoder())

    async def _stop(self, s: Session, keep_files: bool = False) -> None:
        if s.running():
            if s.paused:
                s.proc.send_signal(signal.SIGCONT)
            s.proc.kill()
            try:
                await asyncio.wait_for(s.proc.wait(), 5)
            except asyncio.TimeoutError:
                pass
        if not keep_files:
            shutil.rmtree(s.folder, ignore_errors=True)

    async def _janitor_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            now = time.monotonic()
            for key, s in list(self.sessions.items()):
                if now - s.last_access > IDLE_STOP:
                    await self._stop(s)
                    self.sessions.pop(key, None)
                    self._locks.pop(key, None)
                else:
                    self._throttle(s)

    def status(self) -> list[dict]:
        return [{"title": s.title, "quality": s.quality, "encoder": encoder(), "paused": s.paused,
                 "viewers": sorted(s.viewers), "running": s.running()}
                for s in self.sessions.values()]


manager = TranscodeManager()


# ------------------------------------------------------------ offline copies

def offline_path(media_id: str, quality: str) -> Path:
    return get_settings().cache_dir / "offline" / f"{media_id}-{quality}.mp4"


async def make_mp4(source: Path, dest: Path, quality: str, height: int | None, duration: float | None,
                   on_progress) -> None:
    """Encode a whole film to a phone-friendly MP4 (H.264 + AAC stereo, fast start)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp4")
    cmd = [get_settings().ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-i", str(source), "-map", "0:v:0", *video_args(quality, height, keyframes_every=None),
           *audio_args(quality, 0), "-sn", "-dn", "-movflags", "+faststart",
           "-progress", "pipe:1", "-nostats", str(tmp)]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    last = 0.0
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").strip()
        if line.startswith("out_time_us=") and duration:
            try:
                done = int(line.split("=", 1)[1]) / 1e6 / duration
            except ValueError:
                continue
            if time.monotonic() - last > 2:
                last = time.monotonic()
                await on_progress(min(done, 0.99))
    err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
    if await proc.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(err[-400:] or "ffmpeg failed")
    tmp.replace(dest)
