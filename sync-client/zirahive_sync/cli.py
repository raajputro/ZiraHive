"""zirahive-sync: command line, and the tray app when started with no arguments.

  zirahive-sync                       tray icon (first time: a small set-up window)
  zirahive-sync login --server URL --user NAME
  zirahive-sync add LOCAL_FOLDER /Folder/In/ZiraHive
  zirahive-sync once [--allow-deletions]
  zirahive-sync run                   keep syncing in this window
  zirahive-sync startup on|off        start with Windows
  zirahive-sync status
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__
from .api import Api, ApiError, SignedOut, dlna_fetcher
from .config import Config, Pair, app_dir, load_token, save_token
from .engine import Report, sync_pair


def describe(pair: Pair, r: Report) -> str:
    parts = [f"{pair.local} <-> {pair.remote}:"]
    for label, items in (("uploaded", r.uploaded), ("downloaded", r.downloaded), ("moved to ZiraHive trash", r.trashed_remote),
                         ("moved to Recycle Bin", r.trashed_local), ("kept both copies", r.conflicts),
                         ("skipped", r.skipped), ("errors", r.errors)):
        if items:
            parts.append(f"  {label}: {len(items)}")
            parts += [f"    {x}" for x in items[:20]]
    if r.stopped:
        parts.append(f"  stopped: {r.stopped}")
    if len(parts) == 1:
        parts.append("  up to date")
    return "\n".join(parts)


async def sync_all(cfg: Config, allow_deletions: bool = False) -> list[tuple[Pair, Report]]:
    api = Api(cfg.server, load_token(cfg))
    api.allow_mass_delete = allow_deletions
    try:
        await api.configure()
        return [(p, await sync_pair(api, p)) for p in cfg.pairs]
    finally:
        await api.close()


async def login(cfg: Config, password: str, code: str | None = None) -> None:
    api = Api(cfg.server)
    try:
        token = await api.login(cfg.username, password, code)
        cfg.language = (await api.me()).get("language") or cfg.language
    finally:
        await api.close()
    save_token(cfg, token)
    cfg.save()


def startup(on: bool) -> Path:
    """A small launcher in the Startup folder (Windows) so syncing starts after sign-in."""
    folder = Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    launcher = folder / "ZiraHive Sync.cmd"
    if on:
        folder.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):  # the ZiraHiveSync.exe build
            command = f'"{sys.executable}" tray'
        else:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            command = f'"{pythonw if pythonw.exists() else sys.executable}" -m zirahive_sync tray'
        launcher.write_text(f'@echo off\r\nstart "" {command}\r\n', "utf-8")
    else:
        launcher.unlink(missing_ok=True)
    return launcher


def tv_server(cfg: Config):
    """The DLNA server that shows ZiraHive on TVs, as the signed-in account (not started)."""
    import socket
    import uuid

    from .dlna import DlnaServer

    if not cfg.device_id:
        cfg.device_id = str(uuid.uuid4())
        cfg.save()
    name = f"ZiraHive ({socket.gethostname()})"
    return DlnaServer(name, cfg.device_id, cfg.server, dlna_fetcher(cfg.server, load_token(cfg) or ""))


def main(argv: list[str] | None = None) -> None:
    if sys.stdout is None or sys.stderr is None:  # the windowed .exe has no console window
        out = open(app_dir() / "output.log", "a", encoding="utf-8")  # noqa: SIM115
        sys.stdout, sys.stderr = sys.stdout or out, sys.stderr or out
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(app_dir() / "sync.log", encoding="utf-8"), logging.StreamHandler()])
    ap = argparse.ArgumentParser(prog="zirahive-sync", description="Keep a PC folder and a ZiraHive folder the same.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("login")
    p.add_argument("--server", required=True)
    p.add_argument("--user", required=True)
    p = sub.add_parser("add")
    p.add_argument("local")
    p.add_argument("remote")
    p = sub.add_parser("remove")
    p.add_argument("local")
    p = sub.add_parser("once")
    p.add_argument("--allow-deletions", action="store_true")
    sub.add_parser("run")
    sub.add_parser("status")
    sub.add_parser("tray")
    sub.add_parser("tv", help="show ZiraHive on smart TVs at home (DLNA) until stopped")
    p = sub.add_parser("startup")
    p.add_argument("state", choices=["on", "off"])
    args = ap.parse_args(argv)
    cfg = Config.load()

    if args.cmd in (None, "tray"):
        from .tray import run_tray

        run_tray()
    elif args.cmd == "login":
        cfg.server, cfg.username = args.server.rstrip("/"), args.user
        password = getpass.getpass("Password: ")
        try:
            asyncio.run(login(cfg, password))
        except ApiError as e:
            if e.code != "2fa_required":
                sys.exit(f"Couldn't sign in: {e}")
            asyncio.run(login(cfg, password, input("Code from your authenticator app: ").strip()))
        print(f"Signed in to {cfg.server} as {cfg.username}.")
    elif args.cmd == "add":
        local = str(Path(args.local).expanduser().resolve())
        Path(local).mkdir(parents=True, exist_ok=True)
        cfg.pairs = [p for p in cfg.pairs if os.path.normcase(p.local) != os.path.normcase(local)]
        cfg.pairs.append(Pair(local=local, remote="/" + args.remote.strip("/")))
        cfg.save()
        print(f"Syncing {local} with {cfg.pairs[-1].remote}.")
    elif args.cmd == "remove":
        local = os.path.normcase(str(Path(args.local).expanduser().resolve()))
        cfg.pairs = [p for p in cfg.pairs if os.path.normcase(p.local) != local]
        cfg.save()
    elif args.cmd == "status":
        print(f"Server: {cfg.server or '(not signed in)'} as {cfg.username}")
        for p in cfg.pairs:
            print(f"  {p.local} <-> {p.remote}")
    elif args.cmd in ("once", "run"):
        if not cfg.server or not load_token(cfg):
            sys.exit("Sign in first: zirahive-sync login --server https://... --user NAME")
        while True:
            try:
                for pair, report in asyncio.run(sync_all(cfg, getattr(args, "allow_deletions", False))):
                    print(describe(pair, report))
            except SignedOut:
                sys.exit("ZiraHive signed this PC out. Run zirahive-sync login again.")
            except Exception as exc:  # network down, server restarting: try again later
                logging.warning("sync failed: %s", exc)
            if args.cmd == "once":
                break
            time.sleep(cfg.interval)
    elif args.cmd == "tv":
        if not cfg.server or not load_token(cfg):
            sys.exit("Sign in first: zirahive-sync login --server https://... --user NAME")
        server = tv_server(cfg)
        server.start()
        print(f"TVs at home can now find \"{server.name}\" (as {cfg.username}). Ctrl+C stops it.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            server.stop()
    elif args.cmd == "startup":
        print(startup(args.state == "on"))


if __name__ == "__main__":
    main()
