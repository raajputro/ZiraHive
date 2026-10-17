"""Settings > Server > Plugins, and the pages plugins add under /api/plugins/<id>/..."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import PluginState, User
from ..security import admin_user, current_user
from ..services import plugins
from ..services.events import audit

router = APIRouter(prefix="/api", tags=["plugins"])


class SettingOut(BaseModel):
    key: str
    label: str
    type: str
    help: str | None = None
    choices: list[str] = []
    value: Any = None       # secrets are never sent back
    has_value: bool = False


class PluginOut(BaseModel):
    id: str
    name: str
    description: str
    version: str
    author: str | None
    builtin: bool
    enabled: bool
    events: list[str]
    settings: list[SettingOut]
    error: str | None = None          # the plugin can't be used (bad plugin.json)
    last_error: str | None = None
    last_error_at: datetime | None = None
    last_ok_at: datetime | None = None
    has_pages: bool = False


class PluginIn(BaseModel):
    enabled: bool | None = None
    settings: dict[str, Any] | None = None  # a secret left empty keeps the saved one


class TestOut(BaseModel):
    ok: bool
    error: str | None = None


def _out(m: plugins.Manifest, st: PluginState | None) -> PluginOut:
    saved = json.loads(st.settings_json or "{}") if st else {}
    values = plugins.settings_for(m, saved)
    has_pages = False
    if st and st.enabled and not m.error:
        try:
            has_pages = hasattr(plugins.load(m), "handle")
        except Exception:
            pass
    return PluginOut(
        id=m.id, name=m.name, description=m.description, version=m.version, author=m.author, builtin=m.builtin,
        enabled=bool(st and st.enabled), events=m.events, error=m.error, has_pages=has_pages,
        last_error=st.last_error if st else None, last_error_at=st.last_error_at if st else None,
        last_ok_at=st.last_ok_at if st else None,
        settings=[SettingOut(key=s.key, label=s.label, type=s.type, help=s.help, choices=s.choices,
                             value=None if s.type == "secret" else values.get(s.key),
                             has_value=bool(values.get(s.key))) for s in m.settings])


def _manifest(pid: str) -> plugins.Manifest:
    m = plugins.discover().get(pid)
    if m is None:
        raise HTTPException(404, "No such plugin")
    return m


@router.get("/admin/plugins", response_model=list[PluginOut])
async def list_plugins(_: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    return [_out(m, await session.get(PluginState, m.id)) for m in plugins.discover().values()]


def _clean(m: plugins.Manifest, given: dict[str, Any], saved: dict) -> dict:
    out = dict(saved)
    for s in m.settings:
        if s.key not in given:
            continue
        v = given[s.key]
        if s.type == "secret" and (v is None or v == ""):
            continue  # keep the saved secret
        if s.type == "bool":
            v = bool(v)
        elif s.type == "number":
            try:
                v = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                raise HTTPException(400, f"{s.label}: enter a number") from None
        elif s.type == "choice":
            if v not in s.choices:
                raise HTTPException(400, f"{s.label}: choose one of {', '.join(s.choices)}")
        else:
            v = str(v or "").strip()[:2000]
        out[s.key] = v
    return out


@router.put("/admin/plugins/{pid}", response_model=PluginOut)
async def update_plugin(pid: str, body: PluginIn, request: Request, admin: User = Depends(admin_user),
                        session: AsyncSession = Depends(get_session)):
    m = _manifest(pid)
    if m.error:
        raise HTTPException(400, f"This plugin can't be used: {m.error}")
    st = await session.get(PluginState, pid) or PluginState(id=pid, enabled=False, settings_json="{}")
    session.add(st)
    if body.settings is not None:
        st.settings_json = json.dumps(_clean(m, body.settings, json.loads(st.settings_json or "{}")))
        await audit(session, "plugin_settings", admin, detail=m.name, request=request)
    if body.enabled is not None and body.enabled != st.enabled:
        if body.enabled:
            try:
                plugins.load(m)  # a broken plugin.py is reported now, not on the first event
            except Exception as exc:
                raise HTTPException(400, f"The plugin's code didn't load: {type(exc).__name__}: {exc}") from None
            st.last_error = None
        st.enabled = body.enabled
        await audit(session, "plugin_enabled" if body.enabled else "plugin_disabled", admin, detail=m.name,
                    request=request)
    await session.commit()
    return _out(m, st)


@router.post("/admin/plugins/{pid}/test", response_model=TestOut)
async def test_plugin(pid: str, admin: User = Depends(admin_user), session: AsyncSession = Depends(get_session)):
    m = _manifest(pid)
    st = await session.get(PluginState, pid)
    if st is None or not st.enabled:
        raise HTTPException(409, "Turn the plugin on first")
    event = plugins.Event("plugin.test", {"by": admin.username, "message": "A test from GharBox"})
    error = await plugins.deliver(m, json.loads(st.settings_json or "{}"), event)
    return TestOut(ok=error is None, error=error)


@router.api_route("/plugins/{pid}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def plugin_page(pid: str, path: str, request: Request, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    """A plugin's own API. Only for signed-in people, and only while the plugin is on."""
    m = plugins.discover().get(pid)
    st = await session.get(PluginState, pid) if m else None
    if m is None or m.error or st is None or not st.enabled:
        raise HTTPException(404, "No such plugin")
    module = plugins.load(m)
    handler = getattr(module, "handle", None)
    if handler is None:
        raise HTTPException(404, "This plugin has no pages")
    ctx = plugins.Context(m, plugins.settings_for(m, json.loads(st.settings_json or "{}")))
    ctx.user = user  # type: ignore[attr-defined]
    ctx.path = path  # type: ignore[attr-defined]
    try:
        result = await handler(request, ctx)
    except HTTPException:
        raise
    except Exception as exc:
        plugins.log.warning("plugin %s page failed: %s", pid, exc)
        await plugins._record(pid, f"page {path}: {type(exc).__name__}: {exc}")
        raise HTTPException(500, "The plugin failed. Settings > Server > Plugins has the details.") from None
    return result if isinstance(result, Response) else JSONResponse(result)
