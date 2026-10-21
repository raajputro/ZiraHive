"""Photo search by description, people, photo clean-up, AI subtitles and Ask your files.

Everything works on the signed-in person's own photos and files only. Clean-up needs no AI; the
rest uses the optional local AI (docker compose --profile ai) and says so when it's off.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Asset, AssetText, DocChunk, Face, MediaItem, Person, PhotoVector, User
from ..schemas import AssetOut
from ..security import admin_user, current_user
from ..services import ai, doc_compare, jobs, photo_quality, photo_search, storage, textsearch

router = APIRouter(prefix="/api", tags=["smart"])
log = logging.getLogger(__name__)

AI_OFF = {"code": "ai_off", "message": "Local AI isn't running. An admin can start it with "
                                        "docker compose --profile ai up -d (see docs/AI.md)."}
_BANGLA = re.compile(r"[ঀ-৿]")


# ------------------------------------------------------------ status

class AiStatus(BaseModel):
    ai: bool
    ollama: bool
    models: dict = {}
    photos: int = 0
    photos_indexed: int = 0
    people: int = 0
    documents_ready: int = 0
    llm_model: str
    embed_model: str


@router.get("/ai/status", response_model=AiStatus)
async def ai_status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    a, o = await ai.ai_info(), await ai.ollama_info()
    mine = (Asset.owner_id == user.id, Asset.kind == "photo", Asset.deleted_at.is_(None))
    s = get_settings()
    return AiStatus(
        ai=a is not None, ollama=o is not None, models=(a or {}).get("models", {}),
        photos=await session.scalar(select(func.count()).select_from(Asset).where(*mine)) or 0,
        photos_indexed=await session.scalar(select(func.count()).select_from(Asset).where(
            *mine, Asset.ai_indexed_at.is_not(None))) or 0,
        people=await session.scalar(select(func.count()).select_from(Person).where(
            Person.owner_id == user.id, Person.hidden.is_(False))) or 0,
        documents_ready=await session.scalar(select(func.count(func.distinct(DocChunk.asset_id))).where(
            DocChunk.owner_id == user.id)) or 0,
        llm_model=s.llm_model, embed_model=s.embed_model)


@router.post("/admin/ai/catch-up", status_code=202)
async def ai_catch_up(_: User = Depends(admin_user)):
    """Index everything not yet done (otherwise this happens every night)."""
    ai.forget_status()
    await jobs.enqueue("ai_backfill")
    return {"ok": True}


# ------------------------------------------------------------ photo search

class PhotoHit(BaseModel):
    asset: AssetOut
    score: float


class PhotoSearchOut(BaseModel):
    query: str
    searched_for: str  # in English, when a Bangla query was translated
    hits: list[PhotoHit]


@router.get("/photos/search", response_model=PhotoSearchOut)
async def search_photos(q: str, response: Response, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    q = q.strip()[:200]
    if not q:
        raise HTTPException(400, "Type what's in the photo")
    if not await ai.ai_info():
        raise HTTPException(409, AI_OFF)
    took: dict[str, float] = {}
    started = mark = time.perf_counter()

    def step(name: str) -> None:
        nonlocal mark
        now = time.perf_counter()
        took[name] = (now - mark) * 1000
        mark = now

    key = " ".join(q.lower().split())
    english = q
    if _BANGLA.search(q):
        english = photo_search.translations.get(key)
        if english is None:
            english = q
            if await ai.ollama_info():
                try:  # the picture model only knows English words
                    english = (await ai.chat("Translate the user's words into short, plain English. "
                                             "Reply with the translation only.", q, max_words=24)).strip().strip('"')[:200] or q
                    photo_search.translations.put(key, english)
                except (ai.AiOff, RuntimeError):
                    english = q
        step("translate")
    qv = photo_search.phrase_vectors.get(english.lower())
    if qv is None:
        try:
            qv = await ai.clip_text(f"a photo of {english}")
        except ai.AiOff:
            raise HTTPException(409, AI_OFF) from None
        photo_search.phrase_vectors.put(english.lower(), qv)
    step("words")
    ids, matrix = await photo_search.vectors_for(session, user.id)
    step("load")
    ranked = await asyncio.to_thread(photo_search.rank, qv, ids, matrix, 200, 0.2)
    if ranked:  # keep the clear matches: within reach of the best one
        top = ranked[0][1]
        ranked = [(i, s) for i, s in ranked if s >= top - 0.06]
    step("match")
    assets = {a.id: a for a in (await session.scalars(select(Asset).where(
        Asset.id.in_([i for i, _ in ranked]), Asset.deleted_at.is_(None)))).all()}
    hits = [PhotoHit(asset=AssetOut.model_validate(assets[i]), score=round(s, 4)) for i, s in ranked if i in assets][:80]
    step("photos")
    total = (time.perf_counter() - started) * 1000
    response.headers["Server-Timing"] = ", ".join(f"{k};dur={v:.0f}" for k, v in took.items())
    (log.info if total > 1500 else log.debug)("photo search %r: %.0f ms (%s)", q, total,
                                             ", ".join(f"{k} {v:.0f} ms" for k, v in took.items()))
    return PhotoSearchOut(query=q, searched_for=english, hits=hits)


# ------------------------------------------------------------ people

class PersonOut(BaseModel):
    id: str
    name: str | None
    photos: int
    cover_face: str | None
    hidden: bool = False


class PersonIn(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    hidden: bool | None = None


class MergeIn(BaseModel):
    into: str


async def _person(session: AsyncSession, user: User, pid: str) -> Person:
    p = await session.get(Person, pid)
    if p is None or p.owner_id != user.id:
        raise HTTPException(404, "No such person")
    return p


@router.get("/people", response_model=list[PersonOut])
async def people(hidden: bool = False, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(Person, func.count(func.distinct(Face.asset_id)))
        .join(Face, Face.person_id == Person.id).join(Asset, Asset.id == Face.asset_id)
        .where(Person.owner_id == user.id, Person.hidden.is_(hidden), Asset.deleted_at.is_(None))
        .group_by(Person.id))).all()
    out = []
    for p, n in rows:
        if n < 2 and not p.name:
            continue  # one photo isn't enough to call it a person yet
        cover = await session.scalar(select(Face.id).join(Asset, Asset.id == Face.asset_id).where(
            Face.person_id == p.id, Asset.deleted_at.is_(None)).order_by(Face.confirmed.desc(), Face.score.desc()).limit(1))
        out.append(PersonOut(id=p.id, name=p.name, photos=n, cover_face=cover, hidden=p.hidden))
    out.sort(key=lambda p: (p.name is None, -p.photos, (p.name or "").lower()))
    return out


@router.get("/people/{pid}/photos", response_model=list[AssetOut])
async def person_photos(pid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _person(session, user, pid)
    rows = (await session.scalars(select(Asset).join(Face, Face.asset_id == Asset.id).where(
        Face.person_id == pid, Asset.deleted_at.is_(None)).distinct().order_by(Asset.taken_at.desc()))).all()
    return [AssetOut.model_validate(a) for a in rows]


@router.patch("/people/{pid}", response_model=PersonOut)
async def update_person(pid: str, body: PersonIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    p = await _person(session, user, pid)
    if body.name is not None:
        p.name = body.name.strip() or None
    if body.hidden is not None:
        p.hidden = body.hidden
    await session.commit()
    n = await session.scalar(select(func.count(func.distinct(Face.asset_id))).where(Face.person_id == p.id)) or 0
    cover = await session.scalar(select(Face.id).where(Face.person_id == p.id).order_by(Face.score.desc()).limit(1))
    return PersonOut(id=p.id, name=p.name, photos=n, cover_face=cover, hidden=p.hidden)


@router.post("/people/{pid}/merge", status_code=204)
async def merge_people(pid: str, body: MergeIn, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    """Same person found twice: all of `pid`'s faces go to `into`."""
    a, b = await _person(session, user, pid), await _person(session, user, body.into)
    if a.id == b.id:
        return
    for f in (await session.scalars(select(Face).where(Face.person_id == a.id))).all():
        f.person_id = b.id
    if not b.name and a.name:
        b.name = a.name
    await session.delete(a)
    await session.commit()


@router.delete("/people/{pid}/faces/{face_id}", status_code=204)
async def not_this_person(pid: str, face_id: str, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    await _person(session, user, pid)
    f = await session.get(Face, face_id)
    if f is None or f.person_id != pid:
        raise HTTPException(404, "No such face")
    f.person_id, f.confirmed = None, True  # stays out of this person, also when photos are indexed again
    await session.commit()


@router.get("/people/{pid}/faces")
async def person_faces(pid: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await _person(session, user, pid)
    rows = (await session.execute(select(Face.id, Face.asset_id).join(Asset, Asset.id == Face.asset_id).where(
        Face.person_id == pid, Asset.deleted_at.is_(None)).order_by(Face.score.desc()))).all()
    return [{"id": r[0], "asset_id": r[1]} for r in rows]


def _crop(src: Path, box: list[float], dest: Path) -> None:
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im.draft("RGB", (1600, 1600))
        w, h = im.size
        x, y, bw, bh = box
        cx, cy, side = (x + bw / 2) * w, (y + bh / 2) * h, max(bw * w, bh * h) * 1.6
        left, top = max(0, cx - side / 2), max(0, cy - side / 2)
        face = im.convert("RGB").crop((int(left), int(top), int(min(w, left + side)), int(min(h, top + side))))
        face.thumbnail((240, 240))
        dest.parent.mkdir(parents=True, exist_ok=True)
        face.save(dest, "WEBP", quality=82)


@router.get("/faces/{face_id}/crop")
async def face_crop(face_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    f = await session.get(Face, face_id)
    if f is None or f.owner_id != user.id:
        raise HTTPException(404, "No such face")
    dest = get_settings().cache_dir / "faces" / f"{f.id}.webp"
    if not dest.exists():
        asset = await session.get(Asset, f.asset_id)
        try:
            await asyncio.to_thread(_crop, storage.abs_storage_path(asset.storage_path), json.loads(f.box), dest)
        except OSError:
            raise HTTPException(404, "The photo is gone") from None
    return FileResponse(dest, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})


# ------------------------------------------------------------ clean-up (no AI needed)

class DuplicateGroup(BaseModel):
    keep: str            # the best copy: biggest, then sharpest
    photos: list[AssetOut]


class CleanupOut(BaseModel):
    duplicates: list[DuplicateGroup]
    blurry: list[AssetOut]
    measured: int
    waiting: int  # photos not looked at yet (done in the background)


@router.get("/photos/cleanup", response_model=CleanupOut)
async def cleanup(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    base = (Asset.owner_id == user.id, Asset.kind == "photo", Asset.deleted_at.is_(None))
    photos = (await session.scalars(select(Asset).where(*base, Asset.phash.is_not(None)))).all()
    waiting = await session.scalar(select(func.count()).select_from(Asset).where(
        *base, Asset.phash.is_(None), Asset.sharpness.is_(None))) or 0
    if waiting:
        await jobs.enqueue("ai_backfill")  # measures them; harmless when already running
    by_id = {a.id: a for a in photos}
    groups = await asyncio.to_thread(photo_quality.duplicate_groups, [(a.id, a.phash) for a in photos])

    def rank(a: Asset):
        return ((a.width or 0) * (a.height or 0), a.sharpness or 0, a.size)

    dupes = []
    for g in groups:
        members = sorted((by_id[i] for i in g), key=rank, reverse=True)
        dupes.append(DuplicateGroup(keep=members[0].id, photos=[AssetOut.model_validate(a) for a in members]))
    dupes.sort(key=lambda d: -len(d.photos))
    in_groups = {i for g in groups for i in g}
    blurry = sorted((a for a in photos if a.sharpness is not None and a.sharpness < photo_quality.BLURRY
                     and a.id not in in_groups), key=lambda a: a.sharpness)[:300]
    return CleanupOut(duplicates=dupes[:200], blurry=[AssetOut.model_validate(a) for a in blurry],
                      measured=len(photos), waiting=waiting)


# ------------------------------------------------------------ duplicate documents

class DocDuplicateGroup(BaseModel):
    keep: str
    same: bool          # all exact copies; otherwise edited versions of one document
    similarity: float   # how much of the text the least alike two have in common (1.0 = identical)
    files: list[AssetOut]


class DocCleanupOut(BaseModel):
    groups: list[DocDuplicateGroup]
    checked: int
    waiting: int  # documents whose words haven't been read yet (done in the background)


@router.get("/files/duplicates", response_model=DocCleanupOut)
async def document_duplicates(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Copies and edited versions of the same document. The newest of each group is marked Keep."""
    rows = (await session.execute(
        select(Asset, AssetText.text, AssetText.sha256).outerjoin(AssetText, AssetText.asset_id == Asset.id)
        .where(Asset.owner_id == user.id, Asset.kind == "document", Asset.deleted_at.is_(None)))).all()
    by_id = {a.id: a for a, _, _ in rows}
    waiting = sum(1 for a, _, read_sha in rows
                  if read_sha != a.sha256 and textsearch.wanted(a.filename, a.folder, a.kind))
    if waiting:
        await jobs.enqueue("text_backfill")  # reads them; harmless when already running
    docs = [(a.id, a.sha256, text if read_sha == a.sha256 else None) for a, text, read_sha in rows]
    found = await asyncio.to_thread(doc_compare.duplicate_groups, docs)

    def newest(a: Asset):
        return (a.updated_at or a.created_at, a.size)

    groups = []
    for g in found:
        members = sorted((by_id[i] for i in g.ids), key=newest, reverse=True)
        groups.append(DocDuplicateGroup(keep=members[0].id, same=g.same, similarity=g.similarity,
                                        files=[AssetOut.model_validate(a) for a in members]))
    groups.sort(key=lambda g: (-len(g.files), g.files[0].filename.lower()))
    return DocCleanupOut(groups=groups[:300], checked=len(rows), waiting=waiting)


# ------------------------------------------------------------ AI subtitles

class SubtitlesIn(BaseModel):
    language: str | None = Field(default=None, max_length=8)  # None: detect from the speech


@router.post("/media/{media_id}/ai-subtitles", status_code=202)
async def make_subtitles(media_id: str, body: SubtitlesIn, _: User = Depends(admin_user),
                         session: AsyncSession = Depends(get_session)):
    item = await session.get(MediaItem, media_id)
    if item is None:
        raise HTTPException(404, "Not found")
    if not await ai.ai_info():
        raise HTTPException(409, AI_OFF)
    if item.ai_subtitles in ("queued", "working"):
        return {"status": item.ai_subtitles}
    item.ai_subtitles = "queued"
    await session.commit()
    await jobs.enqueue("transcribe", media_id, body.language)
    return {"status": "queued"}


# ------------------------------------------------------------ ask your files

class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class Source(BaseModel):
    n: int
    asset_id: str
    filename: str
    folder: str
    passage: str


class AskOut(BaseModel):
    answer: str
    sources: list[Source]


SYSTEM = ("You answer questions using only the passages from the person's own documents given below. "
          "Answer in the same language as the question (Bangla or English), briefly and plainly. "
          "After each fact, cite the passage it came from as [1], [2] and so on. "
          "If the passages don't contain the answer, say you couldn't find it in their files. Never make things up.")


@router.post("/ask", response_model=AskOut)
async def ask(body: AskIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if not await ai.ollama_info():
        raise HTTPException(409, AI_OFF)
    try:
        qv = (await ai.embed_texts([body.question]))[0]
    except ai.AiOff:
        raise HTTPException(409, AI_OFF) from None
    rows = (await session.execute(select(DocChunk.id, DocChunk.vector).join(Asset, Asset.id == DocChunk.asset_id).where(
        DocChunk.owner_id == user.id, Asset.deleted_at.is_(None)))).all()
    ranked = await asyncio.to_thread(ai.best, qv, [(r[0], r[1]) for r in rows], 6, 0.35)
    if not ranked:
        return AskOut(answer=("আপনার ফাইলে এ বিষয়ে কিছু পাওয়া যায়নি। কাগজপত্র পেছনে পড়া হয়; নতুনগুলোর জন্য একটু সময় লাগতে পারে।"
                              if _BANGLA.search(body.question) else
                              "I couldn't find anything about that in your files. Documents are read in the "
                              "background; new ones may need a little while."), sources=[])
    chunks = {c.id: c for c in (await session.scalars(select(DocChunk).where(DocChunk.id.in_([i for i, _ in ranked])))).all()}
    assets = {a.id: a for a in (await session.scalars(select(Asset).where(
        Asset.id.in_([c.asset_id for c in chunks.values()])))).all()}
    sources = []
    for n, (cid, _) in enumerate(ranked, 1):
        c = chunks[cid]
        a = assets[c.asset_id]
        sources.append(Source(n=n, asset_id=a.id, filename=a.filename, folder=a.folder, passage=c.text))
    context = "\n\n".join(f"[{s.n}] {s.filename} ({s.folder}):\n{s.passage}" for s in sources)
    try:
        answer = await ai.chat(SYSTEM, f"Passages:\n{context}\n\nQuestion: {body.question}")
    except (ai.AiOff, RuntimeError):
        raise HTTPException(409, AI_OFF) from None
    used = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    return AskOut(answer=answer, sources=[s for s in sources if s.n in used] or sources[:3])
