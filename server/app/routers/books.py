"""Audiobooks, ebooks and comics: browsing, reading, listening and progress."""
from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import Book, BookProgress, Library, User, utcnow
from ..schemas import (AudioPartOut, AudioReadyOut, BookDetailOut, BookOut, BookProgressIn, BookProgressOut,
                       ChapterOut)
from ..security import current_user
from ..services import activity, audio_convert, storage
from ..services.ranged import ranged_file_response
from ..services.shelf_files import AUDIO_MIME, comic_page_bytes, pdf_page_png, resized_page
from .music import safe_path, visible_libraries

router = APIRouter(prefix="/api/books", tags=["books"])

BOOK_KINDS = {"audiobooks", "books", "comics"}
PAGE_WIDTHS = (720, 1080, 1600, 2400)
_FILE_MIME = {"epub": "application/epub+zip", "pdf": "application/pdf", "cbz": "application/vnd.comicbook+zip",
              "cbr": "application/vnd.comicbook-rar", "cb7": "application/x-cb7", "cbt": "application/x-cbt"}


async def _lib_ids(session: AsyncSession, user: User) -> list[str]:
    return list(await visible_libraries(session, user, BOOK_KINDS))


async def _book(session: AsyncSession, user: User, book_id: str) -> tuple[Book, Library]:
    b = await session.get(Book, book_id)
    if b is None or b.missing or b.library_id not in await _lib_ids(session, user):
        raise HTTPException(404, "Book not found")
    return b, await session.get(Library, b.library_id)


async def _progress(session: AsyncSession, user: User, ids: list[str]) -> dict[str, BookProgress]:
    if not ids:
        return {}
    rows = (await session.scalars(select(BookProgress).where(BookProgress.user_id == user.id,
                                                             BookProgress.book_id.in_(ids)))).all()
    return {p.book_id: p for p in rows}


def _prog_out(p: BookProgress | None) -> BookProgressOut | None:
    if p is None:
        return None
    return BookProgressOut(position=p.position, locator=p.locator, fraction=p.fraction, finished=p.finished,
                           updated_at=p.updated_at)


async def _outs(session: AsyncSession, user: User, books: list[Book]) -> list[BookOut]:
    progress = await _progress(session, user, [b.id for b in books])
    out = []
    for b in books:
        o = BookOut.model_validate(b)
        o.progress = _prog_out(progress.get(b.id))
        out.append(o)
    return out


def _parts(b: Book) -> list[dict]:
    return json.loads(b.parts_json) if b.parts_json and b.kind == "audiobook" else []


def _pages(b: Book) -> list[str]:
    if b.kind != "comic" or not b.parts_json:
        return []
    return json.loads(b.parts_json).get("pages", [])


@router.get("", response_model=list[BookOut])
async def list_books(kind: str | None = Query(None, pattern="^(audiobook|ebook|comic|reading)$"),
                     library_id: str | None = None, q: str | None = None, series: str | None = None,
                     sort: str = Query("added", pattern="^(added|title|author|series)$"),
                     limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0),
                     user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """`kind=reading` means ebooks and comics together."""
    ids = await _lib_ids(session, user)
    if library_id:
        ids = [i for i in ids if i == library_id]
    stmt = select(Book).where(Book.library_id.in_(ids), Book.missing.is_(False))
    if kind == "reading":
        stmt = stmt.where(Book.kind.in_(["ebook", "comic"]))
    elif kind:
        stmt = stmt.where(Book.kind == kind)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Book.title.ilike(like), Book.author.ilike(like), Book.series_name.ilike(like),
                              Book.narrator.ilike(like)))
    if series:
        stmt = stmt.where(Book.series_name == series)
    order = {"added": [Book.added_at.desc()], "title": [func.lower(Book.title)],
             "author": [func.lower(Book.author), func.lower(Book.title)],
             "series": [func.lower(Book.series_name), Book.series_index, func.lower(Book.title)]}[sort]
    if series:
        order = [Book.series_index, func.lower(Book.title)]
    rows = (await session.scalars(stmt.order_by(*order).limit(limit).offset(offset))).all()
    return await _outs(session, user, list(rows))


@router.get("/continue", response_model=list[BookOut])
async def continue_books(kind: str | None = Query(None, pattern="^(audiobook|ebook|comic|reading)$"),
                         user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    ids = await _lib_ids(session, user)
    stmt = (select(Book).join(BookProgress, and_(BookProgress.book_id == Book.id, BookProgress.user_id == user.id))
            .where(Book.library_id.in_(ids), Book.missing.is_(False), BookProgress.finished.is_(False),
                   or_(BookProgress.fraction > 0, BookProgress.position > 0))
            .order_by(BookProgress.updated_at.desc()).limit(20))
    if kind == "reading":
        stmt = stmt.where(Book.kind.in_(["ebook", "comic"]))
    elif kind:
        stmt = stmt.where(Book.kind == kind)
    return await _outs(session, user, list((await session.scalars(stmt)).all()))


@router.get("/{book_id}", response_model=BookDetailOut)
async def get_book(book_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    b, _lib = await _book(session, user, book_id)
    base = (await _outs(session, user, [b]))[0]
    out = BookDetailOut(**base.model_dump(), description=b.description, language=b.language)
    start = 0.0
    chapters = json.loads(b.chapters_json) if b.chapters_json else []
    for i, part in enumerate(_parts(b)):
        title = chapters[i]["title"] if len(chapters) == len(_parts(b)) else f"Part {i + 1}"
        out.parts.append(AudioPartOut(index=i, title=title, start=start, duration=part["duration"],
                                      playable=part["playable"]))
        start += part["duration"]
    out.chapters = [ChapterOut(**c) for c in chapters]
    if b.kind == "comic" and b.parts_json:
        out.rtl = bool(json.loads(b.parts_json).get("rtl"))
    out.downloadable = b.format != "images" and not (b.kind == "audiobook" and len(out.parts) > 1)
    if b.series_name:
        nxt = await session.scalar(
            select(Book.id).where(Book.library_id == b.library_id, Book.series_name == b.series_name,
                                  Book.missing.is_(False), Book.id != b.id,
                                  Book.series_index > (b.series_index if b.series_index is not None else -1))
            .order_by(Book.series_index).limit(1))
        out.next_in_series = nxt
    return out


@router.get("/{book_id}/cover")
async def book_cover(book_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    b, _ = await _book(session, user, book_id)
    path = storage.cover_path("book", b.id)
    if not b.cover_ready or not path.is_file():
        raise HTTPException(404, "No cover")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{book_id}/file")
async def book_file(book_id: str, request: Request, download: bool = False, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    """The EPUB or PDF itself (for the reader), or any single-file book as a download."""
    b, lib = await _book(session, user, book_id)
    path = safe_path(lib, b.rel_path)
    if b.format == "images" or path.is_dir():
        raise HTTPException(400, "This comic is a folder of pictures; it can't be downloaded as one file")
    mime = _FILE_MIME.get(b.format) or AUDIO_MIME.get(path.suffix.lower(), "application/octet-stream")
    return ranged_file_response(request, path, mime, path.name, inline=not download)


# ---------------------------------------------------------------- comics

@router.get("/{book_id}/pages/{page}")
async def comic_page(book_id: str, page: int, w: int = Query(1600), user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    """One page (from 1) of a comic, or of a PDF, as a picture scaled to fit `w` pixels wide."""
    b, lib = await _book(session, user, book_id)
    width = min(PAGE_WIDTHS, key=lambda x: abs(x - w))
    count = b.pages or 0
    if page < 1 or page > count:
        raise HTTPException(404, "No such page")
    cached = storage.page_cache_path(b.id, page, width)
    for ext, mime in ((".webp", "image/webp"), (".jpg", "image/jpeg")):
        if cached.with_suffix(ext).is_file():
            os.utime(cached.with_suffix(ext))
            return FileResponse(cached.with_suffix(ext), media_type=mime,
                                headers={"Cache-Control": "private, max-age=604800"})
    path = safe_path(lib, b.rel_path)

    def render() -> tuple[bytes, str]:
        if b.format == "pdf":
            png = pdf_page_png(path, page, width)
            if png is None:
                raise HTTPException(501, "Showing PDF pages as pictures needs poppler-utils")
            return resized_page(png, width)
        return resized_page(comic_page_bytes(path, _pages(b)[page - 1]), width)

    try:
        data, mime = await asyncio.to_thread(render)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "This page couldn't be read")
    target = cached.with_suffix(".webp" if mime == "image/webp" else ".jpg")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=604800"})


# ------------------------------------------------------------- audiobooks

def _part(b: Book, index: int) -> dict:
    parts = _parts(b)
    if not 0 <= index < len(parts):
        raise HTTPException(404, "No such part")
    return parts[index]


@router.get("/{book_id}/audio/{index}/prepare", response_model=AudioReadyOut)
async def prepare_part(book_id: str, index: int, force: bool = False, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    b, lib = await _book(session, user, book_id)
    part = _part(b, index)
    if part["playable"] and not force:
        return AudioReadyOut(ready=True)
    ready, failed = audio_convert.status(safe_path(lib, part["rel"]), f"book-{b.id}-{index}")
    return AudioReadyOut(ready=ready, failed=failed)


@router.get("/{book_id}/audio/{index}")
async def stream_part(book_id: str, index: int, request: Request, converted: bool = False,
                      user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    b, lib = await _book(session, user, book_id)
    part = _part(b, index)
    path = safe_path(lib, part["rel"])
    activity.stream_seen(user.id, user.username, f"book-{b.id}", f"{b.title} (audiobook)")
    if part["playable"] and not converted:
        return ranged_file_response(request, path, AUDIO_MIME.get(path.suffix.lower(), "audio/mpeg"), path.name)
    copy = audio_convert.ready_path(path, f"book-{b.id}-{index}")
    if copy is None:
        audio_convert.status(path, f"book-{b.id}-{index}")
        raise HTTPException(409, "This part is still being converted")
    return ranged_file_response(request, copy, "audio/mpeg", path.stem + ".mp3")


# ---------------------------------------------------------------- progress

@router.put("/{book_id}/progress", response_model=BookProgressOut)
async def save_progress(book_id: str, body: BookProgressIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    b, _ = await _book(session, user, book_id)
    p = await session.scalar(select(BookProgress).where(BookProgress.user_id == user.id,
                                                        BookProgress.book_id == b.id))
    if p is None:
        p = BookProgress(user_id=user.id, book_id=b.id)
        session.add(p)
    p.position, p.fraction = body.position, body.fraction
    if body.locator is not None:
        p.locator = body.locator
    p.finished = body.finished if body.finished is not None else body.fraction >= 0.98
    p.updated_at = utcnow()
    await session.commit()
    return _prog_out(p)


@router.delete("/{book_id}/progress", status_code=204)
async def reset_progress(book_id: str, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    b, _ = await _book(session, user, book_id)
    p = await session.scalar(select(BookProgress).where(BookProgress.user_id == user.id,
                                                        BookProgress.book_id == b.id))
    if p:
        await session.delete(p)
        await session.commit()
