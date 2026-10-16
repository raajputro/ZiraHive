"""arq worker: `arq app.worker.WorkerSettings` (the `worker` container runs this)."""
from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from . import db
from .config import get_settings
from .models import Library
from .routers.files import purge_expired_trash
from .services.jobs import process_asset, scan_library


async def startup(ctx) -> None:
    settings = get_settings()
    settings.ensure_dirs()
    db.init_engine(settings.db_url)
    await db.create_all()


async def shutdown(ctx) -> None:
    await db.dispose()


async def nightly(ctx) -> None:
    """Rescan every library and empty trash older than 30 days."""
    async with db.sessionmaker()() as session:
        await purge_expired_trash(session)
        ids = (await session.scalars(select(Library.id))).all()
    for lib_id in ids:
        await scan_library(ctx, lib_id)


class WorkerSettings:
    functions = [process_asset, scan_library]
    cron_jobs = [cron(nightly, hour={3}, minute={0})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 4
    job_timeout = 6 * 3600
