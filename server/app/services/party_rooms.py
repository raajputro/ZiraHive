"""Live watch-party rooms: the shared playback state and who is in the room.

Timing model: the room stores `position` and the server time `at` when that position is true.
While playing, everyone should be at  position + (server_now - at).  Starting playback sets
`at` a little in the future (LEAD), so every device starts at the same moment after the
message reaches it. Browsers measure their clock offset to the server with ping/pong and
correct small drift by playing slightly faster/slower, big drift by seeking.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

LEAD = 0.6  # seconds between "play" and everyone actually starting
REACTIONS = {"😂", "❤️", "👏", "😮", "😢", "🔥", "🎉", "👍"}
MAX_CHAT = 500


def now() -> float:
    return time.time()


@dataclass
class Viewer:
    conn_id: str
    user_id: str
    username: str
    send: Callable[[dict], Awaitable[None]]
    buffering: bool = False
    position: float = 0.0
    joined: float = field(default_factory=now)
    reactions: list[float] = field(default_factory=list)
    voice: bool = False      # in the voice chat
    muted: bool = False
    signals: list[float] = field(default_factory=list)  # recent voice set-up messages (rate limit)


@dataclass
class Room:
    party_id: str
    host_id: str
    media_id: str
    control: str = "everyone"
    wait_for_all: bool = True
    playing: bool = False
    position: float = 0.0
    at: float = field(default_factory=now)
    waiting_for: list[str] = field(default_factory=list)
    auto_resume: bool = False
    viewers: dict[str, Viewer] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ------------------------------------------------------------ state

    def current(self, t: float | None = None) -> float:
        t = now() if t is None else t
        return self.position + max(0.0, t - self.at) if self.playing else self.position

    def state(self, by: str | None = None) -> dict:
        t = now()
        return {"type": "state", "media_id": self.media_id, "playing": self.playing,
                "position": self.position, "at": self.at, "server_time": t,
                "waiting_for": self.waiting_for, "control": self.control,
                "wait_for_all": self.wait_for_all, "by": by}

    def people(self) -> dict:
        seen: dict[str, dict] = {}
        for v in self.viewers.values():
            p = seen.setdefault(v.user_id, {"user_id": v.user_id, "username": v.username, "devices": 0,
                                            "buffering": False, "position": v.position,
                                            "host": v.user_id == self.host_id})
            p["devices"] += 1
            p["buffering"] = p["buffering"] or v.buffering
            p["voice"] = p.get("voice", False) or v.voice
        return {"type": "people", "people": sorted(seen.values(), key=lambda p: (not p["host"], p["username"]))}

    def voice_roster(self) -> dict:
        """Who is in the voice chat, per device (each device is its own audio connection)."""
        return {"type": "voice", "peers": [{"conn": v.conn_id, "username": v.username, "muted": v.muted}
                                           for v in self.viewers.values() if v.voice]}

    def allow_signal(self, viewer: Viewer) -> bool:
        t = now()
        viewer.signals = [x for x in viewer.signals if t - x < 10]
        if len(viewer.signals) >= 200:  # set-up takes a few dozen messages; more is abuse
            return False
        viewer.signals.append(t)
        return True

    def may_control(self, user_id: str) -> bool:
        return self.control == "everyone" or user_id == self.host_id

    # ---------------------------------------------------------- actions

    def play(self, position: float) -> None:
        self.position, self.at, self.playing = max(0.0, position), now() + LEAD, True
        self.waiting_for, self.auto_resume = [], False

    def pause(self, position: float | None = None) -> None:
        self.position = self.current() if position is None else max(0.0, position)
        self.at, self.playing = now(), False
        self.auto_resume = False

    def seek(self, position: float) -> None:
        self.position = max(0.0, position)
        self.at = now() + (LEAD if self.playing else 0)

    def change_media(self, media_id: str) -> None:
        self.media_id, self.position, self.at, self.playing = media_id, 0.0, now(), False
        self.waiting_for, self.auto_resume = [], False
        for v in self.viewers.values():
            v.buffering = False

    def set_buffering(self, viewer: Viewer, buffering: bool) -> str | None:
        """Returns "paused" or "resumed" when the room changed because of loading."""
        viewer.buffering = buffering
        loading = sorted({v.username for v in self.viewers.values() if v.buffering})
        if not self.wait_for_all:
            return None
        if loading and self.playing:
            self.pause()
            self.waiting_for, self.auto_resume = loading, True
            return "paused"
        if self.auto_resume:
            self.waiting_for = loading
            if not loading:
                self.play(self.position)
                return "resumed"
        return None

    def allow_reaction(self, viewer: Viewer, emoji: str) -> bool:
        if emoji not in REACTIONS:
            return False
        t = now()
        viewer.reactions = [x for x in viewer.reactions if t - x < 2]
        if len(viewer.reactions) >= 6:  # a few per second is plenty
            return False
        viewer.reactions.append(t)
        return True

    async def broadcast(self, msg: dict, skip: str | None = None) -> None:
        for v in list(self.viewers.values()):
            if v.conn_id == skip:
                continue
            try:
                await v.send(msg)
            except Exception:
                self.viewers.pop(v.conn_id, None)


class RoomRegistry:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def get(self, party_id: str) -> Room | None:
        return self.rooms.get(party_id)

    def open(self, party_id: str, host_id: str, media_id: str, position: float, control: str,
             wait_for_all: bool) -> Room:
        room = self.rooms.get(party_id)
        if room is None:
            room = Room(party_id, host_id, media_id, control=control, wait_for_all=wait_for_all,
                        position=position)
            self.rooms[party_id] = room
        return room

    def join(self, room: Room, user_id: str, username: str, send) -> Viewer:
        viewer = Viewer(uuid.uuid4().hex, user_id, username, send)
        room.viewers[viewer.conn_id] = viewer
        return viewer

    def leave(self, room: Room, viewer: Viewer) -> bool:
        """Returns True when the room is now empty and was closed."""
        room.viewers.pop(viewer.conn_id, None)
        if not room.viewers:
            self.rooms.pop(room.party_id, None)
            return True
        return False

    def online(self, party_id: str) -> set[str]:
        room = self.rooms.get(party_id)
        return {v.user_id for v in room.viewers.values()} if room else set()


rooms = RoomRegistry()
