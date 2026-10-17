from __future__ import annotations

import io
import secrets

import pyotp
import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Asset, AssetVersion, RecoveryCode, User, utcnow
from ..schemas import (CodeIn, LoginIn, MeOut, MySettingsIn, PasswordChangeIn, PasswordIn,
                       RecoveryCodesOut, SetupIn, TokenOut, TwoFactorSetupOut, UserAdminOut,
                       UserCreateIn, UserOut, UserUpdateIn)
from ..security import (COOKIE_NAME, admin_user, client_ip, create_token, current_user,
                        hash_password, login_ip_throttle, login_throttle, use_secure_cookie,
                        verify_password)
from ..services.events import audit, notify

router = APIRouter(prefix="/api", tags=["auth"])


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=use_secure_cookie(request),
                        max_age=get_settings().access_token_days * 86400, path="/")


async def used_bytes(session: AsyncSession, user_id: str) -> int:
    files = await session.scalar(select(func.coalesce(func.sum(Asset.size), 0)).where(
        Asset.owner_id == user_id)) or 0
    versions = await session.scalar(select(func.coalesce(func.sum(AssetVersion.size), 0))
                                    .join(Asset, Asset.id == AssetVersion.asset_id)
                                    .where(Asset.owner_id == user_id)) or 0
    from .vault import vault_bytes

    return int(files) + int(versions) + await vault_bytes(session, user_id)


@router.get("/setup/status")
async def setup_status(session: AsyncSession = Depends(get_session)) -> dict:
    count = await session.scalar(select(func.count()).select_from(User))
    return {"needs_setup": count == 0}


@router.post("/setup", response_model=TokenOut)
async def setup(body: SetupIn, request: Request, response: Response,
                session: AsyncSession = Depends(get_session)):
    """First run only: create the admin account."""
    if await session.scalar(select(func.count()).select_from(User)):
        raise HTTPException(409, "Setup already done")
    user = User(username=body.username.lower(), password_hash=hash_password(body.password),
                is_admin=True)
    session.add(user)
    await session.flush()
    await audit(session, "setup", user, request=request)
    await session.commit()
    token = create_token(user)
    _set_cookie(request, response, token)
    return TokenOut(token=token, user=UserOut.model_validate(user))


async def _check_second_factor(session: AsyncSession, user: User, code: str | None) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code:
        return False
    if code.isdigit() and len(code) == 6:
        return pyotp.TOTP(user.totp_secret).verify(code, valid_window=1)
    for rc in (await session.scalars(select(RecoveryCode).where(
            RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)))).all():
        if verify_password(code.lower(), rc.code_hash):
            rc.used_at = utcnow()
            return True
    return False


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response,
                session: AsyncSession = Depends(get_session)):
    username = body.username.lower().strip()
    ip = client_ip(request)
    key = f"{ip}:{username}"
    login_ip_throttle.check(ip)
    login_throttle.check(key)
    user = await session.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(body.password, user.password_hash):
        login_throttle.fail(key)
        login_ip_throttle.fail(ip)
        await audit(session, "login_failed", username=username, request=request)
        await session.commit()
        raise HTTPException(401, "Wrong username or password")
    if user.totp_enabled:
        if not body.code:
            raise HTTPException(401, {"code": "2fa_required",
                                      "message": "Enter the 6-digit code from your authenticator app"})
        if not await _check_second_factor(session, user, body.code):
            login_throttle.fail(key)
            login_ip_throttle.fail(ip)
            await audit(session, "login_failed_2fa", user, request=request)
            await session.commit()
            raise HTTPException(401, {"code": "2fa_invalid", "message": "That code didn't work. Try the newest one."})
    login_throttle.reset(key)
    await audit(session, "login", user, request=request)
    await session.commit()
    token = create_token(user)
    _set_cookie(request, response, token)
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.post("/auth/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@router.post("/auth/logout-all", status_code=204)
async def logout_everywhere(request: Request, response: Response, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    """Sign out on every phone and browser, e.g. after losing a phone."""
    user.token_version = (user.token_version or 0) + 1
    await audit(session, "logout_all", user, request=request)
    await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/auth/me", response_model=MeOut)
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    out = MeOut.model_validate(user)
    out.used_bytes = await used_bytes(session, user.id)
    return out


@router.put("/auth/me/settings", response_model=MeOut)
async def update_my_settings(body: MySettingsIn, user: User = Depends(current_user),
                             session: AsyncSession = Depends(get_session)):
    if "ntfy_url" in body.model_fields_set:
        user.ntfy_url = body.ntfy_url or None
    if "language" in body.model_fields_set:
        user.language = body.language or None
    await session.commit()
    return await me(user, session)


@router.post("/auth/device-token")
async def device_token(request: Request, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)) -> dict:
    """A sign-in for an app on a computer (the PC sync client) that lasts a year.
    "Sign out everywhere" and changing the password still end it."""
    await audit(session, "device_linked", user, detail=request.headers.get("user-agent", "")[:120], request=request)
    await session.commit()
    return {"token": create_token(user, days=365)}


@router.post("/auth/me/test-notification", status_code=204)
async def test_notification(user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    await notify(session, user, "test", "Notifications work", "This is a test from GharBox.")
    await session.commit()


@router.post("/auth/password", response_model=TokenOut)
async def change_password(body: PasswordChangeIn, request: Request, response: Response,
                          user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Changes the password and signs out every other device."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1
    await audit(session, "password_changed", user, request=request)
    await session.commit()
    token = create_token(user)
    _set_cookie(request, response, token)
    return TokenOut(token=token, user=UserOut.model_validate(user))


# ----------------------------------------------------------- two-factor

@router.post("/auth/2fa/setup", response_model=TwoFactorSetupOut)
async def two_factor_setup(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Step 1: make a secret and show it as a QR code. Nothing changes until /enable."""
    if user.totp_enabled:
        raise HTTPException(409, "Two-factor sign-in is already on")
    user.totp_secret = pyotp.random_base32()
    await session.commit()
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.username, issuer_name="GharBox")
    buf = io.BytesIO()
    segno.make(uri, error="m").save(buf, kind="svg", scale=5, border=2, xmldecl=False,
                                     svgns=True, dark="#1F2A44", light="#FFFFFF")
    return TwoFactorSetupOut(secret=user.totp_secret, uri=uri, qr_svg=buf.getvalue().decode())


@router.post("/auth/2fa/enable", response_model=RecoveryCodesOut)
async def two_factor_enable(body: CodeIn, request: Request, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    """Step 2: confirm with a code from the app. Returns one-time recovery codes."""
    if not user.totp_secret or user.totp_enabled:
        raise HTTPException(409, "Start two-factor setup first")
    if not pyotp.TOTP(user.totp_secret).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "That code didn't work. Check the time on your phone and try the newest code.")
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(10)]
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    for c in codes:
        session.add(RecoveryCode(user_id=user.id, code_hash=hash_password(c)))
    user.totp_enabled = True
    await audit(session, "2fa_enabled", user, request=request)
    await session.commit()
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/auth/2fa/disable", status_code=204)
async def two_factor_disable(body: PasswordIn, request: Request, user: User = Depends(current_user),
                             session: AsyncSession = Depends(get_session)):
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "Password is wrong")
    await _turn_off_2fa(session, user)
    await audit(session, "2fa_disabled", user, request=request)
    await session.commit()


async def _turn_off_2fa(session: AsyncSession, user: User) -> None:
    user.totp_enabled, user.totp_secret = False, None
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))


# ------------------------------------------------------------ user admin

async def _admin_out(session: AsyncSession, user: User) -> UserAdminOut:
    out = UserAdminOut.model_validate(user)
    out.used_bytes = await used_bytes(session, user.id)
    return out


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    users = (await session.scalars(select(User).order_by(User.created_at))).all()
    return [await _admin_out(session, u) for u in users]


@router.get("/users/directory", response_model=list[UserOut])
async def user_directory(_: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Everyone on this server, for picking who to share an album with."""
    return (await session.scalars(select(User).order_by(User.username))).all()


@router.post("/users", response_model=UserAdminOut, status_code=201)
async def create_user(body: UserCreateIn, request: Request, admin: User = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    quota = int(body.quota_gb * 1024**3) if body.quota_gb else None
    user = User(username=body.username.lower(), password_hash=hash_password(body.password),
                is_admin=body.is_admin, quota_bytes=quota)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(409, "That username is taken")
    await audit(session, "user_created", admin, detail=user.username, request=request)
    await session.commit()
    from ..services.plugins import emit

    await emit("user.created", {"username": user.username, "by": admin.username, "is_admin": user.is_admin})
    return await _admin_out(session, user)


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def update_user(user_id: str, body: UserUpdateIn, request: Request,
                      admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    changes = []
    if body.max_age is not None:
        user.max_age = None if body.max_age < 0 else body.max_age
        changes.append(f"age limit={user.max_age or 'none'}")
    if body.is_admin is not None and body.is_admin != user.is_admin:
        if user.id == admin.id and not body.is_admin:
            raise HTTPException(400, "You can't remove your own admin role")
        user.is_admin = body.is_admin
        changes.append(f"admin={body.is_admin}")
    if body.clear_quota:
        user.quota_bytes = None
        changes.append("quota=unlimited")
    elif body.quota_gb is not None:
        user.quota_bytes = int(body.quota_gb * 1024**3)
        changes.append(f"quota={body.quota_gb}GB")
    if body.new_password:
        user.password_hash = hash_password(body.new_password)
        user.token_version = (user.token_version or 0) + 1
        changes.append("password reset")
    if body.reset_2fa:
        await _turn_off_2fa(session, user)
        changes.append("2fa reset")
    await audit(session, "user_updated", admin, detail=f"{user.username}: {', '.join(changes) or 'no change'}",
                request=request)
    await session.commit()
    return await _admin_out(session, user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request, admin: User = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    if user_id == admin.id:
        raise HTTPException(400, "You can't delete your own account")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    # Their files stay on disk under storage/<username>; only the account is removed.
    await audit(session, "user_deleted", admin, detail=user.username, request=request)
    await session.delete(user)
    await session.commit()
