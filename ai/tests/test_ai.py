"""The AI helper with the real face models (downloaded once). CLIP and Whisper download from
Hugging Face; those tests skip when it can't be reached."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import tempfile

os.environ.setdefault("ZIRAHIVE_AI_MODELS", str(Path(tempfile.gettempdir()) / "zirahive-aimodels"))

import zirahive_ai  # noqa: E402

client = TestClient(zirahive_ai.app)


def test_health():
    r = client.get("/health").json()
    assert r["ok"] and "clip" in r["models"]


def test_faces_found_and_compared(tmp_path):
    r = client.post("/faces", json={"paths": [str(HERE / "astronaut.jpg"), str(HERE / "cat.jpg"),
                                              str(HERE / "missing.jpg")]}).json()["faces"]
    astronaut, cat, missing = r
    assert len(astronaut) == 1 and astronaut[0]["score"] > 0.8
    x, y, w, h = astronaut[0]["box"]
    assert 0.3 < x < 0.6 and 0 < y < 0.3 and 0.1 < w < 0.4  # her face, upper middle
    assert len(astronaut[0]["vector"]) == 128 and cat == [] and missing is None

    # the same face, smaller and mirrored, is still the same person
    from PIL import Image, ImageOps
    im = ImageOps.mirror(Image.open(HERE / "astronaut.jpg")).resize((380, 380))
    other = tmp_path / "astro-small.jpg"
    im.save(other)
    again = client.post("/faces", json={"paths": [str(other)]}).json()["faces"][0][0]
    import numpy as np
    same = float(np.dot(astronaut[0]["vector"], again["vector"]))
    assert same > 0.363, same  # SFace's "same person" threshold for cosine similarity


class FakeEmbed:
    def embed(self, items, batch_size=16):
        for it in items:
            yield [3.0, 4.0] if not isinstance(it, str) else [len(it), 0.0]


def test_clip_vectors_are_unit_length(monkeypatch):
    monkeypatch.setitem(zirahive_ai._models, "clip_vision", FakeEmbed())
    monkeypatch.setitem(zirahive_ai._models, "clip_text", FakeEmbed())
    r = client.post("/clip/images", json={"paths": [str(HERE / "cat.jpg"), "/nope.jpg"]}).json()["vectors"]
    assert r == [[0.6, 0.8], None]
    assert client.post("/clip/text", json={"texts": ["a cat"]}).json()["vectors"] == [[1.0, 0.0]]


def test_transcribe_makes_webvtt(monkeypatch, tmp_path):
    class Seg:
        def __init__(self, start, end, text): self.start, self.end, self.text = start, end, text

    class Info:
        language, language_probability = "bn", 0.97

    class FakeWhisper:
        def transcribe(self, path, **kw):
            return iter([Seg(1.5, 3.25, " আমি বাংলায় কথা বলি "), Seg(3.5, 4, "  "), Seg(3725.1, 3727, "Bye")]), Info()

    monkeypatch.setitem(zirahive_ai._models, "whisper", FakeWhisper())
    video = tmp_path / "film.mkv"
    video.write_bytes(b"x")
    r = client.post("/transcribe", json={"path": str(video)}).json()
    assert r["language"] == "bn" and r["cues"] == 2
    assert r["vtt"].startswith("WEBVTT\n\n00:00:01.500 --> 00:00:03.250\nআমি বাংলায় কথা বলি\n")
    assert "01:02:05.100 --> 01:02:07.000\nBye" in r["vtt"]
    assert client.post("/transcribe", json={"path": "/nope.mkv"}).status_code == 404
