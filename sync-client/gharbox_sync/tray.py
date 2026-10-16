"""The tray icon (bottom-right of the Windows taskbar) and the first-time set-up window."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from .api import ApiError, SignedOut
from .cli import login, startup, sync_all
from .config import Config, Pair, load_token
from .i18n import set_language, t

log = logging.getLogger("gharbox_sync")


def _icon_image(state: str):
    """A small house-shaped icon, coloured by state: indigo ok, jute syncing, red problem, grey paused."""
    from PIL import Image, ImageDraw

    colour = {"ok": (46, 74, 139), "busy": (201, 166, 107), "error": (179, 38, 30), "paused": (120, 125, 135)}[state]
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(32, 6), (60, 30), (52, 30), (52, 58), (12, 58), (12, 30), (4, 30)], fill=colour)
    d.rectangle([26, 38, 38, 58], fill=(255, 255, 255, 255))
    return im


def setup_window(cfg: Config) -> bool:
    """Server, account and folders, the first time. True when it's ready to sync."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(t("Set up GharBox Sync"))
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=16)
    frm.grid()
    fields: dict[str, tk.StringVar] = {}

    def row(r: int, label: str, key: str, value: str = "", show: str = "") -> ttk.Entry:
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=4)
        fields[key] = tk.StringVar(value=value)
        e = ttk.Entry(frm, textvariable=fields[key], width=44, show=show)
        e.grid(row=r, column=1, sticky="we", pady=4)
        return e

    row(0, t("GharBox address"), "server", cfg.server or "https://gharbox.your-tailnet.ts.net")
    row(1, t("Username"), "user", cfg.username)
    row(2, t("Password"), "password", show="•")
    code_entry = row(3, t("Code from your authenticator app"), "code")
    default_local = str(Path.home() / "GharBox")
    row(4, t("Folder on this PC"), "local", cfg.pairs[0].local if cfg.pairs else default_local)
    ttk.Button(frm, text=t("Choose…"), command=lambda: fields["local"].set(
        filedialog.askdirectory(initialdir=fields["local"].get()) or fields["local"].get())).grid(row=4, column=2, padx=4)
    row(5, t("Folder in GharBox"), "remote", cfg.pairs[0].remote if cfg.pairs else "/PC Sync")
    auto = tk.BooleanVar(value=True)
    ttk.Checkbutton(frm, text=t("Start with Windows"), variable=auto).grid(row=6, column=1, sticky="w", pady=6)
    status = ttk.Label(frm, text="", foreground="#B3261E", wraplength=420)
    status.grid(row=8, column=0, columnspan=3, sticky="w")
    done = {"ok": False}

    def go() -> None:
        status.config(text=t("Signing in…"), foreground="#5D6575")
        root.update()
        cfg.server, cfg.username = fields["server"].get().strip().rstrip("/"), fields["user"].get().strip()
        try:
            asyncio.run(login(cfg, fields["password"].get(), fields["code"].get().strip() or None))
        except ApiError as e:
            status.config(text=str(e), foreground="#B3261E")
            if e.code == "2fa_required":
                code_entry.focus_set()
            return
        except Exception as e:  # wrong address, no network
            status.config(text=f"{e}", foreground="#B3261E")
            return
        local = Path(fields["local"].get()).expanduser()
        local.mkdir(parents=True, exist_ok=True)
        cfg.pairs = [Pair(local=str(local.resolve()), remote="/" + fields["remote"].get().strip().strip("/"))]
        cfg.save()
        if auto.get() and os.name == "nt":
            startup(True)
        done["ok"] = True
        root.destroy()

    ttk.Button(frm, text=t("Start syncing"), command=go).grid(row=7, column=1, sticky="e", pady=8)
    root.mainloop()
    _ = messagebox  # keeps the import for frozen builds
    return done["ok"]


class TrayApp:
    def __init__(self, cfg: Config):
        import pystray

        self.cfg = cfg
        self.state, self.status = "ok", t("Up to date")
        self.wake = threading.Event()
        self.allow_deletions = False
        self.stop = False
        menu = pystray.Menu(
            pystray.MenuItem(lambda _: self.status, None, enabled=False),
            pystray.MenuItem(t("Sync now"), lambda: self.kick(), default=True),
            pystray.MenuItem(t("Sync now, deletions included"), lambda: self.kick(True)),
            pystray.MenuItem(lambda _: t("Resume") if cfg.paused else t("Pause"), lambda: self.toggle()),
            pystray.MenuItem(t("Open the folder"), lambda: self.open_folder()),
            pystray.MenuItem(t("Open GharBox"), lambda: webbrowser.open(cfg.server + "/files")),
            pystray.MenuItem(t("Quit"), lambda: self.quit()),
        )
        self.icon = pystray.Icon("gharbox-sync", _icon_image("ok"), t("GharBox Sync"), menu)

    def set(self, state: str, status: str) -> None:
        self.state, self.status = state, status
        self.icon.icon = _icon_image(state)
        self.icon.title = f"{t('GharBox Sync')}: {status}"
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def notify(self, text: str) -> None:
        try:
            self.icon.notify(text, t("GharBox Sync"))
        except Exception:
            pass

    def kick(self, deletions: bool = False) -> None:
        self.allow_deletions = deletions
        self.wake.set()

    def toggle(self) -> None:
        self.cfg.paused = not self.cfg.paused
        self.cfg.save()
        self.set("paused" if self.cfg.paused else "ok", t("Paused") if self.cfg.paused else t("Up to date"))
        self.wake.set()

    def open_folder(self) -> None:
        if self.cfg.pairs:
            path = self.cfg.pairs[0].local
            if os.name == "nt":
                os.startfile(path)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])

    def quit(self) -> None:
        self.stop = True
        self.wake.set()
        self.icon.stop()

    def loop(self) -> None:
        while not self.stop:
            if not self.cfg.paused:
                self.set("busy", t("Syncing…"))
                try:
                    results = asyncio.run(sync_all(self.cfg, self.allow_deletions))
                    self.allow_deletions = False
                    stopped = [r.stopped for _, r in results if r.stopped]
                    changes = sum(r.changes for _, r in results)
                    for _, r in results:
                        for name in r.conflicts:
                            self.notify(t("Kept both copies of {name}: it changed on the PC and in GharBox.", name=name))
                    if stopped:
                        self.set("error", stopped[0][:120])
                        self.notify(stopped[0])
                    else:
                        if changes:
                            self.notify(t("{n} files synced", n=changes))
                        self.set("ok", t("Last synced {time}", time=datetime.now().strftime("%H:%M")))
                except SignedOut:
                    self.set("error", t("Sign in again: {server}", server=self.cfg.server))
                    self.notify(self.status)
                except Exception as exc:
                    log.warning("sync failed: %s", exc)
                    self.set("error", t("Can't reach GharBox. Trying again soon."))
            self.wake.wait(self.cfg.interval)
            self.wake.clear()


def run_tray() -> None:
    cfg = Config.load()
    set_language(cfg.language)
    if not cfg.server or not cfg.pairs or not load_token(cfg):
        if not setup_window(cfg):
            sys.exit(0)
        set_language(cfg.language)
    app = TrayApp(cfg)
    threading.Thread(target=app.loop, daemon=True).start()
    app.icon.run()
