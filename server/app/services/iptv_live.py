"""Live IPTV channels (and IPTV films whose length isn't known) as HLS the browser can play.

ffmpeg reads the provider's MPEG-TS stream once and writes a short rolling HLS playlist:
- video is copied as it is (no CPU cost) unless "convert" is asked for (channels in HEVC or
  MPEG-2, which browsers can't play), then it's re-encoded to 720p H.264;
- audio is always turned into AAC stereo, because many channels send AC-3 or MP2.
Everyone watching the same channel shares one session, so it's one connection to the provider.
When a screen switches channel, its old channel stops at once if nobody else is watching it:
providers count connections and most plans allow only one or two.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings
from . import transcode
from .iptv import USER_AGENT

log = logging.getLogger(__name__)

SEGMENT = 4
WAIT_PLAYLIST = 30   # seconds to wait for the first segments
IDLE_STOP = 40       # seconds without a request before a channel is stopped
MAX_SESSIONS = 8
SEGMENT_NAME = re.compile(r"^\d{1,9}\.ts$")


class LiveError(Exception):
    pass


class LiveBusy(Exception):
    pass


@dataclass
class LiveSession:
    key: str
    title: str
    url: str
    convert: bool
    rolling: bool          # live: keep only the last few segments; films: keep everything
    folder: Path
    proc: asyncio.subprocess.Process | None = None
    last_access: float = field(default_factory=time.monotonic)
    viewers: set[str] = field(default_factory=set)
    errors: str = ""
    reader: asyncio.Task | None = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    @property
    def playlist(self) -> Path:
        return self.folder / "index.m3u8"


class LiveManager:
    def __init__(self) -> None:
        self.sessions: dict[str, LiveSession] = {}
        self.watching: dict[str, str] = {}  # viewer -> session key
        self._lock = asyncio.Lock()
        self._janitor: asyncio.Task | None = None

    @property
    def root(self) -> Path:
        return get_settings().cache_dir / "iptv-live"

    def start_janitor(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self._janitor = asyncio.create_task(self._janitor_loop())

    async def shutdown(self) -> None:
        if self._janitor:
            self._janitor.cancel()
        for s in list(self.sessions.values()):
            await self._stop(s)
        self.sessions.clear()
        self.watching.clear()

    def command(self, s: LiveSession) -> list[str]:
        cmd = [get_settings().ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-user_agent", USER_AGENT, "-reconnect", "1", "-reconnect_streamed", "1",
               "-reconnect_delay_max", "5"]
        if s.rolling:
            cmd += ["-reconnect_at_eof", "1"]
        cmd += ["-fflags", "+genpts+discardcorrupt", "-i", s.url, "-map", "0:v:0?", "-map", "0:a:0?"]
        if s.convert:
            cmd += transcode.video_args("720p", None, keyframes_every=SEGMENT)
        else:
            cmd += ["-c:v", "copy"]
        cmd += ["-c:a", "aac", "-ac", "2", "-b:a", "128k", "-sn", "-dn", "-f", "hls",
                "-hls_time", str(SEGMENT), "-hls_segment_type", "mpegts",
                "-hls_segment_filename", str(s.folder / "%d.ts")]
        if s.rolling:
            cmd += ["-hls_list_size", "8", "-hls_flags", "delete_segments+temp_file+omit_endlist"]
        else:
            cmd += ["-hls_list_size", "0", "-hls_playlist_type", "event", "-hls_flags", "temp_file"]
        return cmd + [str(s.playlist)]

    async def _start(self, s: LiveSession) -> None:
        shutil.rmtree(s.folder, ignore_errors=True)
        s.folder.mkdir(parents=True, exist_ok=True)
        s.errors = ""
        s.proc = await asyncio.create_subprocess_exec(*self.command(s), stdout=asyncio.subprocess.DEVNULL,
                                                      stderr=asyncio.subprocess.PIPE)
        s.reader = asyncio.create_task(self._read_errors(s))
        log.info("iptv: started %s%s", s.title, " (converting)" if s.convert else "")

    async def _read_errors(self, s: LiveSession) -> None:
        """Keep the end of ffmpeg's error output (and keep the pipe from filling up)."""
        proc = s.proc
        if not proc or not proc.stderr:
            return
        async for raw in proc.stderr:
            s.errors = (s.errors + raw.decode(errors="replace"))[-1500:]

    async def _stop(self, s: LiveSession) -> None:
        if s.running():
            s.proc.kill()
            try:
                await asyncio.wait_for(s.proc.wait(), 5)
            except asyncio.TimeoutError:
                pass
        if s.reader:
            s.reader.cancel()
        shutil.rmtree(s.folder, ignore_errors=True)

    async def _drop(self, key: str) -> None:
        s = self.sessions.pop(key, None)
        if s:
            await self._stop(s)
            log.info("iptv: stopped %s", s.title)

    async def open(self, key: str, url: str, title: str, convert: bool, viewer: str, rolling: bool = True) -> str:
        """Starts (or joins) a session and returns its playlist once the first segments exist."""
        async with self._lock:
            old = self.watching.get(viewer)
            if old and old != key and old in self.sessions:
                prev = self.sessions[old]
                prev.viewers.discard(viewer)
                if not prev.viewers:
                    await self._drop(old)  # free the provider connection for the new channel
            s = self.sessions.get(key)
            if s is None:
                if sum(1 for x in self.sessions.values() if x.running()) >= MAX_SESSIONS:
                    raise LiveBusy()
                s = LiveSession(key=key, title=title, url=url, convert=convert, rolling=rolling,
                                folder=self.root / key)
                self.sessions[key] = s
                await self._start(s)
            elif not s.running() and not (not s.rolling and s.playlist.exists()):
                await self._start(s)  # it stopped (provider hiccup): try again
            s.viewers.add(viewer)
            s.last_access = time.monotonic()
            self.watching[viewer] = key
        deadline = time.monotonic() + WAIT_PLAYLIST
        while True:
            if s.playlist.exists():
                text = s.playlist.read_text(errors="replace")
                if "#EXTINF" in text:
                    s.last_access = time.monotonic()
                    return text
            if not s.running():
                await asyncio.sleep(0.3)
                if s.playlist.exists() and "#EXTINF" in s.playlist.read_text(errors="replace"):
                    continue
                message = s.errors.strip().splitlines()[-1] if s.errors.strip() else "the stream ended"
                async with self._lock:
                    if self.sessions.get(key) is s:
                        await self._drop(key)
                raise LiveError(message)
            if time.monotonic() > deadline:
                async with self._lock:
                    if self.sessions.get(key) is s and len(s.viewers) <= 1:
                        await self._drop(key)
                raise LiveError("no picture arrived in time")
            await asyncio.sleep(0.25)

    def segment(self, key: str, name: str) -> Path | None:
        s = self.sessions.get(key)
        if s is None or not SEGMENT_NAME.match(name):
            return None
        s.last_access = time.monotonic()
        path = s.folder / name
        return path if path.exists() else None

    async def leave(self, viewer: str) -> None:
        async with self._lock:
            key = self.watching.pop(viewer, None)
            s = self.sessions.get(key) if key else None
            if s:
                s.viewers.discard(viewer)
                if not s.viewers:
                    await self._drop(key)

    async def _janitor_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            now = time.monotonic()
            async with self._lock:
                for key, s in list(self.sessions.items()):
                    if now - s.last_access > IDLE_STOP:
                        await self._drop(key)
                        for v in [v for v, k in self.watching.items() if k == key]:
                            self.watching.pop(v, None)

    def status(self) -> list[dict]:
        return [{"title": s.title, "converting": s.convert, "viewers": len(s.viewers), "running": s.running()}
                for s in self.sessions.values()]


manager = LiveManager()
