"""Batch 8: photo clean-up, and the local AI features with stand-ins for the AI container and Ollama.
(The AI container itself is tested with the real face models in ai/tests.)"""
from __future__ import annotations

import io
import re

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from PIL import Image, ImageDraw, ImageFilter

from app.services import ai, jobs
from conftest import make_video
from test_batch6 import upload

# ------------------------------------------------------------ stand-ins

fake_ai = FastAPI()
COLOURS = {"red": [1, 0, 0], "green": [0, 1, 0], "blue": [0, 0, 1]}


def _colour_vector(path: str) -> list[float]:
    im = Image.open(path).convert("RGB").resize((8, 8))
    v = np.asarray(im, dtype=np.float32).reshape(-1, 3).mean(axis=0)
    return (v / np.linalg.norm(v)).tolist()


@fake_ai.get("/health")
def _health():
    return {"ok": True, "models": {"clip": "fake"}}


@fake_ai.post("/clip/images")
def _clip_images(body: dict):
    return {"vectors": [_colour_vector(p) for p in body["paths"]]}


@fake_ai.post("/clip/text")
def _clip_text(body: dict):
    out = []
    for t in body["texts"]:
        v = next((v for k, v in COLOURS.items() if k in t), [0.3, 0.3, 0.3])
        out.append(v)
    return {"vectors": out}


def _person_of(path: str) -> list[float] | None:
    """Pictures with a white square in the corner 'contain' a face; its shade says whose."""
    px = Image.open(path).convert("L").resize((64, 64)).getpixel((2, 2))
    if px < 100:
        return None
    rng = np.random.default_rng(int(px) // 40)  # shades 200-239 -> person A, 240-255 -> person B
    v = rng.normal(size=128)
    return (v / np.linalg.norm(v)).tolist()


@fake_ai.post("/faces")
def _faces(body: dict):
    out = []
    for p in body["paths"]:
        v = _person_of(p)
        out.append([] if v is None else [{"box": [0.0, 0.0, 0.3, 0.3], "score": 0.95, "vector": v}])
    return {"faces": out}


@fake_ai.post("/transcribe")
def _transcribe(body: dict):
    return {"language": "bn", "cues": 1, "vtt": "WEBVTT\n\n00:00:00.500 --> 00:00:02.000\nআমি বাংলায় কথা বলি\n"}


fake_ollama = FastAPI()
WORDS = ["passport", "expires", "electricity", "bill", "rent", "taka", "পাসপোর্ট"]


@fake_ollama.get("/api/tags")
def _tags():
    return {"models": [{"name": "bge-m3:latest"}, {"name": "qwen2.5:3b"}]}


@fake_ollama.post("/api/embed")
def _embed(body: dict):
    out = []
    for t in body["input"]:
        v = np.array([t.lower().count(w) for w in WORDS] + [0.1], dtype=np.float32)
        if "পাসপোর্ট" in t:
            v[0] += 1
        out.append(v.tolist())
    return {"embeddings": out}


ASKED: list[str] = []


@fake_ollama.post("/api/chat")
def _chat(body: dict):
    question = body["messages"][1]["content"]
    ASKED.append(question)
    if "Translate" in body["messages"][0]["content"]:
        return {"message": {"content": "red"}}
    m = re.search(r"\[(\d)\] [^\n]*passport", question, re.I)
    return {"message": {"content": f"Your passport expires on 3 March 2031 [{m.group(1) if m else 1}]."}}


@pytest.fixture
def local_ai(monkeypatch):
    monkeypatch.setenv("ZIRAHIVE_AI_URL", "http://ai")
    monkeypatch.setenv("ZIRAHIVE_OLLAMA_URL", "http://ollama")
    from app.config import get_settings
    get_settings.cache_clear()
    apps = {"http://ai": fake_ai, "http://ollama": fake_ollama}
    monkeypatch.setattr(ai, "client", lambda base, timeout: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=apps[base]), base_url=base))
    ai.forget_status()
    yield
    ai.forget_status()
    get_settings.cache_clear()


def jpeg(colour, size=(640, 480), face_shade: int | None = None, blur=0, quality=90, detail=True) -> bytes:
    im = Image.new("RGB", size, colour)
    d = ImageDraw.Draw(im)
    if detail:  # a scene of its own (from the colour), so different photos look different
        rng = np.random.default_rng(sum(colour))
        for _ in range(14):
            x0, y0 = rng.integers(0, size[0]), rng.integers(0, size[1])
            x1, y1 = x0 + rng.integers(20, size[0] // 2), y0 + rng.integers(20, size[1] // 2)
            d.rectangle([x0, y0, x1, y1], fill=tuple(int(c) for c in rng.integers(0, 255, 3)))
        for i in range(0, size[0], 40):
            d.line([(i, 0), (size[0] - i, size[1])], fill=(20, 20, 20), width=3)
    if face_shade is not None:
        d.rectangle([0, 0, size[0] // 8, size[1] // 8], fill=(face_shade,) * 3)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality)
    return out.getvalue()


def shrink(data: bytes, size, quality) -> bytes:
    im = Image.open(io.BytesIO(data))
    im.thumbnail(size)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality)
    return out.getvalue()


async def photos(client, items: dict[str, bytes]) -> dict[str, dict]:
    out = {name: await upload(client, name, data, folder="/Camera") for name, data in items.items()}
    await jobs.drain_local()
    return out


# ------------------------------------------------------------ clean-up (no AI)

async def test_duplicates_and_blurry_photos(client, admin):
    base = jpeg((180, 120, 60))
    got = await photos(client, {
        "beach.jpg": base,
        "beach copy small.jpg": shrink(base, (320, 240), 70),  # sent on WhatsApp and saved back
        "garden.jpg": jpeg((40, 160, 40)),
        "shaky.jpg": jpeg((60, 80, 200), blur=6),
    })
    r = (await client.get("/api/photos/cleanup")).json()
    assert r["waiting"] == 0 and r["measured"] == 4
    assert len(r["duplicates"]) == 1
    group = r["duplicates"][0]
    assert {p["filename"] for p in group["photos"]} == {"beach.jpg", "beach copy small.jpg"}
    assert group["keep"] == got["beach.jpg"]["id"]  # the bigger one
    assert [p["filename"] for p in r["blurry"]] == ["shaky.jpg"]


def test_fingerprints():
    from app.services.photo_quality import distance, duplicate_groups
    assert distance("ffffffffffffffff", "fffffffffffffff0") == 4
    groups = duplicate_groups([("a", "0123456789abcdef"), ("b", "0123456789abcdee"), ("c", "fedcba9876543210")])
    assert groups == [["a", "b"]]


# ------------------------------------------------------------ AI features

async def test_ai_off_says_so(client, admin):
    r = await client.get("/api/photos/search", params={"q": "beach"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ai_off"
    assert (await client.post("/api/ask", json={"question": "when does my passport expire?"})).status_code == 409
    st = (await client.get("/api/ai/status")).json()
    assert st["ai"] is False and st["ollama"] is False


async def test_search_photos_by_description(client, admin, local_ai):
    await photos(client, {"red car.jpg": jpeg((220, 30, 30)), "lawn.jpg": jpeg((30, 200, 40)),
                          "sky.jpg": jpeg((40, 60, 230))})
    r = (await client.get("/api/photos/search", params={"q": "red"})).json()
    assert [h["asset"]["filename"] for h in r["hits"]] == ["red car.jpg"]
    # a Bangla query is put into English first (the picture model knows English)
    r = (await client.get("/api/photos/search", params={"q": "লাল গাড়ি"})).json()
    assert r["searched_for"] == "red" and r["hits"][0]["asset"]["filename"] == "red car.jpg"
    st = (await client.get("/api/ai/status")).json()
    assert st["ai"] and st["photos_indexed"] == 3


async def test_people_from_faces(client, admin, local_ai):
    got = await photos(client, {
        "rina 1.jpg": jpeg((200, 100, 80), face_shade=210), "rina 2.jpg": jpeg((90, 100, 200), face_shade=215),
        "rina 3.jpg": jpeg((90, 200, 100), face_shade=220),
        "nabil 1.jpg": jpeg((120, 120, 120), face_shade=250), "nabil 2.jpg": jpeg((150, 90, 60), face_shade=252),
        "tree.jpg": jpeg((30, 120, 30)), "once.jpg": jpeg((60, 60, 60), face_shade=160),
    })
    people = (await client.get("/api/people")).json()
    assert sorted(p["photos"] for p in people) == [2, 3]  # the lone face isn't a person yet
    rina = next(p for p in people if p["photos"] == 3)
    named = (await client.patch(f"/api/people/{rina['id']}", json={"name": "Rina"})).json()
    assert named["name"] == "Rina"
    pics = (await client.get(f"/api/people/{rina['id']}/photos")).json()
    assert {p["filename"] for p in pics} == {"rina 1.jpg", "rina 2.jpg", "rina 3.jpg"}
    crop = await client.get(f"/api/faces/{rina['cover_face']}/crop")
    assert crop.status_code == 200 and crop.headers["content-type"] == "image/webp"

    # "not this person" takes one photo out, and it stays out when indexed again
    faces = (await client.get(f"/api/people/{rina['id']}/faces")).json()
    wrong = next(f for f in faces if f["asset_id"] == got["rina 3.jpg"]["id"])
    assert (await client.delete(f"/api/people/{rina['id']}/faces/{wrong['id']}")).status_code == 204
    from app.services.ai_jobs import ai_photo
    await ai_photo(None, got["rina 3.jpg"]["id"])
    assert len((await client.get(f"/api/people/{rina['id']}/photos")).json()) == 2

    # the same person found twice: merge
    nabil = next(p for p in people if p["photos"] == 2)
    assert (await client.post(f"/api/people/{nabil['id']}/merge", json={"into": rina["id"]})).status_code == 204
    people = (await client.get("/api/people")).json()
    assert [p["name"] for p in people] == ["Rina"]

    # nobody else sees them
    await client.post("/api/users", json={"username": "guest", "password": "password12"})
    tok = (await client.post("/api/auth/login", json={"username": "guest", "password": "password12"})).json()["token"]
    other = {"Authorization": f"Bearer {tok}"}
    assert (await client.get("/api/people", headers=other)).json() == []
    assert (await client.get(f"/api/people/{rina['id']}/photos", headers=other)).status_code == 404
    assert (await client.get(f"/api/faces/{rina['cover_face']}/crop", headers=other)).status_code == 404


async def test_ai_subtitles(client, admin, local_ai, tmp_path):
    make_video(tmp_path / "films" / "Monpura (2009).mp4", seconds=2)
    await client.post("/api/libraries", json={"name": "Films", "path": str(tmp_path / "films"), "kind": "movies"})
    await jobs.drain_local()
    film = (await client.get("/api/media")).json()[0]
    r = await client.post(f"/api/media/{film['id']}/ai-subtitles", json={})
    assert r.status_code == 202
    await jobs.drain_local()
    tracks = (await client.get(f"/api/media/{film['id']}/tracks")).json()
    assert tracks["ai_subtitles"] == "done:bn"
    ai_track = next(s for s in tracks["subtitles"] if s["id"] == "ai")
    assert ai_track["label"] == "Bangla (AI)"
    vtt = await client.get(f"/api/media/{film['id']}/subtitles/ai.vtt")
    assert vtt.status_code == 200 and "আমি বাংলায়" in vtt.text


async def test_ask_your_files(client, admin, local_ai):
    await upload(client, "passport.txt", "Passport no. on file. The passport expires on 3 March 2031.".encode(), folder="/Papers")
    await upload(client, "electricity.txt", b"Electricity bill for May: 2,340 taka. Pay by the 15th.", folder="/Papers")
    await jobs.drain_local()
    await jobs.drain_local()
    st = (await client.get("/api/ai/status")).json()
    assert st["documents_ready"] == 2
    r = (await client.post("/api/ask", json={"question": "When does my passport expire?"})).json()
    assert "2031" in r["answer"]
    assert [s["filename"] for s in r["sources"]] == ["passport.txt"]
    assert "passport.txt (/Papers)" in ASKED[-1]  # the model only saw passages from the person's files
    r = (await client.post("/api/ask", json={"question": "আমার পাসপোর্ট কবে শেষ হবে?"})).json()
    assert r["sources"][0]["filename"] == "passport.txt"

    # someone else's question doesn't reach these files
    await client.post("/api/users", json={"username": "guest", "password": "password12"})
    tok = (await client.post("/api/auth/login", json={"username": "guest", "password": "password12"})).json()["token"]
    r = (await client.post("/api/ask", json={"question": "When does my passport expire?"},
                           headers={"Authorization": f"Bearer {tok}"})).json()
    assert r["sources"] == [] and "couldn't find" in r["answer"]


def test_passages():
    from app.services.ai_jobs import chunks
    text = ("This is a sentence about a passport. " * 60) + "\n" + ("অন্য একটি বাক্য। " * 40)
    parts = chunks(text)
    assert len(parts) > 2 and all(len(p) <= 950 for p in parts)
    assert parts[0].endswith(".")
