"""Plugins: small Python add-ons that react to what happens in ZiraHive, or add their own pages.

A plugin is a folder with two files:

    plugin.json   what it is: id, name, description, version, the events it wants, its settings
    plugin.py     the code: `async def on_event(event, ctx)` and/or `async def handle(request, ctx)`

Built-in plugins live in app/plugins/; your own go in <data folder>/plugins/<id>/. A plugin's code
is only loaded once an admin turns it on (Settings > Server > Plugins), because it then runs with
ZiraHive's own rights. See docs/PLUGINS.md.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger("zirahive.plugins")

BUILTIN_DIR = Path(__file__).resolve().parent.parent / "plugins"
ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
SETTING_TYPES = {"text", "secret", "bool", "choice", "number"}
EVENT_TIMEOUT = 15

# Everything plugins can hear about. `data` never contains passwords or file contents.
EVENTS = {
    "file.uploaded": "A file or photo was uploaded (owner, folder, name, size, kind)",
    "media.added": "New movies or episodes were found in a category",
    "backup.finished": "An offsite backup run finished (ok or failed)",
    "party.created": "Someone started or planned a watch party",
    "user.created": "An admin added a person",
    "plugin.test": "Sent by the Send a test button",
}


@dataclass
class Setting:
    key: str
    label: str
    type: str = "text"
    default: Any = None
    help: str | None = None
    choices: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    id: str
    name: str
    description: str
    version: str
    folder: Path
    builtin: bool
    events: list[str]
    settings: list[Setting]
    author: str | None = None
    error: str | None = None  # the manifest couldn't be read


@dataclass
class Event:
    name: str
    data: dict
    time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Context:
    """What a plugin gets: its settings, a logger, an HTTP client, and a way to notify admins."""

    def __init__(self, manifest: Manifest, settings: dict):
        self.plugin_id = manifest.id
        self.settings = settings
        self.log = logging.getLogger(f"zirahive.plugin.{manifest.id}")
        self.public_url = get_settings().public_url

    def http(self, **kw) -> httpx.AsyncClient:
        kw.setdefault("timeout", 10)
        kw.setdefault("headers", {"User-Agent": "ZiraHive plugin"})
        return httpx.AsyncClient(**kw)

    async def notify_admins(self, title: str, body: str | None = None) -> None:
        from ..db import sessionmaker
        from .events import notify_admins

        async with sessionmaker()() as session:
            await notify_admins(session, "plugin", title, body)
            await session.commit()


def plugins_dir() -> Path:
    return get_settings().data_dir / "plugins"


def _read_manifest(folder: Path, builtin: bool) -> Manifest | None:
    path = folder / "plugin.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text("utf-8"))
        pid = str(raw["id"])
        if not ID.match(pid) or pid != folder.name:
            raise ValueError(f"the id must be lower-case letters, digits and dashes, and match the folder name ({folder.name})")
        settings = []
        for s in raw.get("settings", []):
            st = Setting(key=str(s["key"]), label=str(s.get("label", s["key"])), type=s.get("type", "text"),
                         default=s.get("default"), help=s.get("help"), choices=list(s.get("choices", [])))
            if st.type not in SETTING_TYPES:
                raise ValueError(f"setting {st.key}: unknown type {st.type}")
            settings.append(st)
        events = [str(e) for e in raw.get("events", [])]
        unknown = [e for e in events if e != "*" and e not in EVENTS]
        if unknown:
            raise ValueError(f"unknown events: {', '.join(unknown)}")
        if not (folder / "plugin.py").is_file():
            raise ValueError("plugin.py is missing")
        return Manifest(id=pid, name=str(raw.get("name", pid)), description=str(raw.get("description", "")),
                        version=str(raw.get("version", "")), author=raw.get("author"), folder=folder,
                        builtin=builtin, events=events, settings=settings)
    except (ValueError, KeyError, TypeError) as exc:
        return Manifest(id=folder.name, name=folder.name, description="", version="", folder=folder,
                        builtin=builtin, events=[], settings=[], error=f"plugin.json: {exc}")


def discover() -> dict[str, Manifest]:
    """Every plugin found, built-in first. A plugin of yours can't replace a built-in one."""
    found: dict[str, Manifest] = {}
    for base, builtin in ((BUILTIN_DIR, True), (plugins_dir(), False)):
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
            m = _read_manifest(folder, builtin)
            if m and m.id not in found:
                found[m.id] = m
    return found


_modules: dict[str, tuple[float, ModuleType]] = {}


def load(m: Manifest) -> ModuleType:
    """Imports the plugin's code (again if plugin.py changed)."""
    path = m.folder / "plugin.py"
    mtime = path.stat().st_mtime
    cached = _modules.get(m.id)
    if cached and cached[0] == mtime:
        return cached[1]
    name = f"zirahive_plugin_{m.id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"can't load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _modules[m.id] = (mtime, module)
    return module


def settings_for(m: Manifest, saved: dict) -> dict:
    return {s.key: saved.get(s.key, s.default) for s in m.settings}


async def _state(session, pid: str):
    from ..models import PluginState

    return await session.get(PluginState, pid)


async def _record(pid: str, error: str | None) -> None:
    from ..db import sessionmaker
    from ..models import PluginState, utcnow

    async with sessionmaker()() as session:
        st = await session.get(PluginState, pid)
        if st is None:
            return
        if error:
            st.last_error, st.last_error_at = error[:2000], utcnow()
        else:
            st.last_ok_at = utcnow()
        await session.commit()


async def deliver(m: Manifest, saved: dict, event: Event) -> str | None:
    """Gives one plugin one event. Returns the error, if any (it is also saved for Settings)."""
    try:
        module = load(m)
        handler = getattr(module, "on_event", None)
        if handler is None:
            return None
        await asyncio.wait_for(handler(event, Context(m, settings_for(m, saved))), EVENT_TIMEOUT)
        error = None
    except asyncio.TimeoutError:
        error = f"{event.name}: took longer than {EVENT_TIMEOUT} seconds"
    except Exception as exc:  # a plugin's mistake must never break ZiraHive
        error = f"{event.name}: {type(exc).__name__}: {exc}"
        log.warning("plugin %s failed on %s: %s", m.id, event.name, exc)
    await _record(m.id, error)
    return error


_tasks: set[asyncio.Task] = set()


async def emit(name: str, data: dict) -> None:
    """Tells every plugin that is on and wants this event. Returns at once; plugins run in the
    background, so a slow or broken plugin never slows down uploads or scans."""
    from ..db import sessionmaker
    from ..models import PluginState
    from sqlalchemy import select

    try:
        async with sessionmaker()() as session:
            states = {s.id: s for s in (await session.scalars(select(PluginState).where(
                PluginState.enabled.is_(True)))).all()}
    except Exception:  # no database yet (start-up) or a test without one
        return
    if not states:
        return
    event = Event(name, data)
    for pid, m in discover().items():
        st = states.get(pid)
        if st is None or m.error or not (name in m.events or "*" in m.events):
            continue
        task = asyncio.get_running_loop().create_task(deliver(m, json.loads(st.settings_json or "{}"), event))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


async def drain() -> None:
    """Waits for plugins still working (tests, shutdown)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
