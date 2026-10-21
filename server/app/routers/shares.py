"""Share links: a file, folder or album that anyone with the link can open.

Owners manage links under /api/shares. Visitors use /api/s/<token>/... without an account;
password-protected links first POST /unlock and then pass ?key=<key> on every request.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Album, AlbumItem, Asset, Folder, ShareLink, User
from ..schemas import PublicAsset, PublicListing, PublicShareOut, ShareIn, ShareOut, UnlockIn
from ..security import (client_ip, create_scoped_token, current_user, hash_password, read_scope,
                        share_throttle, verify_password)
from ..services import storage
from ..services.assets import file_response, preview_response, thumb_response, view_response
from ..services.events import audit

router = APIRouter(prefix="/api", tags=["shares"])


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


async def _label(session: AsyncSession, link: ShareLink) -> str:
    if link.target_type == "asset":
        asset = await session.get(Asset, link.target_id)
        return asset.filename if asset else "(deleted file)"
    if link.target_type == "album":
        album = await session.get(Album, link.target_id)
        return album.title if album else "(deleted album)"
    return link.target_id.rsplit("/", 1)[-1] or "My files"


async def _out(session: AsyncSession, link: ShareLink) -> ShareOut:
    out = ShareOut.model_validate(link)
    out.label = await _label(session, link)
    out.has_password = link.password_hash is not None
    return out


# ------------------------------------------------------------------ owner

@router.post("/shares", response_model=ShareOut, status_code=201)
async def create_share(body: ShareIn, request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    target = body.target_id
    if body.target_type == "asset":
        asset = await session.get(Asset, target)
        if asset is None or asset.owner_id != user.id or asset.deleted_at:
            raise HTTPException(404, "File not found")
    elif body.target_type == "album":
        album = await session.get(Album, target)
        if album is None or album.owner_id != user.id:
            raise HTTPException(404, "Only the album's owner can make a link for it")
    else:
        target = storage.normalize_folder(target)
        if target != "/" and not await session.scalar(select(Folder.id).where(
                Folder.owner_id == user.id, Folder.path == target)):
            raise HTTPException(404, "Folder not found")
    link = ShareLink(token=secrets.token_urlsafe(16), owner_id=user.id, target_type=body.target_type,
                     target_id=target, allow_download=body.allow_download,
                     password_hash=hash_password(body.password) if body.password else None,
                     expires_at=(datetime.now(timezone.utc) + timedelta(days=body.expires_days))
                     if body.expires_days else None)
    session.add(link)
    await audit(session, "share_created", user, detail=f"{body.target_type} {await _label(session, link)}",
                request=request)
    await session.commit()
    return await _out(session, link)


@router.get("/shares", response_model=list[ShareOut])
async def list_shares(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    links = (await session.scalars(select(ShareLink).where(ShareLink.owner_id == user.id)
                                   .order_by(ShareLink.created_at.desc()))).all()
    return [await _out(session, link) for link in links]


@router.delete("/shares/{share_id}", status_code=204)
async def delete_share(share_id: str, request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    link = await session.get(ShareLink, share_id)
    if link is None or link.owner_id != user.id:
        raise HTTPException(404, "Link not found")
    await audit(session, "share_deleted", user, detail=await _label(session, link), request=request)
    await session.delete(link)
    await session.commit()


# ---------------------------------------------------------------- visitor

async def _open(session: AsyncSession, token: str) -> ShareLink:
    link = await session.scalar(select(ShareLink).where(ShareLink.token == token))
    expired = link and link.expires_at and _aware(link.expires_at) < datetime.now(timezone.utc)
    if link is None or expired:
        raise HTTPException(404, "This link has expired or was removed")
    return link


async def _unlocked(session: AsyncSession, token: str, key: str | None) -> ShareLink:
    link = await _open(session, token)
    if link.password_hash and read_scope(key, "share:") != token:
        raise HTTPException(401, "This link needs a password")
    return link


def _public(a: Asset) -> PublicAsset:
    return PublicAsset(id=a.id, filename=a.filename, size=a.size, mime=a.mime, kind=a.kind,
                       width=a.width, height=a.height, duration=a.duration, taken_at=a.taken_at,
                       thumb_ready=a.thumb_ready)


async def _shared_asset(session: AsyncSession, link: ShareLink, asset_id: str) -> Asset:
    """An asset is reachable only if it's inside what was shared."""
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at or asset.owner_id != link.owner_id:
        raise HTTPException(404, "File not found")
    if link.target_type == "asset" and asset.id == link.target_id:
        return asset
    if link.target_type == "folder":
        root = link.target_id
        if root == "/" or asset.folder == root or asset.folder.startswith(root + "/"):
            return asset
    if link.target_type == "album" and await session.scalar(select(AlbumItem.id).where(
            AlbumItem.album_id == link.target_id, AlbumItem.asset_id == asset.id)):
        return asset
    raise HTTPException(404, "File not found")


@router.get("/s/{token}", response_model=PublicShareOut)
async def share_info(token: str, session: AsyncSession = Depends(get_session)):
    link = await _open(session, token)
    link.views = (link.views or 0) + 1
    await session.commit()
    owner = await session.get(User, link.owner_id)
    return PublicShareOut(type=link.target_type, title=await _label(session, link),
                          owner=owner.username if owner else "", needs_password=link.password_hash is not None,
                          expires_at=link.expires_at, allow_download=link.allow_download)


@router.post("/s/{token}/unlock")
async def unlock_share(token: str, body: UnlockIn, request: Request,
                       session: AsyncSession = Depends(get_session)) -> dict:
    key = f"{client_ip(request)}:{token}"
    share_throttle.check(key)
    link = await _open(session, token)
    if link.password_hash and not verify_password(body.password, link.password_hash):
        share_throttle.fail(key)
        raise HTTPException(401, "Wrong password")
    return {"key": create_scoped_token(f"share:{token}", minutes=12 * 60)}


@router.get("/s/{token}/items", response_model=PublicListing)
async def share_items(token: str, path: str = "", key: str | None = None,
                      session: AsyncSession = Depends(get_session)):
    link = await _unlocked(session, token, key)
    if link.target_type == "asset":
        asset = await _shared_asset(session, link, link.target_id)
        return PublicListing(path="", folders=[], assets=[_public(asset)])
    if link.target_type == "album":
        assets = (await session.scalars(select(Asset).join(AlbumItem, AlbumItem.asset_id == Asset.id).where(
            AlbumItem.album_id == link.target_id, Asset.deleted_at.is_(None))
            .order_by(Asset.taken_at.desc()))).all()
        return PublicListing(path="", folders=[], assets=[_public(a) for a in assets])
    # folder: path is relative to the shared folder
    root = link.target_id
    sub = storage.normalize_folder(path)
    folder = root if sub == "/" else (sub if root == "/" else root + sub)
    depth = 0 if folder == "/" else folder.count("/")
    prefix = "/" if folder == "/" else folder + "/"
    child_paths = (await session.scalars(select(Folder.path).where(
        Folder.owner_id == link.owner_id, Folder.path.like(prefix + "%")))).all()
    children = sorted({"/".join(p.split("/")[: depth + 2]) for p in child_paths if p != folder}, key=str.lower)
    strip = 0 if root == "/" else len(root)
    assets = (await session.scalars(select(Asset).where(
        Asset.owner_id == link.owner_id, Asset.folder == folder, Asset.deleted_at.is_(None))
        .order_by(Asset.filename))).all()
    return PublicListing(path=sub, folders=[c[strip:] for c in children], assets=[_public(a) for a in assets])


@router.get("/s/{token}/assets/{asset_id}/file")
async def share_file(token: str, asset_id: str, request: Request, key: str | None = None,
                     download: bool = False, view: bool = False, session: AsyncSession = Depends(get_session)):
    link = await _unlocked(session, token, key)
    if download and not link.allow_download:
        raise HTTPException(403, "The owner turned off downloads for this link")
    asset = await _shared_asset(session, link, asset_id)
    if not link.allow_download and asset.kind == "photo":
        return await preview_response(asset)  # view-only links never hand out the original
    if view and not download:
        return await view_response(request, asset)
    return file_response(request, asset, download)


@router.get("/s/{token}/assets/{asset_id}/thumb")
async def share_thumb(token: str, asset_id: str, key: str | None = None,
                      session: AsyncSession = Depends(get_session)):
    link = await _unlocked(session, token, key)
    return thumb_response(await _shared_asset(session, link, asset_id))


@router.get("/s/{token}/assets/{asset_id}/preview")
async def share_preview(token: str, asset_id: str, key: str | None = None,
                        session: AsyncSession = Depends(get_session)):
    link = await _unlocked(session, token, key)
    return await preview_response(await _shared_asset(session, link, asset_id))

