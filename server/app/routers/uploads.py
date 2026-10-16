"""Resumable uploads with SHA-256 de-duplication.

Protocol (works the same from the web app and the phone app):
  1. POST /api/uploads/check  {sha256: [...]}       -> which hashes are already backed up
  2. POST /api/uploads        {filename, size, ...}  -> {id, offset} or {status: "exists"}
  3. PATCH /api/uploads/{id}  body = bytes, header Upload-Offset: <offset>
     repeat until offset == size; the last chunk returns {status: "complete", asset}
  4. GET /api/uploads/{id}    -> current offset (resume after a dropped connection)
"""
from __future__ import annotations

import asyncio
import hashlib
import shutil
from collections import defaultdict
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Asset, AssetVersion, Folder, UploadSession, User, utcnow
from ..schemas import AssetOut, HashCheckIn, HashCheckOut, UploadCreateIn, UploadOut
from ..security import current_user
from ..services import jobs, storage
from ..services.media_tools import as_utc

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _part_path(upload_id: str) -> Path:
    return get_settings().upload_dir / f"{upload_id}.part"


async def _get_upload(upload_id: str, user: User, session: AsyncSession) -> UploadSession:
    up = await session.get(UploadSession, upload_id)
    if up is None or up.owner_id != user.id:
        raise HTTPException(404, "Upload not found")
    return up


async def ensure_folders(session: AsyncSession, owner_id: str, folder: str) -> None:
    for path in storage.parent_folders(folder):
        exists = await session.scalar(select(Folder.id).where(
            Folder.owner_id == owner_id, Folder.path == path))
        if not exists:
            session.add(Folder(owner_id=owner_id, path=path))


@router.post("/check", response_model=HashCheckOut)
async def check_hashes(body: HashCheckIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    wanted = {h.lower() for h in body.sha256}
    if not wanted:
        return HashCheckOut(existing=[])
    rows = await session.scalars(select(Asset.sha256).where(
        Asset.owner_id == user.id, Asset.sha256.in_(wanted)))
    return HashCheckOut(existing=sorted(set(rows.all())))


@router.post("", response_model=UploadOut, status_code=201)
async def create_upload(body: UploadCreateIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    folder = storage.normalize_folder(body.folder)
    if body.sha256 and body.dedupe:
        existing = (await session.scalars(select(Asset).where(
            Asset.owner_id == user.id, Asset.sha256 == body.sha256.lower())
            .order_by(Asset.deleted_at.is_not(None)).limit(1))).first()
        if existing:
            if existing.deleted_at:  # uploading again brings it back from the trash
                existing.deleted_at = None
                await session.commit()
            return UploadOut(status="exists", size=existing.size, offset=existing.size,
                             asset=AssetOut.model_validate(existing))
    if user.quota_bytes is not None:
        from .auth import used_bytes
        if await used_bytes(session, user.id) + body.size > user.quota_bytes:
            raise HTTPException(507, "Storage quota exceeded")
    free = shutil.disk_usage(get_settings().data_dir).free
    if body.size > free:
        raise HTTPException(507, "Not enough disk space on the server")
    up = UploadSession(owner_id=user.id, filename=storage.safe_name(body.filename), folder=folder,
                       size=body.size, sha256=body.sha256.lower() if body.sha256 else None,
                       taken_at=as_utc(body.taken_at), device_asset_id=body.device_asset_id,
                       dedupe=body.dedupe and not body.replace, replace=body.replace)
    session.add(up)
    await session.commit()
    _part_path(up.id).touch()
    if up.size == 0:
        return await _finalize(up, user, session)
    return UploadOut(id=up.id, offset=0, size=up.size, status="uploading")


@router.get("/{upload_id}", response_model=UploadOut)
async def upload_status(upload_id: str, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    up = await _get_upload(upload_id, user, session)
    return UploadOut(id=up.id, offset=up.offset, size=up.size, status="uploading")


@router.patch("/{upload_id}", response_model=UploadOut)
async def upload_chunk(upload_id: str, request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    max_chunk = get_settings().max_chunk_mb * 1024 * 1024
    async with _locks[upload_id]:
        up = await _get_upload(upload_id, user, session)
        try:
            offset = int(request.headers.get("upload-offset", ""))
        except ValueError:
            raise HTTPException(400, "Upload-Offset header is required")
        if offset != up.offset:
            raise HTTPException(409, f"Offset mismatch: server has {up.offset}",
                                headers={"Upload-Offset": str(up.offset)})
        part = _part_path(up.id)
        written = 0
        async with aiofiles.open(part, "r+b") as f:
            await f.seek(offset)
            await f.truncate()
            async for data in request.stream():
                written += len(data)
                if written > max_chunk or offset + written > up.size:
                    await f.truncate(offset)
                    raise HTTPException(413, "Chunk too large or past the declared size")
                await f.write(data)
        up.offset = offset + written
        await session.commit()
        if up.offset < up.size:
            return UploadOut(id=up.id, offset=up.offset, size=up.size, status="uploading")
        result = await _finalize(up, user, session)
    _locks.pop(upload_id, None)
    return result


@router.delete("/{upload_id}", status_code=204)
async def cancel_upload(upload_id: str, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    up = await _get_upload(upload_id, user, session)
    _part_path(up.id).unlink(missing_ok=True)
    await session.delete(up)
    await session.commit()


VERSIONED_KINDS = ("document", "other")
MAX_VERSIONS = 20


async def add_version(session: AsyncSession, user: User, asset: Asset, new_file: Path,
                      digest: str, size: int) -> None:
    """Uploading a document with the same name into the same folder keeps the old copy as
    a version (like Google Drive) instead of making 'report (1).pdf'. Photos are not
    versioned, because phones reuse names like IMG_0001.JPG."""
    current_path = storage.abs_storage_path(asset.storage_path)
    old_abs, old_rel = storage.version_target(user.username, asset.id, asset.filename)
    if current_path.exists():
        await asyncio.to_thread(shutil.move, str(current_path), str(old_abs))
    session.add(AssetVersion(asset_id=asset.id, size=asset.size, sha256=asset.sha256,
                             storage_path=old_rel, created_at=asset.updated_at or asset.created_at))
    await asyncio.to_thread(shutil.move, str(new_file), str(current_path))
    asset.size, asset.sha256, asset.updated_at = size, digest, utcnow()
    await session.flush()
    versions = (await session.scalars(select(AssetVersion).where(AssetVersion.asset_id == asset.id)
                                      .order_by(AssetVersion.created_at.desc()))).all()
    for old in versions[MAX_VERSIONS:]:
        storage.abs_storage_path(old.storage_path).unlink(missing_ok=True)
        await session.delete(old)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


async def _read_text_later(asset: Asset) -> None:
    from ..services.textsearch import wanted

    if wanted(asset.filename, asset.folder, asset.kind):
        await jobs.enqueue("extract_text", asset.id)


async def _finalize(up: UploadSession, user: User, session: AsyncSession) -> UploadOut:
    part = _part_path(up.id)
    digest = await asyncio.to_thread(_sha256_file, part)
    if up.sha256 and digest != up.sha256:
        part.unlink(missing_ok=True)
        await session.delete(up)
        await session.commit()
        raise HTTPException(422, "Checksum mismatch: the file was corrupted in transit, upload it again")
    existing = None
    if up.dedupe:
        existing = (await session.scalars(select(Asset).where(
            Asset.owner_id == user.id, Asset.sha256 == digest)
            .order_by(Asset.deleted_at.is_not(None)).limit(1))).first()
    if existing:
        part.unlink(missing_ok=True)
        await session.delete(up)
        if existing.deleted_at:
            existing.deleted_at = None
        await session.commit()
        return UploadOut(status="exists", size=existing.size, offset=existing.size,
                         asset=AssetOut.model_validate(existing))
    if storage.kind_for(up.filename) in VERSIONED_KINDS or up.replace:
        current = await session.scalar(select(Asset).where(
            Asset.owner_id == user.id, Asset.folder == up.folder, Asset.filename == up.filename,
            Asset.deleted_at.is_(None)))
        if current and current.sha256 == digest:  # same contents: nothing to keep
            part.unlink(missing_ok=True)
            await session.delete(up)
            await session.commit()
            return UploadOut(status="complete", size=current.size, offset=current.size,
                             asset=AssetOut.model_validate(current))
        if current:
            await add_version(session, user, current, part, digest, up.size)
            await session.delete(up)
            await session.commit()
            if current.kind in ("photo", "video"):
                await jobs.enqueue("process_asset", current.id)  # new picture, new thumbnail
            await _read_text_later(current)
            return UploadOut(status="complete", size=current.size, offset=current.size,
                             asset=AssetOut.model_validate(current))
    target, rel = storage.unique_target(user.username, up.folder, up.filename)
    await asyncio.to_thread(shutil.move, str(part), str(target))
    asset = Asset(owner_id=user.id, folder=up.folder, filename=target.name, size=up.size,
                  mime=storage.mime_for(target.name), kind=storage.kind_for(target.name),
                  sha256=digest, storage_path=rel, taken_at=up.taken_at,
                  device_asset_id=up.device_asset_id)
    session.add(asset)
    await ensure_folders(session, user.id, up.folder)
    await session.delete(up)
    await session.commit()
    if asset.kind in ("photo", "video"):
        await jobs.enqueue("process_asset", asset.id)
    await _read_text_later(asset)
    return UploadOut(status="complete", size=asset.size, offset=asset.size,
                     asset=AssetOut.model_validate(asset))
