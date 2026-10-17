"""Health check: is everything ZiraHive needs here and working?

Shown in Settings > Server > Health, and from the command line for when the web page doesn't
open at all:   docker compose exec api python -m app.doctor
Each item says what to do when it isn't right.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select

from ..config import get_settings


@dataclass
class Check:
    id: str
    title: str
    status: str          # ok | warn | fail | info
    detail: str = ""
    fix: str | None = None


def _tool(name: str, *args: str) -> str | None:
    """First line of `name --version` (or the given args), or None when it's missing."""
    exe = shutil.which(name)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, *(args or ("-version",))], capture_output=True, text=True, timeout=10)
        return ((out.stdout or out.stderr).strip().splitlines() or [name])[0][:120]
    except (OSError, subprocess.TimeoutExpired):
        return None


def _tesseract_languages() -> set[str]:
    exe = shutil.which("tesseract")
    if not exe:
        return set()
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=10).stdout
        return {ln.strip() for ln in out.splitlines()[1:] if ln.strip()}
    except (OSError, subprocess.TimeoutExpired):
        return set()


async def run_checks(session) -> list[Check]:
    from .. import db
    from ..main import VERSION
    from ..models import Library
    from . import ai, browse, jobs

    s = get_settings()
    out: list[Check] = [Check("version", "ZiraHive version", "info", VERSION)]

    # database and migrations
    try:
        conn = await session.connection()
        dialect = conn.dialect.name
        version = await conn.run_sync(db.schema_version)
        from alembic.script import ScriptDirectory
        from alembic.config import Config
        cfg = Config()
        cfg.set_main_option("script_location", str(db.MIGRATIONS))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        out.append(Check("database", "Database", "ok" if version == head else "fail",  # noqa: E501
                         f"{'PostgreSQL' if dialect == 'postgresql' else 'SQLite'}, schema {version or 'none'}",
                         None if version == head else "Restart ZiraHive: it upgrades the database when it starts."))
        if dialect == "sqlite":
            out.append(Check("database-kind", "Database for daily use", "info", "SQLite (fine for trying out)",
                             "The Docker install uses PostgreSQL, which copes better with several people at once."))
    except Exception as exc:  # noqa: BLE001 - shown to the admin
        out.append(Check("database", "Database", "fail", str(exc).splitlines()[0][:200],
                         "Check that the postgres container is running: docker compose ps"
                         if s.db_url.startswith("postgresql") else "Check that the data folder exists and can be written to."))

    # background jobs
    if s.redis_url:
        queued = await jobs.queued_count()
        out.append(Check("jobs", "Background jobs", "ok" if queued is not None else "fail",
                         f"worker queue, {queued} waiting" if queued is not None else "Redis can't be reached",
                         None if queued is not None else "Check the redis and worker containers: docker compose ps"))
    else:
        out.append(Check("jobs", "Background jobs", "info", "run inside the server (no worker)"))

    # storage
    try:
        probe = s.data_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        usage = shutil.disk_usage(s.data_dir)
        gb = usage.free / 1024 ** 3
        out.append(Check("storage", "Data folder", "ok" if gb > 10 else "warn",
                         f"{s.data_dir} · {gb:.0f} GB free of {usage.total / 1024 ** 3:.0f} GB",
                         None if gb > 10 else "Less than 10 GB left. Empty the trash or move ZIRAHIVE_DATA_PATH to a bigger drive."))
    except OSError as exc:
        out.append(Check("storage", "Data folder", "fail", f"{s.data_dir}: {exc.strerror or exc}",
                         "ZIRAHIVE_DATA_PATH in .env must point at a folder Docker may write to."))

    # media
    try:
        libs = (await session.scalars(select(Library))).all()
    except Exception:  # noqa: BLE001 - no tables yet
        await session.rollback()
        out.append(Check("setup", "Database tables", "fail", "not created yet",
                         "Start ZiraHive once (docker compose up -d); it sets up the database when it starts."))
        libs = []
    missing = [lib.name for lib in libs if not Path(lib.path).is_dir()]
    media_root = Path(s.media_root) if s.media_root else None
    if media_root and media_root.is_dir():
        inside = [p for p in media_root.iterdir() if p.is_dir() and not p.name.startswith((".", "$"))]
        out.append(Check("media", "Media folder", "ok" if inside else "warn",
                         f"{browse.display(media_root)}: {len(inside)} folders, {len(libs)} categories",
                         None if inside else "Make one folder per kind inside it (English Movies, Web Series, Music, ...)."))
    elif not libs:
        out.append(Check("media", "Media folder", "warn", "none yet",
                         "Run setup.ps1 and give your media folder (for example G:\\Media), or add a category "
                         "in Settings > Server > Categories."))
    if missing:
        out.append(Check("media-missing", "Categories whose folder can't be found", "warn", ", ".join(missing),
                         "Plug the drive in, or check MEDIA_PATH / DRIVE_ lines in .env, then restart."))

    # tools the features need
    tools = [("ffmpeg", "Video and music conversion", ("-version",)), ("ffprobe", "Reading video details", ("-version",)),
             ("pdftoppm", "Scanned PDFs and PDF covers", ("-v",)), ("bsdtar", "CBR/CB7 comics", ("--version",)),
             ("restic", "Offsite backup", ("version",))]
    if s.db_url.startswith("postgresql"):
        tools.append(("pg_dump", "Database copy in offsite backup", ("--version",)))
    for name, what, args in tools:
        found = await asyncio.to_thread(_tool, name, *args)
        out.append(Check(f"tool-{name}", what, "ok" if found else "warn", found or f"{name} not found",
                         None if found else f"Install {name} (the Docker image includes it)."))
    langs = await asyncio.to_thread(_tesseract_languages)
    need = {"ben", "eng"}
    out.append(Check("tool-tesseract", "Reading text in scans (Bangla and English)",
                     "ok" if need <= langs else "warn",
                     ", ".join(sorted(langs & need)) or "tesseract not found",
                     None if need <= langs else "Install tesseract with the Bangla (ben) and English (eng) languages."))

    # network
    out.append(Check("lan", "Home-network address (TVs, Chromecast)", "ok" if s.lan_url else "warn",
                     s.lan_url or "not set", None if s.lan_url else "Run setup.ps1, or set ZIRAHIVE_LAN_URL in .env."))
    out.append(Check("public", "Address for share links outside home", "ok" if s.public_url else "info",
                     s.public_url or "not set", None if s.public_url else "Optional: see docs/REMOTE_ACCESS.md."))

    # local AI (optional)
    a, o = await ai.ai_info(), await ai.ollama_info()
    out.append(Check("ai", "Local AI (optional)", "ok" if a and o else "info",
                     "pictures, faces, subtitles: " + ("running" if a else "off") + "; questions: " + ("running" if o else "off"),
                     None if a and o else "Optional: docker compose --profile ai up -d (docs/AI.md)."))
    return out


def as_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]

