"""Passkeys (WebAuthn): sign in with the fingerprint, face or PIN of a phone or laptop.

A passkey replaces both the password and the 6-digit code: it can't be phished (it only works on
the address it was made for) or guessed, and nothing secret is kept on the server, only a
public key. Browsers allow passkeys on https:// addresses and on localhost.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (base64url_to_bytes, generate_authentication_options, generate_registration_options,
                      options_to_json, verify_authentication_response, verify_registration_response)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from ..db import get_session
from ..models import Passkey, User, utcnow
from ..schemas import TokenOut, UserOut
from ..security import (client_ip, create_scoped_token, create_token, current_user, login_ip_throttle,
                        read_scope)
from ..services.events import audit, notify
from .auth import _set_cookie

router = APIRouter(prefix="/api/auth/passkeys", tags=["auth"])

_used: dict[str, float] = {}  # challenges already answered (each works once)


class PasskeyOut(BaseModel):
    id: str
    name: str
    rp_id: str
    created_at: datetime
    last_used_at: datetime | None = None


class OptionsOut(BaseModel):
    options: dict
    state: str


class RegisterIn(BaseModel):
    state: str
    credential: dict
    name: str = Field(default="", max_length=100)


class LoginIn(BaseModel):
    state: str
    credential: dict


def _site(request: Request) -> tuple[str, str]:
    """(rp_id, origin): the address the browser is on. It must be this server's own address."""
    origin = request.headers.get("origin") or ""
    host = urlsplit(origin).hostname
    served = urlsplit(f"//{request.headers.get('x-forwarded-host') or request.headers.get('host', '')}").hostname
    if not host or host != served:
        raise HTTPException(400, "Passkeys need the page and GharBox on the same address")
    if urlsplit(origin).scheme != "https" and host != "localhost":
        raise HTTPException(400, {"code": "passkey_insecure", "message":
                                  "Passkeys work on your https:// address, or on http://localhost on the server PC."})
    return host, origin


def _state(kind: str, challenge: bytes, rp_id: str, user_id: str = "") -> str:
    return create_scoped_token(f"webauthn:{kind}:{rp_id}:{user_id}:{bytes_to_base64url(challenge)}", 5)


def _read_state(state: str, kind: str, rp_id: str) -> tuple[str, bytes]:
    scope = read_scope(state, f"webauthn:{kind}:{rp_id}:")
    if not scope:
        raise HTTPException(400, "This request took too long. Try again.")
    user_id, _, challenge = scope.rpartition(":")
    now = time.time()
    for k, t in list(_used.items()):
        if now - t > 600:
            del _used[k]
    if challenge in _used:
        raise HTTPException(400, "This request was already used. Try again.")
    _used[challenge] = now
    return user_id, base64url_to_bytes(challenge)


def _out(p: Passkey) -> PasskeyOut:
    return PasskeyOut(id=p.id, name=p.name, rp_id=p.rp_id, created_at=p.created_at, last_used_at=p.last_used_at)


@router.get("", response_model=list[PasskeyOut])
async def list_passkeys(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.scalars(select(Passkey).where(Passkey.user_id == user.id)
                                  .order_by(Passkey.created_at))).all()
    return [_out(p) for p in rows]


@router.post("/register/options", response_model=OptionsOut)
async def register_options(request: Request, user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    rp_id, _ = _site(request)
    existing = (await session.scalars(select(Passkey).where(Passkey.user_id == user.id,
                                                            Passkey.rp_id == rp_id))).all()
    opts = generate_registration_options(
        rp_id=rp_id, rp_name="GharBox", user_id=user.id.encode(), user_name=user.username,
        user_display_name=user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id)) for p in existing])
    return OptionsOut(options=json.loads(options_to_json(opts)), state=_state("reg", opts.challenge, rp_id, user.id))


@router.post("/register", response_model=PasskeyOut, status_code=201)
async def register(body: RegisterIn, request: Request, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    rp_id, origin = _site(request)
    user_id, challenge = _read_state(body.state, "reg", rp_id)
    if user_id != user.id:
        raise HTTPException(400, "This request was for another account")
    try:
        v = verify_registration_response(credential=body.credential, expected_challenge=challenge,
                                         expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True)
    except Exception as exc:  # the library raises several kinds of InvalidRegistrationResponse
        raise HTTPException(400, f"The passkey couldn't be checked: {exc}") from None
    cred_id = bytes_to_base64url(v.credential_id)
    if await session.scalar(select(Passkey.id).where(Passkey.credential_id == cred_id)):
        raise HTTPException(409, "This passkey is already added")
    transports = (body.credential.get("response") or {}).get("transports")
    count = len((await session.scalars(select(Passkey.id).where(Passkey.user_id == user.id))).all())
    p = Passkey(user_id=user.id, credential_id=cred_id, public_key=v.credential_public_key, sign_count=v.sign_count,
                name=body.name.strip() or f"Passkey {count + 1}", rp_id=rp_id,
                transports=",".join(transports) if isinstance(transports, list) else None)
    session.add(p)
    await audit(session, "passkey_added", user, detail=p.name, request=request)
    await notify(session, user, "security", "A passkey was added to your account", p.name, link="/settings")
    await session.commit()
    return _out(p)


@router.delete("/{passkey_id}", status_code=204)
async def remove(passkey_id: str, request: Request, user: User = Depends(current_user),
                 session: AsyncSession = Depends(get_session)):
    p = await session.get(Passkey, passkey_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "No such passkey")
    await session.delete(p)
    await audit(session, "passkey_removed", user, detail=p.name, request=request)
    await session.commit()


@router.post("/login/options", response_model=OptionsOut)
async def login_options(request: Request):
    rp_id, _ = _site(request)
    login_ip_throttle.check(client_ip(request))
    opts = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    return OptionsOut(options=json.loads(options_to_json(opts)), state=_state("auth", opts.challenge, rp_id))


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    rp_id, origin = _site(request)
    ip = client_ip(request)
    login_ip_throttle.check(ip)
    _, challenge = _read_state(body.state, "auth", rp_id)

    def fail(message: str):
        login_ip_throttle.fail(ip)
        return HTTPException(401, message)

    p = await session.scalar(select(Passkey).where(Passkey.credential_id == str(body.credential.get("id", "")),
                                                   Passkey.rp_id == rp_id))
    if p is None:
        raise fail("This passkey isn't known here. It may have been removed, or made on another address.")
    handle = (body.credential.get("response") or {}).get("userHandle")
    if handle and base64url_to_bytes(handle) != p.user_id.encode():
        raise fail("This passkey belongs to another account")
    try:
        v = verify_authentication_response(credential=body.credential, expected_challenge=challenge,
                                           expected_rp_id=rp_id, expected_origin=origin,
                                           credential_public_key=p.public_key,
                                           credential_current_sign_count=p.sign_count, require_user_verification=True)
    except Exception:
        user = await session.get(User, p.user_id)
        await audit(session, "login_failed_passkey", user, request=request)
        await session.commit()
        raise fail("The passkey couldn't be checked. Try again.") from None
    user = await session.get(User, p.user_id)
    p.sign_count, p.last_used_at = v.new_sign_count, utcnow()
    await audit(session, "login", user, detail=f"passkey: {p.name}", request=request)
    await session.commit()
    token = create_token(user)
    _set_cookie(request, response, token)
    return TokenOut(token=token, user=UserOut.model_validate(user))

