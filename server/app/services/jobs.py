"""Background jobs: asset processing and library scans.

With ZIRAHIVE_REDIS_URL set, jobs go to the `worker` container through arq (Redis).
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
                from . import photo_quality
                asset.phash, asset.sharpness = await asyncio.to_thread(photo_quality.measure, src)
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
        kind = asset.kind
    from ..config import get_settings

    if kind == "photo" and get_settings().ai_url:
        await enqueue("ai_photo", asset_id)  # does nothing when the ai container isn't running


async def make_offline_copy(_ctx: Any, copy_id: str) -> None:
    """Encode a smaller MP4 for offline viewing, reporting progress as it goes."""
    from pathlib import Path

    from ..models import Library, MediaItem, OfflineCopy, User
    from . import transcode
    from .events import notify

    async with sessionmaker()() as session:
        copy = await session.get(OfflineCopy, copy_id)
        if copy is None or copy.status not in ("queued", "failed"):
            return
        item = await session.get(MediaItem, copy.media_id)
        lib = await session.get(Library, item.library_id) if item else None
        if item is None or lib is None:
            return
        copy.status, copy.progress = "working", 0
        await session.commit()

        async def progress(p: float) -> None:
            copy.progress = round(p, 3)
            await session.commit()

        dest = transcode.offline_path(item.id, copy.quality)
        try:
            await transcode.make_mp4(Path(lib.path) / item.rel_path, dest, copy.quality, item.height,
                                     item.duration, progress)
            copy.status, copy.progress, copy.size = "ready", 1.0, dest.stat().st_size
            who = await session.get(User, copy.requested_by) if copy.requested_by else None
            if who:
                await notify(session, who, "offline", f"{item.title} is ready to download",
                             "Open it and press Download for offline.", link=f"/play/{item.id}")
        except Exception as exc:
            log.warning("offline copy of %s failed: %s", item.title, exc)
            copy.status, copy.error = "failed", str(exc)[-300:]
        await session.commit()


async def scan_library(_ctx: Any, library_id: str) -> dict:
    from .scanner import scan

    return await scan(library_id)


async def offsite_backup(_ctx: Any) -> str:
    from . import offsite

    async with sessionmaker()() as session:
        try:
            return (await offsite.run_backup(session)).status
        except offsite.BackupError as exc:
            return str(exc)


async def offsite_check(_ctx: Any) -> str:
    from . import offsite

    async with sessionmaker()() as session:
        try:
            return (await offsite.run_check(session)).status
        except offsite.BackupError as exc:
            return str(exc)


JOBS = {"process_asset": process_asset, "scan_library": scan_library, "make_offline_copy": make_offline_copy,
        "offsite_backup": offsite_backup, "offsite_check": offsite_check}


async def extract_text(_ctx: Any, asset_id: str) -> str:
    """Read the words in one file (text layer or OCR) so Files can search inside it."""
    from ..models import AssetText
    from . import textsearch

    async with sessionmaker()() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None or asset.deleted_at:
            return "gone"
        row = await session.get(AssetText, asset_id)
        if row and row.sha256 == asset.sha256:
            return "done already"
        src = storage.abs_storage_path(asset.storage_path)
        try:
            text, method, pages = await asyncio.to_thread(textsearch.extract, src)
        except Exception as exc:  # a damaged file must not stop the queue
            log.info("reading text of %s failed: %s", asset.filename, exc)
            text, method, pages = "", "failed", None
        if row is None:
            row = AssetText(asset_id=asset_id, sha256=asset.sha256, method=method)
            session.add(row)
        row.text, row.method, row.pages, row.sha256 = text, method, pages, asset.sha256
        await session.commit()
    from ..config import get_settings

    if text.strip() and get_settings().ollama_url:
        await enqueue("doc_chunks", asset_id)
    return method


async def text_backfill(_ctx: Any, limit: int = 300) -> int:
    """Files uploaded before text search existed (or changed since): a few hundred per night."""
    from sqlalchemy import or_, select

    from ..models import AssetText
    from . import textsearch

    async with sessionmaker()() as session:
        rows = (await session.execute(
            select(Asset.id, Asset.filename, Asset.folder, Asset.kind).outerjoin(AssetText, AssetText.asset_id == Asset.id)
            .where(Asset.deleted_at.is_(None), or_(AssetText.asset_id.is_(None), AssetText.sha256 != Asset.sha256))
            .order_by(Asset.created_at.desc()).limit(limit * 5))).all()
    todo = [r.id for r in rows if textsearch.wanted(r.filename, r.folder, r.kind)][:limit]
    for asset_id in todo:
        await extract_text(None, asset_id)
    return len(todo)


JOBS.update({"extract_text": extract_text, "text_backfill": text_backfill})

from . import ai_jobs  # noqa: E402

JOBS.update({"photo_quality": ai_jobs.photo_quality_job, "ai_photo": ai_jobs.ai_photo, "doc_chunks": ai_jobs.doc_chunks,
             "transcribe": ai_jobs.transcribe, "ai_backfill": ai_jobs.ai_backfill})
