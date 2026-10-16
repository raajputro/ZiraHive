"""Encrypted offsite backup with restic.

restic encrypts and de-duplicates everything on this PC before it is written to the target,
so a USB disk, a friend's server or a cloud bucket only ever holds ciphertext. Each run:

  1. dumps the database (pg_dump, or SQLite's online backup) into data/backup-staging,
  2. backs up the data folder (photos, files, vault, database dump) minus caches,
     plus the media folders if chosen,
  3. on Sundays, forgets old snapshots (7 daily, 5 weekly, 12 monthly by default) and prunes.

Restoring is documented in docs/BACKUP.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import BackupConfig, BackupRun, Library, utcnow

log = logging.getLogger(__name__)
_running = asyncio.Lock()


class BackupError(RuntimeError):
    pass


def restic_bin() -> str | None:
    return shutil.which("restic")


def new_password() -> str:
    """A long random repository password: 6 groups of 5, easy to write down."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(6))


def _env(cfg: BackupConfig) -> dict[str, str]:
    s = get_settings()
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TZ", "LANG", "SSL_CERT_FILE", "HTTPS_PROXY",
                                                         "HTTP_PROXY", "NO_PROXY")}
    env.setdefault("HOME", str(s.data_dir))
    env.update({k: str(v) for k, v in json.loads(cfg.env_json or "{}").items() if v})
    env.update({"RESTIC_REPOSITORY": cfg.repository, "RESTIC_PASSWORD": cfg.password,
                "RESTIC_CACHE_DIR": str(s.cache_dir / "restic"),
                # rclone remotes (Google Drive, OneDrive, ...) are set up once with `rclone config`
                "RCLONE_CONFIG": str(s.data_dir / "rclone.conf")})
    return env


async def restic(cfg: BackupConfig, *args: str, timeout: float = 6 * 3600) -> tuple[int, str, str]:
    exe = restic_bin()
    if not exe:
        raise BackupError("restic is not installed (the GharBox Docker image includes it)")
    proc = await asyncio.create_subprocess_exec(exe, *args, env=_env(cfg), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise BackupError(f"restic {args[0]} took too long")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _short(err: str) -> str:
    lines = [ln for ln in err.strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "unknown error")[:400]


async def ensure_repository(cfg: BackupConfig) -> bool:
    """Opens the repository, creating it the first time. True when it was just created."""
    rc, _, err = await restic(cfg, "cat", "config", timeout=300)
    if rc == 0:
        return False
    low = err.lower()
    if "wrong password" in low or "no key found" in low:
        raise BackupError("A backup already exists there with a different password. Use that password, or another place.")
    if not any(s in low for s in ("does not exist", "no such file", "unable to open config", "not found", "is not a")):
        raise BackupError(f"Couldn't reach the backup place: {_short(err)}")
    if cfg.repository.startswith("/"):
        Path(cfg.repository).parent.mkdir(parents=True, exist_ok=True)
    rc, _, err = await restic(cfg, "init", timeout=600)
    if rc != 0:
        raise BackupError(f"Couldn't create the backup: {_short(err)}")
    return True


def _sqlite_copy(src: Path, dest: Path) -> None:
    with sqlite3.connect(src) as a, sqlite3.connect(dest) as b:
        a.backup(b)


async def dump_database(staging: Path) -> Path:
    """A consistent copy of the database to back up (the live files may be mid-write)."""
    s = get_settings()
    staging.mkdir(parents=True, exist_ok=True)
    url = s.db_url
    if url.startswith("sqlite"):
        dest = staging / "gharbox.db"
        await asyncio.to_thread(_sqlite_copy, s.data_dir / "gharbox.db", dest)
        return dest
    u = urlparse(url.replace("+asyncpg", ""))
    exe = shutil.which("pg_dump")
    if not exe:
        raise BackupError("pg_dump is not installed (the GharBox Docker image includes it)")
    dest = staging / "gharbox.pgdump"
    env = {"PATH": os.environ.get("PATH", ""), "PGPASSWORD": u.password or ""}
    proc = await asyncio.create_subprocess_exec(
        exe, "--format=custom", "--no-owner", "-h", u.hostname or "localhost", "-p", str(u.port or 5432),
        "-U", u.username or "postgres", "-f", str(dest), (u.path or "/gharbox").lstrip("/"),
        env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise BackupError(f"Couldn't copy the database: {_short(err.decode(errors='replace'))}")
    return dest


async def _paths(session: AsyncSession, cfg: BackupConfig) -> list[str]:
    s = get_settings()
    paths = [str(s.data_dir)]
    if cfg.include_media:
        for lib in (await session.scalars(select(Library))).all():
            if Path(lib.path).is_dir():
                paths.append(lib.path)
    return paths


def _excludes() -> list[str]:
    s = get_settings()
    out = []
    for p in (s.cache_dir, s.upload_dir, s.data_dir / "gharbox.db", s.data_dir / "gharbox.db-wal",
              s.data_dir / "gharbox.db-shm", s.data_dir / "restore"):
        out += ["--exclude", str(p)]
    return out


async def run_backup(session: AsyncSession) -> BackupRun:
    cfg = await session.get(BackupConfig, "main")
    if cfg is None or not cfg.enabled:
        raise BackupError("Offsite backup isn't set up")
    if _running.locked():
        raise BackupError("A backup is already running")
    async with _running:
        run = BackupRun(kind="backup")
        session.add(run)
        await session.commit()
        staging = get_settings().data_dir / "backup-staging"
        try:
            await ensure_repository(cfg)
            await dump_database(staging)
            rc, out, err = await restic(cfg, "backup", "--json", "--host", "gharbox", "--tag", "gharbox",
                                        *_excludes(), *(await _paths(session, cfg)))
            if rc not in (0, 3):  # 3 = some files couldn't be read (reported, the rest is saved)
                raise BackupError(_short(err))
            summary = next((json.loads(ln) for ln in reversed(out.splitlines())
                            if ln.startswith("{") and '"message_type":"summary"' in ln), {})
            run.snapshot_id = summary.get("snapshot_id")
            run.files_new, run.files_changed = summary.get("files_new"), summary.get("files_changed")
            run.bytes_added = summary.get("data_added")
            run.total_bytes = summary.get("total_bytes_processed")
            run.message = "Some files couldn't be read and were skipped" if rc == 3 else None
            if datetime.now(timezone.utc).weekday() == 6:
                await restic(cfg, "forget", "--tag", "gharbox", "--keep-daily", str(cfg.keep_daily),
                             "--keep-weekly", str(cfg.keep_weekly), "--keep-monthly", str(cfg.keep_monthly), "--prune")
            run.status = "ok"
        except BackupError as exc:
            run.status, run.message = "failed", str(exc)
        except Exception as exc:  # never leave a run "running"
            log.exception("backup failed")
            run.status, run.message = "failed", f"Unexpected error: {exc}"
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            run.finished_at = utcnow()
            await session.commit()
        if run.status == "failed":
            from .events import notify_admins

            await notify_admins(session, "backup", "Offsite backup failed", run.message, link="/settings#server")
            await session.commit()
        return run


async def run_check(session: AsyncSession, subset: str = "5%") -> BackupRun:
    """Reads back part of the stored data to prove the backup can be restored."""
    cfg = await session.get(BackupConfig, "main")
    if cfg is None:
        raise BackupError("Offsite backup isn't set up")
    async with _running:
        run = BackupRun(kind="check")
        session.add(run)
        await session.commit()
        try:
            rc, _, err = await restic(cfg, "check", f"--read-data-subset={subset}")
            run.status, run.message = ("ok", None) if rc == 0 else ("failed", _short(err))
        except BackupError as exc:
            run.status, run.message = "failed", str(exc)
        run.finished_at = utcnow()
        await session.commit()
        return run


async def snapshots(cfg: BackupConfig) -> list[dict]:
    rc, out, err = await restic(cfg, "snapshots", "--no-lock", "--json", "--tag", "gharbox", timeout=300)
    if rc != 0:
        raise BackupError(_short(err))
    return json.loads(out or "[]")


async def due(session: AsyncSession, now: datetime | None = None) -> bool:
    """Once a day at the chosen hour (UTC), or as soon as possible if the last one is over a day old."""
    cfg = await session.get(BackupConfig, "main")
    if cfg is None or not cfg.enabled:
        return False
    now = now or datetime.now(timezone.utc)
    last = await session.scalar(select(BackupRun).where(BackupRun.kind == "backup")
                                .order_by(BackupRun.started_at.desc()).limit(1))
    if last is None:
        return True
    started = last.started_at if last.started_at.tzinfo else last.started_at.replace(tzinfo=timezone.utc)
    age = (now - started).total_seconds()
    if last.status == "failed" and age > 3600:  # try again an hour after a failure
        return True
    return (now.hour == cfg.hour and age > 3 * 3600) or age > 26 * 3600
