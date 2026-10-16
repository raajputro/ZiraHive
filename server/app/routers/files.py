from __future__ import annotations

import asyncio
import base64
import shutil
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, extract, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Asset, AssetVersion, Folder, User
from ..schemas import (AssetOut, AssetUpdateIn, FolderCreateIn, FolderListing, MemoryGroup,
                       PhotoPage, VersionOut)
from ..security import current_user
from ..services import storage
from ..services.ranged import ranged_file_response
from ..services.assets import file_response, preview_response, thumb_response, viewable_asset
from ..services.events import audit
from .uploads import add_version, ensure_folders

router = APIRouter(prefix="/api", tags=["files"])
TRASH_DAYS = 30


async def _get_asset(asset_id: str, user: User, session: AsyncSession,
                     include_deleted: bool = False) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.owner_id != user.id or (asset.deleted_at and not include_deleted):
        raise HTTPException(404, "File not found")
    return asset


def _in_folder(column, folder: str):
    """Rows whose folder is `folder` or anything below it."""
    if folder == "/":
        return column.like("/%")
    return or_(column == folder, column.like(folder + "/%"))


@router.get("/files", response_model=FolderListing)
async def list_folder(folder: str = "/", user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    folder = storage.normalize_folder(folder)
    depth = 0 if folder == "/" else folder.count("/")
    prefix = "/" if folder == "/" else folder + "/"
    child_paths = (await session.scalars(select(Folder.path).where(
        Folder.owner_id == user.id, Folder.path.like(prefix + "%")))).all()
    children = sorted({"/".join(p.split("/")[: depth + 2]) for p in child_paths
                       if p != folder}, key=str.lower)
    assets = (await session.scalars(select(Asset).where(
        Asset.owner_id == user.id, Asset.folder == folder, Asset.deleted_at.is_(None))
        .order_by(Asset.filename))).all()
    return FolderListing(folder=folder, folders=children, assets=assets)


@router.post("/folders", status_code=201)
async def create_folder(body: FolderCreateIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)) -> dict:
    path = storage.normalize_folder(body.path)
    if path == "/":
        raise HTTPException(400, "Folder name is required")
    await ensure_folders(session, user.id, path)
    await session.commit()
    storage.user_root(user.username).joinpath(*path.strip("/").split("/")).mkdir(
        parents=True, exist_ok=True)
    return {"path": path}


@router.delete("/folders", status_code=204)
async def delete_folder(path: str, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    """Moves every file in the folder (and sub-folders) to the trash, then removes the folder."""
    path = storage.normalize_folder(path)
    if path == "/":
        raise HTTPException(400, "Can't delete the root folder")
    now = datetime.now(timezone.utc)
    for asset in (await session.scalars(select(Asset).where(
            Asset.owner_id == user.id, _in_folder(Asset.folder, path),
            Asset.deleted_at.is_(None)))).all():
        asset.deleted_at = now
    for f in (await session.scalars(select(Folder).where(
            Folder.owner_id == user.id, _in_folder(Folder.path, path)))).all():
        await session.delete(f)
    await session.commit()


@router.get("/assets/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: str, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    return await viewable_asset(session, user.id, asset_id)


@router.get("/assets/{asset_id}/file")
async def download_asset(asset_id: str, request: Request, download: bool = False,
                         user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    asset = await viewable_asset(session, user.id, asset_id, include_deleted=True)
    return file_response(request, asset, download)


@router.get("/assets/{asset_id}/thumb")
async def asset_thumb(asset_id: str, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    return thumb_response(await viewable_asset(session, user.id, asset_id, include_deleted=True))


@router.get("/assets/{asset_id}/preview")
async def asset_preview(asset_id: str, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    return await preview_response(await viewable_asset(session, user.id, asset_id, include_deleted=True))


# --------------------------------------------------------------- versions

@router.get("/assets/{asset_id}/versions", response_model=list[VersionOut])
async def list_versions(asset_id: str, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    asset = await _get_asset(asset_id, user, session)
    return (await session.scalars(select(AssetVersion).where(AssetVersion.asset_id == asset.id)
                                  .order_by(AssetVersion.created_at.desc()))).all()


async def _get_version(asset: Asset, version_id: str, session: AsyncSession) -> AssetVersion:
    version = await session.get(AssetVersion, version_id)
    if version is None or version.asset_id != asset.id:
        raise HTTPException(404, "Version not found")
    return version


@router.get("/assets/{asset_id}/versions/{version_id}/file")
async def download_version(asset_id: str, version_id: str, request: Request,
                           user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    asset = await _get_asset(asset_id, user, session)
    version = await _get_version(asset, version_id, session)
    return ranged_file_response(request, storage.abs_storage_path(version.storage_path), asset.mime,
                                asset.filename, inline=False)


@router.post("/assets/{asset_id}/versions/{version_id}/restore", response_model=AssetOut)
async def restore_version(asset_id: str, version_id: str, request: Request,
                          user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Make an older copy current again. The current copy is kept as a version."""
    asset = await _get_asset(asset_id, user, session)
    version = await _get_version(asset, version_id, session)
    old_file = storage.abs_storage_path(version.storage_path)
    staged = old_file.with_name(old_file.name + ".restoring")
    await asyncio.to_thread(shutil.move, str(old_file), str(staged))
    size, digest = version.size, version.sha256
    await session.delete(version)
    await add_version(session, user, asset, staged, digest, size)
    await audit(session, "version_restored", user, detail=asset.filename, request=request)
    await session.commit()
    return asset


# ------------------------------------------------------------------ edits

@router.patch("/assets/{asset_id}", response_model=AssetOut)
async def update_asset(asset_id: str, body: AssetUpdateIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Rename and/or move a file. The file on disk moves too, so Explorer stays in sync."""
    asset = await _get_asset(asset_id, user, session)
    folder = storage.normalize_folder(body.folder) if body.folder is not None else asset.folder
    name = storage.safe_name(body.filename) if body.filename else asset.filename
    if folder == asset.folder and name == asset.filename:
        return asset
    src = storage.abs_storage_path(asset.storage_path)
    target, rel = storage.unique_target(user.username, folder, name)
    await asyncio.to_thread(shutil.move, str(src), str(target))
    asset.folder, asset.filename, asset.storage_path = folder, target.name, rel
    asset.kind, asset.mime = storage.kind_for(target.name), storage.mime_for(target.name)
    await ensure_folders(session, user.id, folder)
    await session.commit()
    return asset


@router.delete("/assets/{asset_id}", status_code=204)
async def trash_asset(asset_id: str, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    asset = await _get_asset(asset_id, user, session)
    asset.deleted_at = datetime.now(timezone.utc)
    await session.commit()


# ------------------------------------------------------------------ trash

@router.get("/trash", response_model=list[AssetOut])
async def list_trash(user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(Asset).where(
        Asset.owner_id == user.id, Asset.deleted_at.is_not(None))
        .order_by(Asset.deleted_at.desc()))).all()


@router.post("/trash/{asset_id}/restore", response_model=AssetOut)
async def restore_asset(asset_id: str, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    asset = await _get_asset(asset_id, user, session, include_deleted=True)
    asset.deleted_at = None
    await ensure_folders(session, user.id, asset.folder)
    await session.commit()
    return asset


async def purge_asset(asset: Asset, session: AsyncSession) -> None:
    storage.abs_storage_path(asset.storage_path).unlink(missing_ok=True)
    storage.thumb_path(asset.id).unlink(missing_ok=True)
    storage.preview_path(asset.id).unlink(missing_ok=True)
    for version in (await session.scalars(select(AssetVersion).where(AssetVersion.asset_id == asset.id))).all():
        storage.abs_storage_path(version.storage_path).unlink(missing_ok=True)
    await session.delete(asset)


@router.delete("/trash/{asset_id}", status_code=204)
async def delete_forever(asset_id: str, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    asset = await _get_asset(asset_id, user, session, include_deleted=True)
    if asset.deleted_at is None:
        raise HTTPException(400, "Move the file to the trash first")
    await purge_asset(asset, session)
    await session.commit()


@router.delete("/trash", status_code=204)
async def empty_trash(request: Request, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    await audit(session, "trash_emptied", user, request=request)
    for asset in (await session.scalars(select(Asset).where(
            Asset.owner_id == user.id, Asset.deleted_at.is_not(None)))).all():
        await purge_asset(asset, session)
    await session.commit()


async def purge_expired_trash(session: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=TRASH_DAYS)
    old = (await session.scalars(select(Asset).where(Asset.deleted_at < cutoff))).all()
    for asset in old:
        await purge_asset(asset, session)
    await session.commit()
    return len(old)


# ----------------------------------------------------------------- photos

def _encode_cursor(asset: Asset) -> str:
    raw = f"{asset.taken_at.isoformat()}|{asset.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        when, _, aid = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromisoformat(when), aid
    except Exception:
        raise HTTPException(400, "Bad cursor")


@router.get("/photos", response_model=PhotoPage)
async def photo_timeline(cursor: str | None = None, limit: int = Query(120, ge=1, le=500),
                         user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    """Photos and videos, newest first, paged with a cursor."""
    q = select(Asset).where(Asset.owner_id == user.id, Asset.deleted_at.is_(None),
                            Asset.kind.in_(("photo", "video")), Asset.taken_at.is_not(None))
    if cursor:
        when, aid = _decode_cursor(cursor)
        q = q.where(or_(Asset.taken_at < when, and_(Asset.taken_at == when, Asset.id < aid)))
    rows = (await session.scalars(q.order_by(Asset.taken_at.desc(), Asset.id.desc())
                                  .limit(limit + 1))).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return PhotoPage(items=rows, next_cursor=_encode_cursor(rows[-1]) if more and rows else None)


@router.get("/photos/on-this-day", response_model=list[MemoryGroup])
async def on_this_day(day: date | None = None, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """Photos and videos taken on today's date in earlier years, newest year first."""
    today = day or datetime.now(timezone.utc).date()
    rows = (await session.scalars(select(Asset).where(
        Asset.owner_id == user.id, Asset.deleted_at.is_(None), Asset.kind.in_(("photo", "video")),
        Asset.taken_at.is_not(None),
        extract("month", Asset.taken_at) == today.month, extract("day", Asset.taken_at) == today.day,
        extract("year", Asset.taken_at) < today.year).order_by(Asset.taken_at))).all()
    groups: dict[int, list[Asset]] = {}
    for a in rows:
        groups.setdefault(a.taken_at.year, []).append(a)
    return [MemoryGroup(year=y, years_ago=today.year - y, items=items)
            for y, items in sorted(groups.items(), reverse=True)]
