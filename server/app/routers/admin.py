from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Asset, MediaItem, User
from ..schemas import StatsOut
from ..security import admin_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats", response_model=StatsOut)
async def stats(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    by_kind = dict((await session.execute(
        select(Asset.kind, func.count()).where(Asset.deleted_at.is_(None))
        .group_by(Asset.kind))).all())
    total_bytes = await session.scalar(select(func.coalesce(func.sum(Asset.size), 0))) or 0
    disk = shutil.disk_usage(get_settings().data_dir)
    return StatsOut(
        users=await session.scalar(select(func.count()).select_from(User)) or 0,
        assets=sum(by_kind.values()),
        asset_bytes=int(total_bytes),
        photos=by_kind.get("photo", 0),
        videos=by_kind.get("video", 0),
        documents=by_kind.get("document", 0),
        media_items=await session.scalar(select(func.count()).select_from(MediaItem).where(
            MediaItem.missing.is_(False))) or 0,
        disk_total=disk.total,
        disk_free=disk.free,
        jobs_mode="redis worker" if get_settings().redis_url else "in-process",
    )
