from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .models import User

COOKIE_NAME = "gharbox_token"
_hasher = PasswordHasher()
_ALGO = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_token(user_id: str, days: int | None = None) -> str:
    settings = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(days=days or settings.access_token_days)
    return jwt.encode({"sub": user_id, "exp": exp}, settings.resolved_secret(), algorithm=_ALGO)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().resolved_secret(), algorithms=[_ALGO])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # <img>/<video> tags can't send headers: accept the cookie or a ?token= query param.
    return request.cookies.get(COOKIE_NAME) or request.query_params.get("token")


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    token = _token_from_request(request)
    user_id = decode_token(token) if token else None
    user = await session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user
