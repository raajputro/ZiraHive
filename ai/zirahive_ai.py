"""ZiraHive's local AI helper: runs only with `docker compose --profile ai`.

Free, open models that run on the CPU (or an NVIDIA GPU) of your own PC. Nothing is sent anywhere:
models are downloaded once into the `ai-models` volume, then everything stays local.

  CLIP ViT-B/32 (fastembed, ONNX)      pictures and words in one space, for "beach at sunset"
  YuNet + SFace (OpenCV)                finds faces and tells people apart
  Whisper (faster-whisper)              speech to subtitles, in about 100 languages

The main ZiraHive server calls this over HTTP with file paths: both containers see the same
folders (read-only here).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("zirahive.ai")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MODELS = Path(os.environ.get("ZIRAHIVE_AI_MODELS", "/models"))
CLIP_VISION = "Qdrant/clip-ViT-B-32-vision"
CLIP_TEXT = "Qdrant/clip-ViT-B-32-text"
WHISPER = os.environ.get("ZIRAHIVE_WHISPER_MODEL", "small")
FACE_FILES = {
    "yunet.onnx": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
                  "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
                  "face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
MAX_SIDE = 1600  # pictures are scaled down to this before looking at them

app = FastAPI(title="ZiraHive AI", docs_url=None, redoc_url=None)
_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()
_models: dict[str, object] = {}
_loading: dict[str, float] = {}
# Indexing photos uses all but one core, so a search typed meanwhile still gets an answer quickly.
_BACKGROUND_THREADS = max(1, (os.cpu_count() or 2) - 1)


def _get(name: str, make):
    """Loads a model the first time it's needed (downloading it once), then keeps it. Each model
    has its own lock, so a search never waits for, say, the subtitle model to finish loading."""
    if name in _models:
        return _models[name]
    with _locks_lock:
        lock = _locks.setdefault(name, threading.Lock())
    with lock:
        if name not in _models:
            _loading[name] = time.time()
            try:
                _models[name] = make()
            finally:
                _loading.pop(name, None)
        return _models[name]


def _clip_vision():
    from fastembed import ImageEmbedding

    return ImageEmbedding(CLIP_VISION, cache_dir=str(MODELS / "fastembed"), threads=_BACKGROUND_THREADS)


def _clip_text():
    from fastembed import TextEmbedding

    return TextEmbedding(CLIP_TEXT, cache_dir=str(MODELS / "fastembed"))


def _face_file(name: str) -> str:
    path = MODELS / "faces" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        log.info("downloading %s", name)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(FACE_FILES[name], tmp)  # noqa: S310 (fixed https address)
        tmp.replace(path)
    return str(path)


def _faces():
    import cv2

    detector = cv2.FaceDetectorYN.create(_face_file("yunet.onnx"), "", (320, 320), 0.8, 0.3, 5000)
    recognizer = cv2.FaceRecognizerSF.create(_face_file("sface.onnx"), "")
    return detector, recognizer


def _whisper():
    from faster_whisper import WhisperModel

    device = "cuda" if os.environ.get("ZIRAHIVE_AI_GPU") == "1" else "cpu"
    return WhisperModel(WHISPER, device=device, compute_type="int8" if device == "cpu" else "float16",
                        download_root=str(MODELS / "whisper"), cpu_threads=min(4, _BACKGROUND_THREADS))


def _unit(v) -> list[float]:
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return (v / n if n else v).astype(np.float64).round(6).tolist()


def _picture(path: str):
    """The picture as RGB, scaled down; None when it can't be read."""
    from PIL import Image, ImageOps

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        im = ImageOps.exif_transpose(Image.open(path))
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        return im.convert("RGB")
    except Exception as exc:  # broken or unsupported file: skip it
        log.warning("can't read %s: %s", path, exc)
        return None


# ------------------------------------------------------------------ API

class Paths(BaseModel):
    paths: list[str] = Field(max_length=64)


class Texts(BaseModel):
    texts: list[str] = Field(max_length=64)


class TranscribeIn(BaseModel):
    path: str
    language: str | None = None  # None: detect


@app.on_event("startup")
def _warm_up() -> None:
    """Load the search model straight away (small, a second or two), so the first photo search
    after a restart doesn't wait for it."""
    def load():
        try:
            _get("clip_text", _clip_text)
        except Exception as exc:  # no internet on first run, say: it loads on first use instead
            log.warning("couldn't load the search model yet: %s", exc)
    threading.Thread(target=load, daemon=True).start()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "loaded": sorted(_models), "loading": sorted(_loading),
            "models": {"clip": CLIP_VISION, "faces": "YuNet + SFace", "whisper": WHISPER}}


@app.post("/clip/images")
def clip_images(body: Paths) -> dict:
    model = _get("clip_vision", _clip_vision)
    pictures = [_picture(p) for p in body.paths]
    ok = [p for p in pictures if p is not None]
    vectors = iter(list(model.embed(ok, batch_size=16)) if ok else [])
    return {"vectors": [_unit(next(vectors)) if p is not None else None for p in pictures]}


@app.post("/clip/text")
def clip_text(body: Texts) -> dict:
    model = _get("clip_text", _clip_text)
    return {"vectors": [_unit(v) for v in model.embed(body.texts)]}


def find_faces(im, detector, recognizer) -> list[dict]:
    import cv2

    img = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, found = detector.detect(img)
    out = []
    for f in found if found is not None else []:
        x, y, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])
        if fw < 40 or fh < 40:  # too small to recognise anyone reliably
            continue
        aligned = recognizer.alignCrop(img, f)
        vec = recognizer.feature(aligned)[0]
        out.append({"box": [round(x / w, 4), round(y / h, 4), round(fw / w, 4), round(fh / h, 4)],
                    "score": round(score, 3), "vector": _unit(vec)})
    return out


@app.post("/faces")
def faces(body: Paths) -> dict:
    detector, recognizer = _get("faces", _faces)
    result = []
    for p in body.paths:
        im = _picture(p)
        result.append(None if im is None else find_faces(im, detector, recognizer))
    return {"faces": result}


def _stamp(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


@app.post("/transcribe")
def transcribe(body: TranscribeIn) -> dict:
    if not Path(body.path).is_file():
        raise HTTPException(404, "File not found")
    model = _get("whisper", _whisper)
    segments, info = model.transcribe(body.path, language=body.language, vad_filter=True, beam_size=5)
    lines = ["WEBVTT", ""]
    count = 0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        count += 1
        lines += [f"{_stamp(seg.start)} --> {_stamp(seg.end)}", text, ""]
    return {"language": info.language, "probability": round(info.language_probability, 3),
            "cues": count, "vtt": "\n".join(lines)}
