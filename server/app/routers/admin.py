from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Asset, AuditEvent, Library, MediaItem, Notification, User, utcnow
from ..schemas import (ActivityOut, AuditOut, BackupReportIn, DiskOut, NotificationList,
                       NotificationOut, SecurityCheck, StatsOut, StreamOut)
from ..security import admin_user, current_user, is_https
from ..services import activity, jobs
from ..services.events import notify

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/admin/stats", response_model=StatsOut)
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


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


@router.get("/admin/activity", response_model=ActivityOut)
async def activity_now(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    """Live view for the admin dashboard: streams, job queue and every disk GharBox uses."""
    settings = get_settings()
    disks, seen = [], set()
    places = [("Backups and app data", str(settings.data_dir))]
    places += [(lib.name, lib.path) for lib in (await session.scalars(select(Library))).all()]
    for label, path in places:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        dev = os.stat(path).st_dev
        if dev in seen:  # same physical disk as one already listed
            continue
        seen.add(dev)
        disks.append(DiskOut(label=label, path=path, total=usage.total, free=usage.free))
    return ActivityOut(
        streams=[StreamOut(**s) for s in activity.active_streams()],
        jobs_queued=await jobs.queued_count(), jobs_mode="redis worker" if settings.redis_url else "in-process",
        disks=disks, cache_bytes=_dir_size(settings.cache_dir), started_at=activity.STARTED_AT)


@router.get("/admin/security", response_model=list[SecurityCheck])
async def security_check(request: Request, _: User = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    """A plain-language checklist for the admin. Each item says what to do if it fails."""
    settings = get_settings()
    checks: list[SecurityCheck] = []

    def add(ok: bool, title: str, fix: str, level: str = "high") -> None:
        checks.append(SecurityCheck(ok=ok, title=title, fix=None if ok else fix, level=level))

    host = request.url.hostname or ""
    # home network and Tailscale addresses are already private/encrypted
    local = host in ("localhost", "127.0.0.1") or host.startswith(("192.168.", "10.", "172.", "100."))
    add(is_https(request) or local, "You're connected over HTTPS",
        "Open GharBox through its Tailscale address (https://gharbox.<your-tailnet>.ts.net) "
        "instead of plain http when you're away from home.")
    admins = (await session.scalars(select(User).where(User.is_admin.is_(True)))).all()
    weak = [a.username for a in admins if not a.totp_enabled]
    add(not weak, "Every admin uses two-factor sign-in",
        f"Turn on two-factor for: {', '.join(weak)} (Settings > Your account).")
    add(len(settings.resolved_secret()) >= 32, "Sign-in tokens use a strong secret key",
        "Set GHARBOX_SECRET_KEY in .env to a long random value (or leave it empty to auto-generate).")
    add(not settings.api_docs, "The developer API page is off",
        "Set GHARBOX_API_DOCS=false in .env unless you are developing.", "medium")
    if settings.public_url:
        add(settings.public_url.startswith("https://"), "Share links use HTTPS",
            "GHARBOX_PUBLIC_URL should start with https://")
    else:
        add(False, "Share links can be opened outside your home",
            "Set up the public share address (docs/REMOTE_ACCESS.md) and put it in GHARBOX_PUBLIC_URL. "
            "Until then, links only work on your home network and Tailscale.", "info")
    others = await session.scalar(select(func.count()).select_from(User).where(
        User.is_admin.is_(False), User.totp_enabled.is_(False))) or 0
    add(others == 0, "Family members use two-factor sign-in",
        f"{others} member account(s) sign in with a password only. Recommended, not required.", "info")
    usage = shutil.disk_usage(settings.data_dir)
    add(usage.free / usage.total > 0.1, "There's room for new backups",
        "The backup disk is over 90% full. Empty the trash or add a bigger disk.", "medium")
    return checks


@router.get("/admin/audit", response_model=list[AuditOut])
async def audit_log(limit: int = Query(100, ge=1, le=1000), before: datetime | None = None,
                    action: str | None = None, _: User = Depends(admin_user),
                    session: AsyncSession = Depends(get_session)):
    q = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if before:
        q = q.where(AuditEvent.created_at < before)
    if action:
        q = q.where(AuditEvent.action == action)
    return (await session.scalars(q)).all()


# ---------------------------------------------------------- notifications

@router.get("/notifications", response_model=NotificationList)
async def my_notifications(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    items = (await session.scalars(select(Notification).where(Notification.user_id == user.id)
                                   .order_by(Notification.created_at.desc()).limit(50))).all()
    unread = await session.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    return NotificationList(unread=unread, items=[NotificationOut.model_validate(n) for n in items])


@router.post("/notifications/read", status_code=204)
async def mark_all_read(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(update(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    await session.commit()


@router.post("/events/backup", status_code=204)
async def phone_backup_finished(body: BackupReportIn, user: User = Depends(current_user),
                                session: AsyncSession = Depends(get_session)):
    """The phone app reports the end of a backup run so it shows up as a notification."""
    if body.uploaded == 0 and body.failed == 0:
        return
    device = f" from {body.device}" if body.device else ""
    title = f"Backed up {body.uploaded} photos and videos{device}"
    text = f"{body.skipped} were already safe." + (f" {body.failed} failed; open the app to retry." if body.failed else "")
    await notify(session, user, "backup", title, text, link="/photos")
    await session.commit()
