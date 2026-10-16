from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import User
from ..schemas import (LoginIn, PasswordChangeIn, SetupIn, TokenOut, UserCreateIn, UserOut)
from ..security import (COOKIE_NAME, admin_user, create_token, current_user, hash_password,
                        verify_password)

router = APIRouter(prefix="/api", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax",
                        max_age=get_settings().access_token_days * 86400, path="/")


@router.get("/setup/status")
async def setup_status(session: AsyncSession = Depends(get_session)) -> dict:
    count = await session.scalar(select(func.count()).select_from(User))
    return {"needs_setup": count == 0}


@router.post("/setup", response_model=TokenOut)
async def setup(body: SetupIn, response: Response, session: AsyncSession = Depends(get_session)):
    """First run only: create the admin account."""
    if await session.scalar(select(func.count()).select_from(User)):
        raise HTTPException(409, "Setup already done")
    user = User(username=body.username.lower(), password_hash=hash_password(body.password),
                is_admin=True)
    session.add(user)
    await session.commit()
    token = create_token(user.id)
    _set_cookie(response, token)
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, response: Response, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.username == body.username.lower().strip()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong username or password")
    token = create_token(user.id)
    _set_cookie(response, token)
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.post("/auth/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/auth/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user


@router.post("/auth/password", status_code=204)
async def change_password(body: PasswordChangeIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    session.add(user)
    await session.commit()


# ------------------------------------------------------------ user admin

@router.get("/users", response_model=list[UserOut])
async def list_users(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    return (await session.scalars(select(User).order_by(User.created_at))).all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreateIn, _: User = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    quota = int(body.quota_gb * 1024**3) if body.quota_gb else None
    user = User(username=body.username.lower(), password_hash=hash_password(body.password),
                is_admin=body.is_admin, quota_bytes=quota)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "That username is taken")
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, admin: User = Depends(admin_user),
                      session: AsyncSession = Depends(get_session)):
    if user_id == admin.id:
        raise HTTPException(400, "You can't delete your own account")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    # Their files stay on disk under storage/<username>; only the account is removed.
    await session.delete(user)
    await session.commit()
