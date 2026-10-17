"""Photo clean-up without AI: near-duplicates and blurry shots.

- A 64-bit "difference hash" (dHash) fingerprints what a picture looks like. Copies, resized or
  re-saved versions and most burst shots differ in only a few bits.
- Sharpness is the variance of the Laplacian (how much edges stand out) on a 512-pixel version.
  Low means blurry or shaken.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

SAME = 5          # at most this many different bits: the same picture
BLURRY = 60.0     # sharpness below this: likely blurry (tuned on phone photos at 512 px)
_BANDS = 8        # 8 bands of 8 bits: two hashes within 7 bits share at least one band


def _gray(path: Path, side: int) -> np.ndarray:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.draft("L", (side, side))
        g = im.convert("L")
        g.thumbnail((side, side))
        return np.asarray(g, dtype=np.float32)


def dhash(path: Path) -> str:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.draft("L", (64, 64))
        small = np.asarray(im.convert("L").resize((9, 8), Image.LANCZOS), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return f"{value:016x}"


def sharpness(path: Path) -> float:
    g = _gray(path, 512)
    lap = (g[1:-1, :-2] + g[1:-1, 2:] + g[:-2, 1:-1] + g[2:, 1:-1] - 4 * g[1:-1, 1:-1])
    return round(float(lap.var()), 2)


def measure(path: Path) -> tuple[str | None, float | None]:
    try:
        return dhash(path), sharpness(path)
    except Exception:  # unreadable picture
        return None, None


def distance(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def duplicate_groups(items: list[tuple[str, str]], same: int = SAME) -> list[list[str]]:
    """Groups of ids whose pictures look the same, from (id, phash) pairs. Uses bands so it
    doesn't compare every photo with every other one."""
    buckets: dict[tuple[int, str], list[int]] = defaultdict(list)
    for i, (_, h) in enumerate(items):
        if h == "0" * 16:  # a plain, one-colour picture: its fingerprint says nothing
            continue
        for b in range(_BANDS):
            buckets[(b, h[b * 2:b * 2 + 2])].append(i)
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seen: set[tuple[int, int]] = set()
    for members in buckets.values():
        if len(members) < 2 or len(members) > 500:  # a huge bucket is a plain colour, not duplicates
            continue
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                a, b = members[x], members[y]
                if (a, b) in seen:
                    continue
                seen.add((a, b))
                if distance(items[a][1], items[b][1]) <= same:
                    parent[find(a)] = find(b)
    groups: dict[int, list[str]] = defaultdict(list)
    for i, (aid, _) in enumerate(items):
        groups[find(i)].append(aid)
    return [g for g in groups.values() if len(g) > 1]
