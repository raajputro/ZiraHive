"""For the PC sync client: everything under one folder in Files, in one listing.

The client compares it with the PC folder and with what both looked like at the last sync,
then uploads, downloads, trashes or keeps both copies. It uses the normal upload API (with
`replace`) and file download; deletions go to the GharBox trash, never straight away.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Asset, Folder, User
from ..security import current_user
from ..services import storage

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncFile(BaseModel):
    id: str
    path: str  # relative to the root, with / separators
    size: int
    sha256: str
    modified: datetime


class SyncTree(BaseModel):
    root: str
    folders: list[str]
    files: list[SyncFile]


def _under(path: str, root: str) -> str | None:
    if root == "/":
        return path.lstrip("/")
    if path == root:
        return ""
    if path.startswith(root + "/"):
        return path[len(root) + 1:]
    return None


@router.get("/tree", response_model=SyncTree)
async def sync_tree(root: str = "/", user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    root = storage.normalize_folder(root)
    like = f"{root.rstrip('/')}/%"
    assets = (await session.scalars(select(Asset).where(
        Asset.owner_id == user.id, Asset.deleted_at.is_(None),
        or_(Asset.folder == root, Asset.folder.like(like))))).all()
    folders = (await session.scalars(select(Folder.path).where(
        Folder.owner_id == user.id, or_(Folder.path == root, Folder.path.like(like))))).all()
    files = []
    for a in assets:
        rel = _under(a.folder, root)
        if rel is None:
            continue
        files.append(SyncFile(id=a.id, path=f"{rel}/{a.filename}".lstrip("/"), size=a.size, sha256=a.sha256,
                              modified=a.updated_at or a.created_at))
    rels = sorted({r for f in folders if (r := _under(f, root))})
    return SyncTree(root=root, folders=rels, files=sorted(files, key=lambda f: f.path))
