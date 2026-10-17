"""Background work for photo clean-up and the local AI.

  photo_quality   fingerprint + sharpness of one photo (always; no AI needed)
  ai_photo        CLIP vector and faces of one photo (when the ai container runs)
  doc_chunks      passages of one document, with their meaning as vectors (when Ollama runs)
  transcribe      AI subtitles for one video (the ai container's Whisper)
  ai_backfill     nightly: catch up on everything above, a batch at a time
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, select

from ..db import sessionmaker
from ..models import Asset, AssetText, DocChunk, Face, Person, PhotoVector, utcnow
from . import ai, photo_quality, storage

log = logging.getLogger(__name__)

SAME_PERSON = 0.42   # cosine between SFace vectors; 0.363 is the model's own threshold, a bit stricter here
CHUNK = 900          # characters per passage
OVERLAP = 150


def subtitle_path(media_id: str) -> Path:
    from ..config import get_settings

    return get_settings().cache_dir / "ai-subtitles" / f"{media_id}.vtt"


# ------------------------------------------------------------ photos

async def photo_quality_job(_ctx: Any, asset_id: str) -> None:
    async with sessionmaker()() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None or asset.kind != "photo":
            return
        src = storage.abs_storage_path(asset.storage_path)
        asset.phash, asset.sharpness = await asyncio.to_thread(photo_quality.measure, src)
        await session.commit()


async def assign_people(session, owner_id: str, faces: list[Face]) -> None:
    """Puts each new face with the person it looks most like, or starts a new person when it
    looks like an earlier face nobody was found for. Lone faces wait for a second photo."""
    rows = (await session.execute(select(Face.id, Face.person_id, Face.vector).where(
        Face.owner_id == owner_id))).all()
    by_person: dict[str, list[np.ndarray]] = {}
    loose: list[tuple[str, np.ndarray]] = []
    new_ids = {f.id for f in faces}
    for fid, pid, vec in rows:
        if fid in new_ids:
            continue
        if pid:
            by_person.setdefault(pid, []).append(ai.unpack(vec))
        else:
            loose.append((fid, ai.unpack(vec)))
    centroids = {pid: ai.unit(np.mean(v, axis=0)) for pid, v in by_person.items()}
    for face in faces:
        v = ai.unpack(face.vector)
        best_pid, best = None, SAME_PERSON
        for pid, c in centroids.items():
            s = float(c @ v)
            if s > best:
                best_pid, best = pid, s
        if best_pid:
            face.person_id = best_pid
            continue
        match = max(((fid, float(lv @ v)) for fid, lv in loose), key=lambda x: x[1], default=(None, 0.0))
        if match[0] and match[1] > SAME_PERSON:
            person = Person(owner_id=owner_id)
            session.add(person)
            await session.flush()
            face.person_id = person.id
            other = await session.get(Face, match[0])
            if other is not None:
                other.person_id = person.id
            loose = [x for x in loose if x[0] != match[0]]
            centroids[person.id] = ai.unit(v + ai.unpack(other.vector)) if other else v
        else:
            loose.append((face.id, v))


async def ai_photo(_ctx: Any, asset_id: str) -> str:
    async with sessionmaker()() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None or asset.kind != "photo" or asset.deleted_at:
            return "skip"
        path = str(storage.abs_storage_path(asset.storage_path))
        try:
            vector = (await ai.clip_images([path]))[0]
            found = (await ai.faces([path]))[0]
        except ai.AiOff:
            return "ai off"
        if vector is not None:
            row = await session.get(PhotoVector, asset.id)
            if row is None:
                session.add(PhotoVector(asset_id=asset.id, owner_id=asset.owner_id, vector=ai.pack(vector)))
            else:
                row.vector = ai.pack(vector)
        await session.execute(delete(Face).where(Face.asset_id == asset.id, Face.confirmed.is_(False)))
        # faces someone already corrected stay as they are; don't add them again
        kept = [ai.unpack(v) for v in (await session.scalars(select(Face.vector).where(
            Face.asset_id == asset.id, Face.confirmed.is_(True)))).all()]
        new = [Face(asset_id=asset.id, owner_id=asset.owner_id, box=json.dumps(f["box"]), score=f["score"],
                    vector=ai.pack(f["vector"])) for f in (found or [])
               if not any(float(k @ ai.unit(f["vector"])) > 0.9 for k in kept)]
        session.add_all(new)
        await session.flush()
        await assign_people(session, asset.owner_id, new)
        asset.ai_indexed_at = utcnow()
        await session.commit()
        return f"{len(new)} faces"


# ------------------------------------------------------------ documents

def chunks(text: str) -> list[str]:
    """Passages of about CHUNK characters, cut at sentence or line ends, overlapping a little."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK)
        if end < len(text):
            cut = max(text.rfind(m, start + CHUNK // 2, end) for m in ("\n", ". ", "। ", "? ", "! "))
            if cut > start:
                end = cut + 1
        piece = text[start:end].strip()
        if len(piece) > 20:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return out


async def doc_chunks(_ctx: Any, asset_id: str) -> str:
    async with sessionmaker()() as session:
        asset = await session.get(Asset, asset_id)
        row = await session.get(AssetText, asset_id)
        if asset is None or asset.deleted_at or row is None or not (row.text or "").strip():
            return "no text"
        have = await session.scalar(select(DocChunk.sha256).where(DocChunk.asset_id == asset_id).limit(1))
        if have == asset.sha256:
            return "done already"
        pieces = chunks(row.text)[:400]
        try:
            vectors = []
            for i in range(0, len(pieces), 16):
                vectors += await ai.embed_texts([f"{asset.filename}\n{p}" for p in pieces[i:i + 16]])
        except ai.AiOff:
            return "ai off"
        await session.execute(delete(DocChunk).where(DocChunk.asset_id == asset_id))
        session.add_all(DocChunk(asset_id=asset_id, owner_id=asset.owner_id, n=i, text=p, vector=ai.pack(v),
                                 sha256=asset.sha256) for i, (p, v) in enumerate(zip(pieces, vectors)))
        await session.commit()
        return f"{len(pieces)} passages"


# ------------------------------------------------------------ subtitles

async def transcribe(_ctx: Any, media_id: str, language: str | None = None) -> str:
    from ..models import Library, MediaItem
    from .events import notify_admins

    async with sessionmaker()() as session:
        item = await session.get(MediaItem, media_id)
        if item is None:
            return "gone"
        lib = await session.get(Library, item.library_id)
        src = Path(lib.path) / item.rel_path
        item.ai_subtitles = "working"
        await session.commit()
        try:
            result = await ai.transcribe(str(src), language)
            if not result.get("cues"):
                raise RuntimeError("no speech was found")
            dest = subtitle_path(media_id)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(result["vtt"], "utf-8")
            item.ai_subtitles = f"done:{result.get('language') or 'und'}"
            item.tracks_json = None  # list the new track next time
            await notify_admins(session, "media", f"AI subtitles are ready for {item.title}", link=f"/play/{item.id}")
        except (ai.AiOff, RuntimeError, OSError) as exc:
            item.ai_subtitles = f"failed:{str(exc)[:250]}"
        await session.commit()
        return item.ai_subtitles


# ------------------------------------------------------------ nightly

async def ai_backfill(_ctx: Any, limit: int = 2000) -> dict:
    done = {"quality": 0, "photos": 0, "documents": 0}
    async with sessionmaker()() as session:
        quality = (await session.scalars(select(Asset.id).where(
            Asset.kind == "photo", Asset.deleted_at.is_(None), Asset.phash.is_(None), Asset.sharpness.is_(None))
            .limit(limit))).all()
    for aid in quality:
        await photo_quality_job(None, aid)
        done["quality"] += 1
    if await ai.ai_info():
        async with sessionmaker()() as session:
            photos = (await session.scalars(select(Asset.id).where(
                Asset.kind == "photo", Asset.deleted_at.is_(None), Asset.ai_indexed_at.is_(None))
                .order_by(Asset.created_at.desc()).limit(limit))).all()
        for aid in photos:
            if await ai_photo(None, aid) == "ai off":
                break
            done["photos"] += 1
    if await ai.ollama_info():
        async with sessionmaker()() as session:
            have = select(DocChunk.asset_id).where(DocChunk.sha256 == Asset.sha256)
            docs = (await session.scalars(select(AssetText.asset_id).join(Asset, Asset.id == AssetText.asset_id).where(
                Asset.deleted_at.is_(None), AssetText.text != "", ~AssetText.asset_id.in_(have))
                .limit(limit // 4))).all()
        for aid in docs:
            if await doc_chunks(None, aid) == "ai off":
                break
            done["documents"] += 1
    return done
