"""arq worker: `arq app.worker.WorkerSettings` (the `worker` container runs this)."""
from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from . import db
from .config import get_settings
from .models import Library
from .routers.files import purge_expired_trash
from .services.jobs import make_offline_copy, process_asset, scan_library
from .services.libraries import discover


async def startup(ctx) -> None:
    settings = get_settings()
    settings.ensure_dirs()
    db.init_engine(settings.db_url)
    await db.create_all()


async def shutdown(ctx) -> None:
    await db.dispose()


async def nightly(ctx) -> None:
    """Pick up new category folders, rescan every library, empty trash older than 30 days."""
    async with db.sessionmaker()() as session:
        await purge_expired_trash(session)
        await discover(session)
        await purge_old_offline_copies(session)
        ids = (await session.scalars(select(Library.id))).all()
    for lib_id in ids:
        await scan_library(ctx, lib_id)


async def purge_old_offline_copies(session) -> int:
    from datetime import timedelta

    from .models import OfflineCopy, utcnow
    from .services.transcode import offline_path

    cutoff = utcnow() - timedelta(days=get_settings().offline_days)
    old = (await session.scalars(select(OfflineCopy).where(OfflineCopy.last_used_at < cutoff))).all()
    for copy in old:
        offline_path(copy.media_id, copy.quality).unlink(missing_ok=True)
        await session.delete(copy)
    await session.commit()
    return len(old)


async def disk_check(ctx) -> None:
    """Warn admins once a day when the backup disk is over 90% full."""
    from datetime import timedelta
    import shutil

    from sqlalchemy import func

    from .models import Notification, utcnow
    from .services.events import notify_admins

    usage = shutil.disk_usage(get_settings().data_dir)
    used = 1 - usage.free / usage.total
    if used < 0.9:
        return
    async with db.sessionmaker()() as session:
        recent = await session.scalar(select(func.count()).select_from(Notification).where(
            Notification.kind == "disk", Notification.created_at > utcnow() - timedelta(hours=23)))
        if recent:
            return
        await notify_admins(session, "disk", f"Backup disk is {used:.0%} full",
                            f"{usage.free / 1024**3:.1f} GB left. Empty the trash or add a bigger disk.",
                            link="/settings")
        await session.commit()


class WorkerSettings:
    functions = [process_asset, scan_library, make_offline_copy]
    cron_jobs = [cron(nightly, hour={3}, minute={0}), cron(disk_check, minute={17})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 4
    job_timeout = 6 * 3600
