from __future__ import annotations

import time
from collections import defaultdict
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


def create_token(user: User, days: int | None = None) -> str:
    """A sign-in token. It stops working when the user's token_version changes
    (password change, 'sign out everywhere')."""
    settings = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(days=days or settings.access_token_days)
    payload = {"sub": user.id, "v": user.token_version or 0, "exp": exp}
    return jwt.encode(payload, settings.resolved_secret(), algorithm=_ALGO)


def create_scoped_token(scope: str, minutes: int) -> str:
    """A short-lived token that only grants one thing, e.g. 'share:<token>' or '2fa:<user id>'."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return jwt.encode({"scope": scope, "exp": exp}, get_settings().resolved_secret(), algorithm=_ALGO)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().resolved_secret(), algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None


def read_scope(token: str | None, prefix: str) -> str | None:
    payload = decode_token(token) if token else None
    scope = (payload or {}).get("scope") or ""
    return scope[len(prefix):] if scope.startswith(prefix) else None


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # <img>/<video> tags can't send headers: accept the cookie or a ?token= query param.
    return request.cookies.get(COOKIE_NAME) or request.query_params.get("token")


async def optional_user(request: Request, session: AsyncSession = Depends(get_session)) -> User | None:
    token = _token_from_request(request)
    payload = decode_token(token) if token else None
    if not payload or "sub" not in payload:
        return None
    user = await session.get(User, payload["sub"])
    if user is None or payload.get("v", 0) != (user.token_version or 0):
        return None
    request.state.user = user
    return user


async def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


class Throttle:
    """Slows down password guessing: at most `limit` failures per key in `window` seconds."""

    def __init__(self, limit: int = 10, window: int = 900):
        self.limit, self.window = limit, window
        self._fails: dict[str, list[float]] = defaultdict(list)

    def _recent(self, key: str) -> list[float]:
        now = time.monotonic()
        self._fails[key] = [t for t in self._fails[key] if now - t < self.window]
        return self._fails[key]

    def check(self, key: str) -> None:
        if len(self._recent(key)) >= self.limit:
            raise HTTPException(429, "Too many wrong attempts. Wait 15 minutes and try again.")

    def fail(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


login_throttle = Throttle()
share_throttle = Throttle(limit=20)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"
