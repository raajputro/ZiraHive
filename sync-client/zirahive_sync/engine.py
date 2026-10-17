"""Two-way sync of one PC folder with one ZiraHive folder.

For every file it compares three things: the PC now, ZiraHive now, and what both were at the
end of the last sync (kept in a small database). That tells an edit from a deletion:

  changed on the PC only        -> upload (ZiraHive keeps the old copy as a version)
  changed in ZiraHive only       -> download
  deleted on the PC only        -> move to the ZiraHive trash (30 days to get it back)
  deleted in ZiraHive only       -> move to the Windows Recycle Bin
  changed on both, differently  -> keep both: the PC copy is renamed "name (PC copy, date).ext"

Safety: if the PC folder is missing (drive unplugged), nothing happens. If one run would delete
more than half of the files, it stops and asks instead.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from .api import Api
from .config import Pair, app_dir

log = logging.getLogger("zirahive_sync")

IGNORE = re.compile(r"^(desktop\.ini|thumbs\.db|\.ds_store|~\$.*|.*\.tmp|.*\.partial|\.zirahive-sync-.*|.*\.crdownload)$", re.I)
_BAD = re.compile(r'[<>:"\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
SETTLE_SECONDS = 2.0      # skip files still being written
MASS_DELETE = 0.5         # stop if a run would delete more than this share of the files


def server_name(name: str) -> str:
    """The name ZiraHive will store (same rules as the server)."""
    name = _BAD.sub("_", name.replace("/", "_")).strip().strip(".")
    if not name or name.split(".")[0].lower() in _RESERVED:
        name = f"_{name or 'file'}"
    return name[:200]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class State:
    """What both sides looked like after the last sync, per file."""

    def __init__(self, pair: Pair):
        self.db = sqlite3.connect(app_dir() / f"state-{pair.key}.db")
        self.db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, sha TEXT, size INTEGER, "
                        "mtime REAL, remote_id TEXT)")
        self.db.commit()

    def all(self) -> dict[str, tuple[str, int, float, str]]:
        return {r[0]: r[1:] for r in self.db.execute("SELECT path, sha, size, mtime, remote_id FROM files")}

    def put(self, path: str, sha: str, size: int, mtime: float, remote_id: str | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?)", (path, sha, size, mtime, remote_id))

    def drop(self, path: str) -> None:
        self.db.execute("DELETE FROM files WHERE path = ?", (path,))

    def commit(self) -> None:
        self.db.commit()

    def close(self) -> None:
        self.db.close()


@dataclass
class Report:
    uploaded: list[str] = field(default_factory=list)
    downloaded: list[str] = field(default_factory=list)
    trashed_remote: list[str] = field(default_factory=list)
    trashed_local: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stopped: str | None = None

    @property
    def changes(self) -> int:
        return len(self.uploaded) + len(self.downloaded) + len(self.trashed_remote) + len(self.trashed_local)


def scan_local(root: Path, report: Report) -> dict[str, os.stat_result]:
    found: dict[str, os.stat_result] = {}
    now = time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and server_name(d) == d]
        for fn in filenames:
            if IGNORE.match(fn) or fn.startswith("."):
                continue
            p = Path(dirpath) / fn
            rel = PurePosixPath(*p.relative_to(root).parts).as_posix()
            if server_name(fn) != fn:
                report.skipped.append(f"{rel} (ZiraHive can't keep this name)")
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if p.is_symlink() or now - st.st_mtime < SETTLE_SECONDS:
                continue
            found[rel] = st
    return found


def trash_local(path: Path) -> None:
    """To the Recycle Bin, so a deletion from ZiraHive can be undone on the PC too."""
    try:
        from send2trash import send2trash

        send2trash(str(path))
    except Exception:
        dest = app_dir() / "Removed files" / datetime.now().strftime("%Y-%m-%d") / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))


def conflict_name(rel: str) -> str:
    p = PurePosixPath(rel)
    stamp = datetime.now().strftime("%Y-%m-%d %H.%M")
    return str(p.with_name(f"{p.stem} (PC copy {stamp}){p.suffix}"))


async def sync_pair(api: Api, pair: Pair, state: State | None = None) -> Report:
    report = Report()
    root = Path(pair.local)
    if not root.is_dir():
        report.stopped = f"The folder {root} isn't there (is the drive connected?). Nothing was changed."
        return report
    own_state = state is None
    state = state or State(pair)
    try:
        await _sync(api, pair, root, state, report)
    finally:
        state.commit()
        if own_state:
            state.close()
    return report


async def _sync(api: Api, pair: Pair, root: Path, state: State, report: Report) -> None:
    remote_root = pair.remote if pair.remote.startswith("/") else "/" + pair.remote
    tree = await api.tree(remote_root)
    remote = {f["path"]: f for f in tree["files"]}
    local = scan_local(root, report)
    saved = state.all()

    def folder_of(rel: str) -> str:
        parent = str(PurePosixPath(rel).parent)
        return remote_root.rstrip("/") + ("" if parent == "." else "/" + parent) or "/"

    def local_sha(rel: str) -> str | None:
        st = local.get(rel)
        if st is None:
            return None
        s = saved.get(rel)
        if s and s[1] == st.st_size and abs(s[2] - st.st_mtime) < 0.001:
            return s[0]  # unchanged since last time: no need to read it again
        return sha256_of(root / rel)

    # empty folders: make them on the other side too
    for f in tree["folders"]:
        (root / f).mkdir(parents=True, exist_ok=True)
    known = set(tree["folders"])
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and server_name(d) == d]
        for d in dirnames:
            rel = PurePosixPath(*(Path(dirpath) / d).relative_to(root).parts).as_posix()
            if rel not in known:
                await api.make_folder(remote_root.rstrip("/") + "/" + rel)

    plan = []
    for rel in sorted(set(local) | set(remote) | set(saved)):
        try:
            lsha, r = local_sha(rel), remote.get(rel)
        except OSError as exc:  # locked by another program; next time
            report.skipped.append(f"{rel} ({exc.strerror or exc})")
            continue
        rsha = r["sha256"] if r else None
        ssha = saved[rel][0] if rel in saved else None
        plan.append((rel, lsha, rsha, ssha, r))

    deletions = sum(1 for _, l, rs, s, _ in plan if s and ((l is None and rs == s) or (rs is None and l == s)))
    if deletions > 3 and deletions > MASS_DELETE * max(1, len(saved)) and not getattr(api, "allow_mass_delete", False):
        report.stopped = (f"This run would delete {deletions} of {len(saved)} files, so it was paused to be safe. "
                          f"If that's what you want, choose \"Sync now, deletions included\".")
        return

    for rel, lsha, rsha, ssha, r in plan:
        try:
            await _one(api, root, rel, lsha, rsha, ssha, r, local, state, report, folder_of)
        except Exception as exc:
            if exc.__class__.__name__ == "SignedOut":
                raise
            log.warning("%s: %s", rel, exc)
            report.errors.append(f"{rel}: {exc}")


async def _one(api, root, rel, lsha, rsha, ssha, r, local, state, report, folder_of) -> None:
    path = root / rel

    def remember(sha: str, remote_id: str | None) -> None:
        st = path.stat()
        state.put(rel, sha, st.st_size, st.st_mtime, remote_id)

    async def upload() -> None:
        asset = await api.upload(path, folder_of(rel), path.name, lsha)
        remember(lsha, asset["id"])
        report.uploaded.append(rel)

    async def download() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        await api.download(r["id"], path)
        remember(rsha, r["id"])
        report.downloaded.append(rel)

    if lsha == rsha:
        if lsha is None:
            state.drop(rel)
        else:
            remember(lsha, r["id"])
        return
    local_changed, remote_changed = lsha != ssha, rsha != ssha
    if local_changed and not remote_changed:
        if lsha is None:
            await api.trash(r["id"])
            state.drop(rel)
            report.trashed_remote.append(rel)
        else:
            await upload()
    elif remote_changed and not local_changed:
        if rsha is None:
            trash_local(path)
            state.drop(rel)
            report.trashed_local.append(rel)
        else:
            await download()
    elif lsha is None:
        await download()
    elif rsha is None:
        await upload()
    else:
        # changed on both sides: keep both, nothing is lost
        copy_rel = conflict_name(rel)
        copy = root / copy_rel
        os.replace(path, copy)
        asset = await api.upload(copy, folder_of(copy_rel), copy.name, lsha)
        st = copy.stat()
        state.put(copy_rel, lsha, st.st_size, st.st_mtime, asset["id"])
        await download()
        report.downloaded.pop()
        report.conflicts.append(rel)
