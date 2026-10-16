"""The vault: end-to-end encrypted files.

Everything is encrypted in the browser before it is sent. The server stores opaque bytes and
the master key wrapped by the person's passphrase (and by their recovery key). It never sees
the passphrase, the keys, file names or contents, so neither an admin nor someone who steals
the disk can read the vault.

Upload: POST /api/vault/items (encrypted size, wrapped file key, encrypted name) -> id, then
PATCH /api/vault/items/{id}/data with Upload-Offset, as many times as needed.
"""
from __future__ import annotations

import shutil
from collections import defaultdict
from asyncio import Lock
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import User, Vault, VaultItem
from ..schemas import (VaultItemIn, VaultItemOut, VaultItemUpdateIn, VaultKeysIn, VaultOut, VaultResetIn,
                       VaultSetupIn)
from ..security import current_user, verify_password
from ..services.events import audit
from ..services.ranged import ranged_file_response

router = APIRouter(prefix="/api/vault", tags=["vault"])

MAX_PATCH = 17 * 1024 * 1024
MAX_THUMB = 2 * 1024 * 1024
_locks: defaultdict[str, Lock] = defaultdict(Lock)


def vault_dir(user_id: str) -> Path:
    return get_settings().data_dir / "vault" / user_id


def data_path(item: VaultItem) -> Path:
    return vault_dir(item.user_id) / f"{item.id}.bin"


def thumb_path(item: VaultItem) -> Path:
    return vault_dir(item.user_id) / f"{item.id}.thumb"


async def vault_bytes(session: AsyncSession, user_id: str) -> int:
    return int(await session.scalar(select(func.coalesce(func.sum(VaultItem.size), 0))
                                    .where(VaultItem.user_id == user_id)) or 0)


async def _vault(session: AsyncSession, user: User) -> Vault | None:
    return await session.scalar(select(Vault).where(Vault.user_id == user.id))


async def _item(session: AsyncSession, user: User, item_id: str) -> VaultItem:
    item = await session.get(VaultItem, item_id)
    if item is None or item.user_id != user.id:  # nobody else's vault, admins included
        raise HTTPException(404, "Not found")
    return item


def _check_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise HTTPException(403, "Password is wrong")


@router.get("", response_model=VaultOut)
async def get_vault(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    v = await _vault(session, user)
    if v is None:
        return VaultOut(set_up=False)
    count = await session.scalar(select(func.count()).select_from(VaultItem).where(
        VaultItem.user_id == user.id, VaultItem.complete.is_(True)))
    return VaultOut(set_up=True, kdf=v.kdf, salt=v.salt, iterations=v.iterations, wrapped_key=v.wrapped_key,
                    recovery_wrapped_key=v.recovery_wrapped_key, item_count=count or 0,
                    bytes=await vault_bytes(session, user.id))


@router.post("", response_model=VaultOut, status_code=201)
async def set_up_vault(body: VaultSetupIn, request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    if await _vault(session, user):
        raise HTTPException(409, "Your vault is already set up")
    session.add(Vault(user_id=user.id, salt=body.salt, iterations=body.iterations, wrapped_key=body.wrapped_key,
                      recovery_wrapped_key=body.recovery_wrapped_key))
    await audit(session, "vault_created", user=user, request=request)
    await session.commit()
    return await get_vault(user, session)


@router.put("/keys", response_model=VaultOut)
async def change_vault_keys(body: VaultKeysIn, request: Request, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    """A new vault passphrase. The files stay as they are; only the wrapped master key changes."""
    _check_password(user, body.password)
    v = await _vault(session, user)
    if v is None:
        raise HTTPException(404, "Your vault isn't set up yet")
    v.salt, v.iterations, v.wrapped_key = body.salt, body.iterations, body.wrapped_key
    if body.recovery_wrapped_key:
        v.recovery_wrapped_key = body.recovery_wrapped_key
    await audit(session, "vault_keys_changed", user=user, request=request)
    await session.commit()
    return await get_vault(user, session)


@router.delete("", status_code=204)
async def reset_vault(body: VaultResetIn, request: Request, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """Forgot both the passphrase and the recovery key: the only way out is to empty the vault."""
    _check_password(user, body.password)
    await session.execute(delete(VaultItem).where(VaultItem.user_id == user.id))
    await session.execute(delete(Vault).where(Vault.user_id == user.id))
    await audit(session, "vault_reset", user=user, request=request)
    await session.commit()
    shutil.rmtree(vault_dir(user.id), ignore_errors=True)


# ------------------------------------------------------------------ items

@router.get("/items", response_model=list[VaultItemOut])
async def list_items(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(VaultItem).where(VaultItem.user_id == user.id, VaultItem.complete.is_(True))
                                  .order_by(VaultItem.created_at.desc()))).all()
    return rows


@router.post("/items", response_model=VaultItemOut, status_code=201)
async def create_item(body: VaultItemIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    if await _vault(session, user) is None:
        raise HTTPException(409, "Set up your vault first")
    from .auth import used_bytes

    if user.quota_bytes is not None and await used_bytes(session, user.id) + body.size > user.quota_bytes:
        raise HTTPException(413, "Storage quota exceeded")
    free = shutil.disk_usage(get_settings().data_dir).free
    if body.size > free - 512 * 1024 * 1024:
        raise HTTPException(507, "Not enough disk space on the server")
    item = VaultItem(user_id=user.id, size=body.size, chunk_size=body.chunk_size, wrapped_key=body.wrapped_key,
                     meta=body.meta)
    session.add(item)
    await session.commit()
    path = data_path(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return item


@router.head("/items/{item_id}/data")
async def item_offset(item_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    item = await _item(session, user, item_id)
    return Response(headers={"Upload-Offset": str(item.received), "Upload-Length": str(item.size)})


@router.patch("/items/{item_id}/data", response_model=VaultItemOut)
async def upload_data(item_id: str, request: Request, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    async with _locks[item_id]:
        item = await _item(session, user, item_id)
        if item.complete:
            raise HTTPException(409, "Already uploaded")
        try:
            offset = int(request.headers.get("upload-offset", ""))
        except ValueError:
            raise HTTPException(400, "Upload-Offset header is required")
        if offset != item.received:
            raise HTTPException(409, f"Offset mismatch: server has {item.received}",
                                headers={"Upload-Offset": str(item.received)})
        written = 0
        async with aiofiles.open(data_path(item), "r+b") as f:
            await f.seek(offset)
            await f.truncate()
            async for data in request.stream():
                written += len(data)
                if written > MAX_PATCH or offset + written > item.size:
                    await f.truncate(offset)
                    raise HTTPException(413, "Chunk too large or past the declared size")
                await f.write(data)
        item.received = offset + written
        item.complete = item.received == item.size
        await session.commit()
    if item.complete:
        _locks.pop(item_id, None)
    return item


@router.get("/items/{item_id}/data")
async def download_data(item_id: str, request: Request, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    item = await _item(session, user, item_id)
    if not item.complete:
        raise HTTPException(409, "Not ready")
    return ranged_file_response(request, data_path(item), "application/octet-stream", f"{item.id}.bin", inline=False)


@router.put("/items/{item_id}/thumb", status_code=204)
async def upload_thumb(item_id: str, request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    item = await _item(session, user, item_id)
    body = await request.body()
    if not 16 < len(body) <= MAX_THUMB:
        raise HTTPException(413, "Thumbnail too large")
    thumb_path(item).write_bytes(body)
    item.has_thumb = True
    await session.commit()


@router.get("/items/{item_id}/thumb")
async def get_thumb(item_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    item = await _item(session, user, item_id)
    path = thumb_path(item)
    if not item.has_thumb or not path.is_file():
        raise HTTPException(404, "No thumbnail yet")
    return Response(path.read_bytes(), media_type="application/octet-stream",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.patch("/items/{item_id}", response_model=VaultItemOut)
async def rename_item(item_id: str, body: VaultItemUpdateIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    item = await _item(session, user, item_id)
    item.meta = body.meta
    await session.commit()
    return item


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(item_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    item = await _item(session, user, item_id)
    data_path(item).unlink(missing_ok=True)
    thumb_path(item).unlink(missing_ok=True)
    await session.delete(item)
    await session.commit()


async def purge_unfinished(session: AsyncSession) -> int:
    """Uploads that were started more than a day ago and never finished."""
    from datetime import timedelta

    from ..models import utcnow

    old = (await session.scalars(select(VaultItem).where(
        VaultItem.complete.is_(False), VaultItem.created_at < utcnow() - timedelta(days=1)))).all()
    for item in old:
        data_path(item).unlink(missing_ok=True)
        thumb_path(item).unlink(missing_ok=True)
        await session.delete(item)
    await session.commit()
    return len(old)
