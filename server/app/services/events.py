"""Audit log and notifications (in-app, plus push through ntfy when the user set it up)."""
from __future__ import annotations

import logging

import httpx
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditEvent, Notification, User

log = logging.getLogger(__name__)


async def audit(session: AsyncSession, action: str, user: User | None = None,
                detail: str | None = None, request: Request | None = None,
                username: str | None = None) -> None:
    """Record who did what. The caller commits."""
    ip = None
    if request is not None:
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else None)
    session.add(AuditEvent(user_id=user.id if user else None,
                           username=user.username if user else username,
                           action=action, detail=detail, ip=ip))


async def _push(url: str, title: str, body: str | None, link: str | None) -> None:
    headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore") or "ZiraHive",
               "Tags": "house"}
    if link:
        headers["Click"] = link
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, content=(body or title).encode("utf-8"), headers=headers)
    except Exception as exc:  # push is best-effort
        log.info("ntfy push failed: %s", exc)


async def notify(session: AsyncSession, user: User, kind: str, title: str,
                 body: str | None = None, link: str | None = None) -> None:
    """Add an in-app notification (caller commits) and push it to the user's phone if set up."""
    session.add(Notification(user_id=user.id, kind=kind, title=title, body=body, link=link))
    if user.ntfy_url:
        await _push(user.ntfy_url, title, body, link)


async def notify_admins(session: AsyncSession, kind: str, title: str, body: str | None = None,
                        link: str | None = None) -> None:
    for admin in (await session.scalars(select(User).where(User.is_admin.is_(True)))).all():
        await notify(session, admin, kind, title, body, link)
