"""Serving backed-up files: who may see them, and the original / preview / thumbnail."""
from __future__ import annotations

import asyncio

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Album, AlbumItem, AlbumMember, Asset
from . import media_tools, storage
from .ranged import ranged_file_response

PREVIEW_SIZE = 1920
_CACHE = {"Cache-Control": "private, max-age=604800"}


async def in_shared_album(session: AsyncSession, user_id: str, asset_id: str) -> bool:
    """True when the asset is in an album this user owns or was added to."""
    q = (select(AlbumItem.id).join(Album, Album.id == AlbumItem.album_id)
         .outerjoin(AlbumMember, and_(AlbumMember.album_id == Album.id, AlbumMember.user_id == user_id))
         .where(AlbumItem.asset_id == asset_id,
                or_(Album.owner_id == user_id, AlbumMember.user_id.is_not(None))).limit(1))
    return (await session.scalar(q)) is not None


async def viewable_asset(session: AsyncSession, user_id: str, asset_id: str,
                         include_deleted: bool = False) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "File not found")
    if asset.owner_id == user_id:
        if asset.deleted_at and not include_deleted:
            raise HTTPException(404, "File not found")
        return asset
    if asset.deleted_at is None and await in_shared_album(session, user_id, asset_id):
        return asset
    raise HTTPException(404, "File not found")


def file_response(request: Request, asset: Asset, download: bool = False):
    path = storage.abs_storage_path(asset.storage_path)
    return ranged_file_response(request, path, asset.mime, asset.filename, inline=not download)


def thumb_response(asset: Asset) -> FileResponse:
    path = storage.thumb_path(asset.id)
    if not asset.thumb_ready or not path.exists():
        raise HTTPException(404, "No thumbnail yet")
    return FileResponse(path, media_type="image/webp", headers=_CACHE)


async def preview_response(asset: Asset) -> FileResponse:
    """A screen-sized WebP (1920 px). Lighter than the original on mobile data, and it
    lets browsers that can't open HEIC still show iPhone photos in full screen."""
    if asset.kind != "photo":
        return thumb_response(asset)
    path = storage.preview_path(asset.id)
    if not path.exists():
        src = storage.abs_storage_path(asset.storage_path)
        try:
            await asyncio.to_thread(media_tools.make_image_thumb, src, path, PREVIEW_SIZE)
        except Exception:
            return thumb_response(asset)
    return FileResponse(path, media_type="image/webp", headers=_CACHE)
