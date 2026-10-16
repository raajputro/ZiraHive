"""Search inside files, and the document scanner (pages from the camera -> a searchable PDF)."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Asset, AssetText, User, new_id
from ..schemas import AssetOut, ScanFinishIn, SearchHit
from ..security import current_user
from ..services import storage, textsearch
from .uploads import ensure_folders

router = APIRouter(prefix="/api", tags=["search"])

MAX_PAGE = 15 * 1024 * 1024
MAX_PAGES = 60


@router.get("/search", response_model=list[SearchHit])
async def search_files(q: str = Query(min_length=2, max_length=200), limit: int = Query(50, ge=1, le=200),
                       user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Your files whose name, or the words inside them, contain `q`."""
    like = f"%{q.strip()}%"
    rows = (await session.execute(
        select(Asset, AssetText.text).outerjoin(AssetText, AssetText.asset_id == Asset.id)
        .where(Asset.owner_id == user.id, Asset.deleted_at.is_(None),
               or_(Asset.filename.ilike(like), and_(AssetText.text.is_not(None), AssetText.text.ilike(like))))
        .order_by(Asset.filename.ilike(like).desc(), func.coalesce(Asset.updated_at, Asset.created_at).desc())
        .limit(limit))).all()
    hits = []
    for asset, text in rows:
        snip = textsearch.snippet(text, q.strip()) if text else None
        hits.append(SearchHit(asset=AssetOut.model_validate(asset), snippet=snip,
                              in_text=bool(snip) and q.strip().lower() not in asset.filename.lower()))
    return hits


@router.get("/assets/{asset_id}/text")
async def asset_text(asset_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> dict:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.owner_id != user.id:
        raise HTTPException(404, "File not found")
    row = await session.get(AssetText, asset_id)
    return {"text": row.text if row else None, "method": row.method if row else None}


# ------------------------------------------------------------------ scanner

def _scan_dir(user: User, scan_id: str) -> Path:
    if not scan_id.isalnum():
        raise HTTPException(400, "Bad scan")
    return get_settings().upload_dir / "scans" / user.id / scan_id


@router.post("/scans", status_code=201)
async def start_scan(user: User = Depends(current_user)) -> dict:
    scan_id = new_id()
    _scan_dir(user, scan_id).mkdir(parents=True)
    return {"id": scan_id}


@router.put("/scans/{scan_id}/pages/{n}", status_code=204)
async def add_page(scan_id: str, n: int, request: Request, user: User = Depends(current_user)):
    d = _scan_dir(user, scan_id)
    if not d.is_dir():
        raise HTTPException(404, "Scan not found")
    if not 1 <= n <= MAX_PAGES:
        raise HTTPException(400, f"A scan can have up to {MAX_PAGES} pages")
    data = await request.body()
    if not data or len(data) > MAX_PAGE or data[:3] != b"\xff\xd8\xff":
        raise HTTPException(415, "Each page must be a JPEG picture")
    (d / f"{n:03d}.jpg").write_bytes(data)


def _make_pdf(pages: list[Path], out: Path) -> str:
    """A PDF with the page pictures and, when Tesseract is there, invisible text on top so it's searchable."""
    exe = textsearch.tesseract()
    if exe:
        lst = out.with_suffix(".list")
        lst.write_text("\n".join(str(p) for p in pages) + "\n", "utf-8")
        base = out.with_suffix("")
        try:
            subprocess.run([exe, str(lst), str(base), "-l", get_settings().ocr_languages, "pdf", "txt"],
                           check=True, capture_output=True, timeout=60 * len(pages) + 60)
            text = base.with_suffix(".txt").read_text("utf-8", "replace") if base.with_suffix(".txt").exists() else ""
            if out.is_file():
                return text
        except Exception:
            pass
    from PIL import Image

    images = [Image.open(p).convert("RGB") for p in pages]
    images[0].save(out, "PDF", save_all=True, append_images=images[1:], resolution=200)
    return ""


@router.post("/scans/{scan_id}/finish", response_model=AssetOut, status_code=201)
async def finish_scan(scan_id: str, body: ScanFinishIn, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    d = _scan_dir(user, scan_id)
    pages = sorted(d.glob("*.jpg")) if d.is_dir() else []
    if not pages:
        raise HTTPException(400, "Add at least one page")
    folder = storage.normalize_folder(body.folder)
    name = storage.safe_name(body.title.removesuffix(".pdf")) + ".pdf"
    pdf = d / "scan.pdf"
    text = await asyncio.to_thread(_make_pdf, pages, pdf)
    import hashlib

    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    size = pdf.stat().st_size
    if user.quota_bytes is not None:
        from .auth import used_bytes

        if await used_bytes(session, user.id) + size > user.quota_bytes:
            shutil.rmtree(d, ignore_errors=True)
            raise HTTPException(507, "Storage quota exceeded")
    target, rel = storage.unique_target(user.username, folder, name)
    await asyncio.to_thread(shutil.move, str(pdf), str(target))
    asset = Asset(owner_id=user.id, folder=folder, filename=target.name, size=size, mime="application/pdf",
                  kind="document", sha256=digest, storage_path=rel)
    session.add(asset)
    await ensure_folders(session, user.id, folder)
    await session.flush()
    session.add(AssetText(asset_id=asset.id, text=textsearch._clean(text), method="ocr" if text.strip() else "none",
                          pages=len(pages), sha256=digest))
    await session.commit()
    shutil.rmtree(d, ignore_errors=True)
    return asset


@router.delete("/scans/{scan_id}", status_code=204)
async def cancel_scan(scan_id: str, user: User = Depends(current_user)):
    shutil.rmtree(_scan_dir(user, scan_id), ignore_errors=True)
