"""Settings > Server > Offsite backup (admins only)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import BackupConfig, BackupRun, User
from ..schemas import BackupConfigIn, BackupOut, BackupRunOut, SnapshotOut
from ..security import admin_user
from ..services import jobs, offsite
from ..services.events import audit

router = APIRouter(prefix="/api/admin/backup", tags=["backup"])

ENV_ALLOWED = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION", "B2_ACCOUNT_ID", "B2_ACCOUNT_KEY",
               "AZURE_ACCOUNT_NAME", "AZURE_ACCOUNT_KEY", "GOOGLE_PROJECT_ID", "RESTIC_REST_USERNAME",
               "RESTIC_REST_PASSWORD"}


async def _restic_version() -> str | None:
    if not offsite.restic_bin():
        return None
    import asyncio

    proc = await asyncio.create_subprocess_exec(offsite.restic_bin(), "version", stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    return out.decode().split(" compiled")[0].strip() or "restic"


async def _out(session: AsyncSession, cfg: BackupConfig | None, **extra) -> BackupOut:
    runs = (await session.scalars(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(10))).all()
    base = BackupOut(configured=cfg is not None, restic=await _restic_version(),
                     runs=[BackupRunOut.model_validate(r) for r in runs], **extra)
    if cfg:
        base.enabled, base.repository, base.hour, base.include_media = cfg.enabled, cfg.repository, cfg.hour, cfg.include_media
        base.env_keys = sorted(json.loads(cfg.env_json or "{}"))
    return base


@router.get("", response_model=BackupOut)
async def get_backup(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    return await _out(session, await session.get(BackupConfig, "main"))


@router.put("", response_model=BackupOut)
async def save_backup(body: BackupConfigIn, request: Request, user: User = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    """Saves the settings and opens (or creates) the encrypted repository to prove they work."""
    if body.env and set(body.env) - ENV_ALLOWED:
        raise HTTPException(422, f"Unknown setting: {', '.join(sorted(set(body.env) - ENV_ALLOWED))}")
    repo = body.repository.strip()
    if not (repo.startswith("/") or repo.split(":", 1)[0] in ("s3", "b2", "sftp", "rest", "rclone", "azure", "gs", "swift")):
        raise HTTPException(422, "Use a folder like /backup-disk/zirahive, or an address starting with s3:, b2:, sftp:, rest: or rclone:")
    cfg = await session.get(BackupConfig, "main")
    made_password = None
    if cfg is None:
        made_password = body.password or offsite.new_password()
        cfg = BackupConfig(id="main", repository=repo, password=made_password, env_json=json.dumps(body.env or {}))
        session.add(cfg)
    else:
        if repo != cfg.repository and body.password is None:
            made_password = cfg.password  # same password in the new place; show it again to write down
        cfg.repository = repo
        if body.password:
            cfg.password = made_password = body.password
        if body.env is not None:
            cfg.env_json = json.dumps(body.env)
    cfg.hour, cfg.include_media, cfg.enabled = body.hour, body.include_media, body.enabled
    try:
        created = await offsite.ensure_repository(cfg)
    except offsite.BackupError as exc:
        await session.rollback()
        raise HTTPException(400, str(exc))
    await audit(session, "backup_configured", user=user, detail=repo.split(":", 1)[0] if ":" in repo else "disk",
                request=request)
    await session.commit()
    return await _out(session, cfg, password=made_password, created=created)


@router.post("/run", status_code=202)
async def backup_now(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(BackupConfig, "main") is None:
        raise HTTPException(409, "Offsite backup isn't set up")
    await jobs.enqueue("offsite_backup")
    return {"status": "started"}


@router.post("/check", status_code=202)
async def check_now(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    if await session.get(BackupConfig, "main") is None:
        raise HTTPException(409, "Offsite backup isn't set up")
    await jobs.enqueue("offsite_check")
    return {"status": "started"}


@router.get("/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    cfg = await session.get(BackupConfig, "main")
    if cfg is None:
        raise HTTPException(409, "Offsite backup isn't set up")
    try:
        snaps = await offsite.snapshots(cfg)
    except offsite.BackupError as exc:
        raise HTTPException(502, str(exc))
    return [SnapshotOut(id=s["short_id"], time=s["time"], paths=s.get("paths", [])) for s in reversed(snaps)]


@router.get("/password")
async def show_password(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)) -> dict:
    """The admin may need it again to write down; it is needed to restore on a new PC."""
    cfg = await session.get(BackupConfig, "main")
    if cfg is None:
        raise HTTPException(404, "Offsite backup isn't set up")
    return {"password": cfg.password}
