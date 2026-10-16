"""Audio tracks, subtitles and chapters of a video, and turning subtitles into WebVTT.

Dual-audio releases (Hindi + English, Bangla + English) are common, so every audio track is
listed and can be picked in the player. Subtitles come from inside the file (text formats)
or from files next to it: Movie.srt, Movie.en.srt, Movie.bn.vtt, ...
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from ..config import get_settings

log = logging.getLogger(__name__)

TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
SIDECAR_EXT = {".srt", ".vtt", ".ass", ".ssa"}
_INTRO = re.compile(r"\b(intro|opening|op|recap|previously)\b", re.I)
_CREDITS = re.compile(r"\b(credits|ending|ed|outro|end credits)\b", re.I)
LANGS = {"eng": "English", "en": "English", "ben": "Bangla", "bn": "Bangla", "hin": "Hindi", "hi": "Hindi",
         "urd": "Urdu", "ur": "Urdu", "tam": "Tamil", "ta": "Tamil", "tel": "Telugu", "te": "Telugu",
         "kor": "Korean", "ko": "Korean", "jpn": "Japanese", "ja": "Japanese", "spa": "Spanish",
         "es": "Spanish", "fre": "French", "fra": "French", "fr": "French", "ara": "Arabic", "ar": "Arabic",
         "chi": "Chinese", "zho": "Chinese", "zh": "Chinese", "ger": "German", "deu": "German", "de": "German"}


def language_name(code: str | None) -> str | None:
    if not code or code == "und":
        return None
    return LANGS.get(code.lower(), code)


def probe_tracks(path: Path) -> dict:
    """{"audio": [...], "subtitles": [...], "chapters": [...]} for one file."""
    s = get_settings()
    cmd = [s.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_streams", "-show_chapters", str(path)]
    try:
        data = json.loads(subprocess.run(cmd, capture_output=True, check=True, timeout=60).stdout or b"{}")
    except Exception as exc:
        log.warning("ffprobe tracks failed for %s: %s", path, exc)
        data = {}
    audio, subs = [], []
    for st in data.get("streams", []):
        tags = st.get("tags") or {}
        lang = language_name(tags.get("language"))
        title = tags.get("title")
        if st.get("codec_type") == "audio":
            label = title or lang or f"Track {len(audio) + 1}"
            if st.get("channels", 2) > 2:
                label += f" ({st['channels'] - 1}.1)" if st["channels"] in (6, 8) else f" ({st['channels']} ch)"
            audio.append({"index": len(audio), "label": label, "language": lang, "codec": st.get("codec_name"),
                          "default": bool(st.get("disposition", {}).get("default"))})
        elif st.get("codec_type") == "subtitle":
            text = st.get("codec_name") in TEXT_SUBS
            subs.append({"id": f"e{len([x for x in subs if x['id'].startswith('e')])}",
                         "stream": sum(1 for x in subs if x["source"] == "embedded"),
                         "source": "embedded", "label": title or lang or "Subtitles", "language": lang,
                         "usable": text,
                         "forced": bool(st.get("disposition", {}).get("forced"))})
    for sub in sidecar_subtitles(path):
        subs.append(sub)
    chapters = []
    for ch in data.get("chapters", []):
        try:
            chapters.append({"start": float(ch["start_time"]), "end": float(ch["end_time"]),
                             "title": (ch.get("tags") or {}).get("title", "")})
        except (KeyError, ValueError):
            pass
    return {"audio": audio, "subtitles": subs, "chapters": chapters}


def sidecar_subtitles(video: Path) -> list[dict]:
    """Subtitle files next to the video whose name starts with the video's name."""
    out = []
    try:
        siblings = sorted(video.parent.iterdir())
    except OSError:
        return out
    for i, f in enumerate(p for p in siblings if p.suffix.lower() in SIDECAR_EXT and p.stem.startswith(video.stem)):
        extra = f.stem[len(video.stem):].strip(" ._-")  # "en", "bn.forced", ""
        parts = [p for p in re.split(r"[ ._-]+", extra) if p]
        lang = next((language_name(p) for p in parts if p.lower() in LANGS), None)
        out.append({"id": f"x{i}", "source": "file", "file": f.name, "label": lang or (extra or "Subtitles"),
                    "language": lang, "usable": True, "forced": "forced" in (p.lower() for p in parts)})
    return out


def markers_from_chapters(chapters: list[dict], duration: float | None) -> dict:
    """Intro and credits positions when the file's chapters are named that way."""
    intro_start = intro_end = credits = None
    for ch in chapters:
        if _INTRO.search(ch["title"]) and ch["start"] < (duration or 1e9) * 0.4 and intro_end is None:
            intro_start, intro_end = ch["start"], ch["end"]
        elif _CREDITS.search(ch["title"]) and ch["start"] > (duration or 0) * 0.6:
            credits = ch["start"]
    return {"intro_start": intro_start, "intro_end": intro_end, "credits_start": credits}


def to_vtt(video: Path, sub: dict, dest: Path) -> None:
    """Convert one subtitle (embedded stream or sidecar file) to WebVTT for the browser."""
    s = get_settings()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.vtt")
    if sub["source"] == "file":
        src = video.parent / sub["file"]
        cmd = [s.ffmpeg_bin, "-y", "-v", "error", "-sub_charenc", "UTF-8", "-i", str(src), "-f", "webvtt", str(tmp)]
    else:
        cmd = [s.ffmpeg_bin, "-y", "-v", "error", "-i", str(video), "-map", f"0:s:{sub['stream']}",
               "-f", "webvtt", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0 and sub["source"] == "file":
        # Many Bangla/Hindi .srt files are not UTF-8; let ffmpeg guess instead.
        cmd = [c for c in cmd if c not in ("-sub_charenc", "UTF-8")]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(r.stderr.decode(errors="replace")[-300:])
    tmp.replace(dest)
