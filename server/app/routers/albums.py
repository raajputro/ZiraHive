"""Albums, which can be shared with family members on the same GharBox."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Album, AlbumItem, AlbumMember, Asset, User
from ..schemas import (AlbumDetailOut, AlbumIn, AlbumMemberOut, AlbumOut, AlbumUpdateIn, AssetIdsIn,
                       AssetOut, MembersIn)
from ..security import current_user
from ..services.events import audit, notify

router = APIRouter(prefix="/api/albums", tags=["albums"])


async def _membership(session: AsyncSession, album: Album, user: User) -> AlbumMember | None:
    return await session.scalar(select(AlbumMember).where(
        AlbumMember.album_id == album.id, AlbumMember.user_id == user.id))


async def _get_album(session: AsyncSession, album_id: str, user: User) -> tuple[Album, bool, bool]:
    """Returns (album, is_owner, can_add). 404 for albums the user can't see."""
    album = await session.get(Album, album_id)
    if album is None:
        raise HTTPException(404, "Album not found")
    if album.owner_id == user.id:
        return album, True, True
    member = await _membership(session, album, user)
    if member is None:
        raise HTTPException(404, "Album not found")
    return album, False, member.can_add


async def _album_out(session: AsyncSession, album: Album, user: User) -> AlbumOut:
    owner = await session.get(User, album.owner_id)
    rows = (await session.execute(select(AlbumMember, User.username).join(
        User, User.id == AlbumMember.user_id).where(AlbumMember.album_id == album.id)
        .order_by(User.username))).all()
    members = [AlbumMemberOut(user_id=m.user_id, username=name, can_add=m.can_add) for m, name in rows]
    mine = next((m for m in members if m.user_id == user.id), None)
    count = await session.scalar(select(func.count()).select_from(AlbumItem).join(
        Asset, Asset.id == AlbumItem.asset_id).where(AlbumItem.album_id == album.id,
                                                     Asset.deleted_at.is_(None))) or 0
    cover = album.cover_asset_id
    if cover is None:
        cover = await session.scalar(select(AlbumItem.asset_id).join(Asset, Asset.id == AlbumItem.asset_id)
                                     .where(AlbumItem.album_id == album.id, Asset.deleted_at.is_(None),
                                            Asset.thumb_ready.is_(True))
                                     .order_by(Asset.taken_at.desc()).limit(1))
    is_owner = album.owner_id == user.id
    return AlbumOut(id=album.id, title=album.title, owner_id=album.owner_id,
                    owner=owner.username if owner else "?", is_owner=is_owner,
                    can_add=is_owner or bool(mine and mine.can_add), cover_asset_id=cover,
                    item_count=count, members=members, created_at=album.created_at)


async def _add_items(session: AsyncSession, album: Album, user: User, ids: list[str]) -> int:
    owned = set((await session.scalars(select(Asset.id).where(
        Asset.id.in_(ids), Asset.owner_id == user.id, Asset.deleted_at.is_(None)))).all())
    if len(owned) != len(set(ids)):
        raise HTTPException(400, "You can only add your own photos and videos")
    present = set((await session.scalars(select(AlbumItem.asset_id).where(
        AlbumItem.album_id == album.id, AlbumItem.asset_id.in_(ids)))).all())
    for asset_id in owned - present:
        session.add(AlbumItem(album_id=album.id, asset_id=asset_id, added_by=user.id))
    return len(owned - present)


@router.get("", response_model=list[AlbumOut])
async def list_albums(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    member_of = select(AlbumMember.album_id).where(AlbumMember.user_id == user.id)
    albums = (await session.scalars(select(Album).where(
        (Album.owner_id == user.id) | Album.id.in_(member_of)).order_by(Album.created_at.desc()))).all()
    return [await _album_out(session, a, user) for a in albums]


@router.post("", response_model=AlbumOut, status_code=201)
async def create_album(body: AlbumIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    album = Album(owner_id=user.id, title=body.title.strip())
    session.add(album)
    await session.flush()
    if body.asset_ids:
        await _add_items(session, album, user, body.asset_ids)
    await session.commit()
    return await _album_out(session, album, user)


@router.get("/{album_id}", response_model=AlbumDetailOut)
async def get_album(album_id: str, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    album, _, _ = await _get_album(session, album_id, user)
    items = (await session.scalars(select(Asset).join(AlbumItem, AlbumItem.asset_id == Asset.id).where(
        AlbumItem.album_id == album.id, Asset.deleted_at.is_(None)).order_by(Asset.taken_at.desc()))).all()
    out = await _album_out(session, album, user)
    return AlbumDetailOut(**out.model_dump(), items=[AssetOut.model_validate(a) for a in items])


@router.patch("/{album_id}", response_model=AlbumOut)
async def update_album(album_id: str, body: AlbumUpdateIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    album, is_owner, _ = await _get_album(session, album_id, user)
    if not is_owner:
        raise HTTPException(403, "Only the album's owner can change it")
    if body.title:
        album.title = body.title.strip()
    if body.cover_asset_id is not None:
        album.cover_asset_id = body.cover_asset_id or None
    await session.commit()
    return await _album_out(session, album, user)


@router.delete("/{album_id}", status_code=204)
async def delete_album(album_id: str, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Deletes the album only; the photos stay in everyone's library."""
    album, is_owner, _ = await _get_album(session, album_id, user)
    if not is_owner:
        raise HTTPException(403, "Only the album's owner can delete it")
    await session.delete(album)
    await session.commit()


@router.post("/{album_id}/items", response_model=AlbumOut)
async def add_items(album_id: str, body: AssetIdsIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    album, is_owner, can_add = await _get_album(session, album_id, user)
    if not can_add:
        raise HTTPException(403, "You can view this album but not add to it")
    added = await _add_items(session, album, user, body.asset_ids)
    if added and not is_owner:
        owner = await session.get(User, album.owner_id)
        await notify(session, owner, "album", f"{user.username} added {added} to {album.title}",
                     link=f"/photos/albums/{album.id}")
    await session.commit()
    return await _album_out(session, album, user)


@router.post("/{album_id}/items/remove", response_model=AlbumOut)
async def remove_items(album_id: str, body: AssetIdsIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """The owner can remove anything; members can remove what they added."""
    album, is_owner, _ = await _get_album(session, album_id, user)
    q = delete(AlbumItem).where(AlbumItem.album_id == album.id, AlbumItem.asset_id.in_(body.asset_ids))
    if not is_owner:
        q = q.where(AlbumItem.added_by == user.id)
    await session.execute(q)
    await session.commit()
    return await _album_out(session, album, user)


@router.put("/{album_id}/members", response_model=AlbumOut)
async def set_members(album_id: str, body: MembersIn, request: Request, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    album, is_owner, _ = await _get_album(session, album_id, user)
    if not is_owner:
        raise HTTPException(403, "Only the album's owner can choose who it's shared with")
    wanted = {m.user_id: m for m in body.members if m.user_id != user.id}
    existing = {m.user_id: m for m in (await session.scalars(select(AlbumMember).where(
        AlbumMember.album_id == album.id))).all()}
    for uid, m in existing.items():
        if uid not in wanted:
            await session.delete(m)
    for uid, m in wanted.items():
        if uid in existing:
            existing[uid].can_add = m.can_add
            continue
        member = await session.get(User, uid)
        if member is None:
            raise HTTPException(400, "Unknown person")
        session.add(AlbumMember(album_id=album.id, user_id=uid, can_add=m.can_add))
        await notify(session, member, "album", f"{user.username} shared the album {album.title} with you",
                     link=f"/photos/albums/{album.id}")
    await audit(session, "album_shared", user, detail=f"{album.title}: {len(wanted)} people", request=request)
    await session.commit()
    return await _album_out(session, album, user)
