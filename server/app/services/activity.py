"""Who is watching what right now (kept in memory by the api process)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

STARTED_AT = datetime.now(timezone.utc)
_ACTIVE_SECONDS = 90
_streams: dict[tuple[str, str], tuple[float, str, str]] = {}


def stream_seen(user_id: str, username: str, media_id: str, title: str) -> None:
    _streams[(user_id, media_id)] = (time.time(), username, title)


def active_streams() -> list[dict]:
    now = time.time()
    for key in [k for k, v in _streams.items() if now - v[0] > _ACTIVE_SECONDS]:
        _streams.pop(key, None)
    return [{"username": name, "media_id": mid, "title": title,
             "last_seen": datetime.fromtimestamp(seen, timezone.utc)}
            for (_, mid), (seen, name, title) in sorted(_streams.items(), key=lambda kv: -kv[1][0])]
