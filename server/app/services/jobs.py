"""Background jobs: asset processing and library scans.

With GHARBOX_REDIS_URL set, jobs go to the `worker` container through arq (Redis).
Without it (local dev, tests), they run as asyncio tasks inside the API process.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..config import get_settings
from ..db import sessionmaker
from ..models import Asset
from . import media_tools, storage

log = logging.getLogger(__name__)

_redis_pool: Any = None
_local_tasks: set[asyncio.Task] = set()


async def init_queue() -> None:
    global _redis_pool
    url = get_settings().redis_url
    if url:
        from arq import create_pool
        from arq.connections import RedisSettings

        _redis_pool = await create_pool(RedisSettings.from_dsn(url))


async def close_queue() -> None:
    if _redis_pool is not None:
        await _redis_pool.aclose()


async def enqueue(name: str, *args: Any) -> None:
    if _redis_pool is not None:
        await _redis_pool.enqueue_job(name, *args)
        return
    func = JOBS[name]
    task = asyncio.create_task(func(None, *args))
    _local_tasks.add(task)
    task.add_done_callback(_local_tasks.discard)


async def queued_count() -> int | None:
    """Jobs waiting in the queue (None when jobs run in-process)."""
    if _redis_pool is None:
        return len(_local_tasks)
    try:
        return await _redis_pool.zcard("arq:queue")
    except Exception:
        return None


async def drain_local() -> None:
    """Wait for in-process jobs (used by tests)."""
    while _local_tasks:
        await asyncio.gather(*list(_local_tasks), return_exceptions=True)


# ---------------------------------------------------------------- jobs

async def process_asset(_ctx: Any, asset_id: str) -> None:
    """Read dimensions, capture date and make a thumbnail for one backed-up file."""
    async with sessionmaker()() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            return
        src = storage.abs_storage_path(asset.storage_path)
        dest = storage.thumb_path(asset.id)
        try:
            if asset.kind == "photo":
                w, h, taken = await asyncio.to_thread(media_tools.image_info, src)
                asset.width, asset.height = w, h
                if taken and asset.taken_at is None:
                    asset.taken_at = media_tools.as_utc(taken)
                await asyncio.to_thread(media_tools.make_image_thumb, src, dest)
                asset.thumb_ready = True
            elif asset.kind == "video":
                info = await asyncio.to_thread(media_tools.probe, src)
                asset.width, asset.height, asset.duration = info.width, info.height, info.duration
                if info.creation_time and asset.taken_at is None:
                    asset.taken_at = media_tools.as_utc(info.creation_time)
                at = min(1.0, (info.duration or 0) / 2)
                asset.thumb_ready = await asyncio.to_thread(media_tools.make_video_thumb, src, dest, at)
        except Exception as exc:  # a bad file must never kill the worker
            log.warning("processing %s failed: %s", asset.filename, exc)
        if asset.taken_at is None:
            asset.taken_at = asset.created_at
        await session.commit()


async def scan_library(_ctx: Any, library_id: str) -> dict:
    from .scanner import scan

    return await scan(library_id)


JOBS = {"process_asset": process_asset, "scan_library": scan_library}
