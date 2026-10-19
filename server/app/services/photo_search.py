"""Keeps photo search fast: everything a search needs that doesn't change between searches is
remembered in memory.

- Each person's photo vectors, as one matrix. Rebuilt only when their photos change (checked with
  one cheap count query); reading tens of thousands of vectors from the database every search was
  the slow part on big libraries.
- The vector for each search phrase, and the English for each Bangla phrase (the translation goes
  through the language model, which takes seconds), for the most recent few hundred phrases.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PhotoVector
from . import ai


class _Recent(OrderedDict):
    """A small least-recently-used cache."""

    def __init__(self, size: int):
        super().__init__()
        self.size = size

    def get(self, key, default=None):
        if key in self:
            self.move_to_end(key)
            return self[key]
        return default

    def put(self, key, value) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.size:
            self.popitem(last=False)


translations = _Recent(512)
phrase_vectors = _Recent(512)
_matrices: dict[str, tuple[tuple, list[str], np.ndarray]] = {}
_building: dict[str, asyncio.Lock] = {}


async def vectors_for(session: AsyncSession, owner_id: str) -> tuple[list[str], np.ndarray | None]:
    """(asset ids, matrix with one unit vector per row) for one person's photos."""
    stamp = tuple((await session.execute(
        select(func.count(), func.max(PhotoVector.asset_id), func.min(PhotoVector.asset_id))
        .where(PhotoVector.owner_id == owner_id))).one())
    hit = _matrices.get(owner_id)
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    async with _building.setdefault(owner_id, asyncio.Lock()):
        hit = _matrices.get(owner_id)
        if hit and hit[0] == stamp:
            return hit[1], hit[2]
        rows = (await session.execute(select(PhotoVector.asset_id, PhotoVector.vector)
                                      .where(PhotoVector.owner_id == owner_id))).all()

        def build():
            if not rows:
                return [], None
            width = np.bincount([len(v) for _, v in rows]).argmax()  # skip any from an older model
            keep = [(i, v) for i, v in rows if len(v) == width]
            return [i for i, _ in keep], np.vstack([ai.unpack(v) for _, v in keep])

        ids, matrix = await asyncio.to_thread(build)
        _matrices[owner_id] = (stamp, ids, matrix)
        return ids, matrix


def rank(query, ids: list[str], matrix: np.ndarray | None, limit: int, floor: float) -> list[tuple[str, float]]:
    if matrix is None or not ids:
        return []
    q = ai.unit(query)
    if matrix.shape[1] != q.shape[0]:
        return []
    scores = matrix @ q
    top = np.argpartition(-scores, min(limit, len(scores) - 1))[:limit] if len(scores) > limit else np.arange(len(scores))
    top = top[np.argsort(-scores[top])]
    return [(ids[i], float(scores[i])) for i in top if scores[i] >= floor]


def forget() -> None:
    translations.clear(); phrase_vectors.clear(); _matrices.clear()
