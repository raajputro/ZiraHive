"""Talking to the optional local AI: the `ai` container (CLIP, faces, Whisper) and Ollama
(a language model and a text-embedding model). Both are off unless their address is set and
they answer; every feature that uses them says so instead of failing."""
from __future__ import annotations

import logging
import time

import httpx
import numpy as np

from ..config import get_settings

log = logging.getLogger(__name__)


class AiOff(RuntimeError):
    """The AI part isn't running (or can't be reached)."""


def client(base: str, timeout: float) -> httpx.AsyncClient:
    """Replaced in tests."""
    return httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(timeout, connect=5))


_status: dict[str, tuple[float, dict | None]] = {}


async def _probe(kind: str, base: str, path: str) -> dict | None:
    hit = _status.get(kind)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    info = None
    if base:
        try:
            async with client(base, 5) as c:
                r = await c.get(path)
            if r.status_code == 200:
                info = r.json()
        except (httpx.HTTPError, ValueError):
            info = None
    _status[kind] = (time.time(), info)
    return info


def forget_status() -> None:
    _status.clear()


async def ai_info() -> dict | None:
    return await _probe("ai", get_settings().ai_url, "/health")


async def ollama_info() -> dict | None:
    return await _probe("ollama", get_settings().ollama_url, "/api/tags")


async def _post(kind: str, path: str, body: dict, timeout: float) -> dict:
    s = get_settings()
    base = s.ai_url if kind == "ai" else s.ollama_url
    if not base:
        raise AiOff(f"{kind} isn't set up")
    try:
        async with client(base, timeout) as c:
            r = await c.post(path, json=body)
    except httpx.HTTPError as exc:
        _status.pop(kind, None)
        raise AiOff(f"{kind} can't be reached: {type(exc).__name__}") from None
    if r.status_code >= 400:
        raise RuntimeError(f"{kind} answered {r.status_code}: {r.text[:200]}")
    return r.json()


# ------------------------------------------------------------ the ai container

async def clip_images(paths: list[str]) -> list[list[float] | None]:
    return (await _post("ai", "/clip/images", {"paths": paths}, 600))["vectors"]


async def clip_text(text: str) -> list[float]:
    return (await _post("ai", "/clip/text", {"texts": [text]}, 120))["vectors"][0]


async def faces(paths: list[str]) -> list[list[dict] | None]:
    return (await _post("ai", "/faces", {"paths": paths}, 600))["faces"]


async def transcribe(path: str, language: str | None) -> dict:
    return await _post("ai", "/transcribe", {"path": path, "language": language}, 6 * 3600)


# ------------------------------------------------------------ Ollama

async def _ensure_model(model: str) -> None:
    """Pulls the model the first time (a few GB for the language model)."""
    info = await ollama_info()
    names = {m.get("name", "") for m in (info or {}).get("models", [])}
    if model in names or f"{model}:latest" in names:
        return
    log.info("pulling %s into Ollama (first use)", model)
    await _post("ollama", "/api/pull", {"model": model, "stream": False}, 3 * 3600)
    _status.pop("ollama", None)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_settings().embed_model
    await _ensure_model(model)
    r = await _post("ollama", "/api/embed", {"model": model, "input": texts}, 600)
    return [unit(v).tolist() for v in r["embeddings"]]


async def chat(system: str, user: str, max_words: int | None = None) -> str:
    """`max_words`: for short answers (a translation), stop early instead of letting the model ramble."""
    model = get_settings().llm_model
    await _ensure_model(model)
    options: dict = {"temperature": 0.2}
    if max_words:
        options["num_predict"] = max_words * 3  # tokens; Bangla and English words are a few each
    r = await _post("ollama", "/api/chat", {
        "model": model, "stream": False, "options": options,
        # keep the model in memory between uses (Ollama unloads it after 5 idle minutes, and
        # loading it again takes longer than the answer itself)
        "keep_alive": "30m",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, 600)
    return r["message"]["content"].strip()


# ------------------------------------------------------------ vectors

def unit(v) -> np.ndarray:
    a = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(a))
    return a / n if n else a


def pack(v) -> bytes:
    return unit(v).astype(np.float32).tobytes()


def unpack(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def best(query, rows: list[tuple[str, bytes]], limit: int, floor: float) -> list[tuple[str, float]]:
    """The ids whose vectors are most like the query (cosine), best first."""
    if not rows:
        return []
    q = unit(query)
    m = np.vstack([unpack(v) for _, v in rows])
    if m.shape[1] != q.shape[0]:
        return []
    scores = m @ q
    order = np.argsort(-scores)[:limit]
    return [(rows[i][0], float(scores[i])) for i in order if scores[i] >= floor]
