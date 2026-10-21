"""Duplicate documents: exact copies and edited versions of the same document.

- Exact copies have the same SHA-256.
- Edited versions ("report v1" / "report v2", a contract with one clause changed) are found from
  their words: each document becomes the set of its 3-word phrases ("shingles"), and two documents
  whose sets overlap by at least SIMILAR (Jaccard) count as the same document. MinHash signatures
  with banding find the likely pairs without comparing every document with every other one; each
  pair is then checked exactly.

Words are taken with Bangla letters included (\\w alone would split Bangla words at vowel signs).
The browser does the same for the vault (web/src/vault/compare.ts); keep the two in step.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

SIMILAR = 0.80      # share of 3-word phrases two documents must have in common
MIN_WORDS = 30      # shorter texts say too little to call two documents the same
_PERMS = 32         # MinHash functions
_ROWS = 4           # rows per band: 8 bands of 4, which catches pairs at 0.8 about 98% of the time
_WORD = re.compile(r"[\wঀ-৿]+")
_SALTS = np.random.default_rng(20261019).integers(1, 2**63 - 1, size=_PERMS, dtype=np.int64).astype(np.uint64)


def shingles(text: str) -> frozenset[int]:
    """The document's 3-word phrases, as 64-bit numbers. Empty when the text is too short."""
    words = _WORD.findall(text.lower())
    if len(words) < MIN_WORDS:
        return frozenset()
    return frozenset(int.from_bytes(hashlib.blake2b(" ".join(words[i:i + 3]).encode(), digest_size=8).digest(), "little")
                     for i in range(len(words) - 2))


def _signature(sh: frozenset[int]) -> np.ndarray:
    values = np.fromiter(sh, dtype=np.uint64, count=len(sh))
    mixed = values[None, :] ^ _SALTS[:, None]
    mixed = (mixed * np.uint64(0x9E3779B97F4A7C15)) ^ (mixed >> np.uint64(29))  # scramble each salted copy
    return mixed.min(axis=1)


def jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Group:
    ids: list[str]
    same: bool          # every file is an exact copy of the others
    similarity: float   # lowest overlap between two files joined in the group (1.0 for exact copies)


def duplicate_groups(docs: list[tuple[str, str, str | None]], similar: float = SIMILAR) -> list[Group]:
    """Groups of document ids that are copies or edited versions of each other, from
    (id, sha256, text or None) tuples."""
    parent = {d[0]: d[0] for d in docs}
    lowest: dict[tuple[str, str], float] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a: str, b: str, sim: float) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
        lowest[(a, b)] = sim

    by_sha: dict[str, list[str]] = defaultdict(list)
    for doc_id, sha, _ in docs:
        by_sha[sha].append(doc_id)
    for ids in by_sha.values():
        for other in ids[1:]:
            join(ids[0], other, 1.0)

    # one text per distinct file content is enough
    sets: dict[str, frozenset[int]] = {}
    first_of_sha: dict[str, str] = {}
    for doc_id, sha, text in docs:
        if sha in first_of_sha or not text:
            continue
        sh = shingles(text)
        if sh:
            first_of_sha[sha] = doc_id
            sets[doc_id] = sh
    buckets: dict[tuple[int, bytes], list[str]] = defaultdict(list)
    for doc_id, sh in sets.items():
        sig = _signature(sh)
        for band in range(_PERMS // _ROWS):
            buckets[(band, sig[band * _ROWS:(band + 1) * _ROWS].tobytes())].append(doc_id)
    checked: set[tuple[str, str]] = set()
    for ids in buckets.values():
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                pair = (a, b) if a < b else (b, a)
                if pair in checked:
                    continue
                checked.add(pair)
                sim = jaccard(sets[a], sets[b])
                if sim >= similar:
                    join(a, b, sim)

    members: dict[str, list[str]] = defaultdict(list)
    for doc_id, _, _ in docs:
        members[find(doc_id)].append(doc_id)
    sha_of = {d[0]: d[1] for d in docs}
    out = []
    for ids in members.values():
        if len(ids) < 2:
            continue
        inside = set(ids)
        sims = [s for (a, b), s in lowest.items() if a in inside and b in inside]
        out.append(Group(ids=ids, same=len({sha_of[i] for i in ids}) == 1, similarity=round(min(sims, default=1.0), 3)))
    return out
