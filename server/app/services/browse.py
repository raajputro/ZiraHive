"""Folders the admin may pick as categories: the media folder and the drives Docker mounted
(read-only) under /drives. Nothing outside them can become a category, so ZiraHive's own data
and the server's system files can never be shown to family members as "media"."""
from __future__ import annotations

import os
import re
import string
from pathlib import Path, PurePosixPath

from ..config import get_settings

NO_DRIVE_MARK = ".zirahive-no-drive"  # inside the placeholder folder used for drives not in .env
DATA_MARK = ".zirahive-data"          # inside ZiraHive's own data folder (see Settings.ensure_dirs)
_OLD_MARKS = {DATA_MARK: ".gharbox-data", NO_DRIVE_MARK: ".gharbox-no-drive"}  # from before the rename


def marked(folder: Path, mark: str = DATA_MARK) -> bool:
    """True when the folder carries the mark (under the new or the old name)."""
    return (folder / mark).exists() or (folder / _OLD_MARKS[mark]).exists()


def is_private(path: Path) -> bool:
    """True inside ZiraHive's data folder (also when reached through a drive mount)."""
    for d in (path, *path.parents):
        try:
            if marked(d):
                return True
        except OSError:
            return False
    return False


def walk_filter(dirpath: str, dirnames: list[str]) -> list[str]:
    """For os.walk: leave out hidden folders and ZiraHive's own data folder."""
    base = Path(dirpath)
    return [d for d in dirnames if not d.startswith(".") and not marked(base / d)]
_SKIP = re.compile(r"^(\$recycle\.bin|system volume information|\$windows\..*|windows|program files.*|programdata|"
                   r"recovery|config\.msi|msocache|appdata|node_modules|\..*)$", re.I)


def roots() -> list[tuple[Path, str]]:
    """(path, label) for every place folders can be picked from."""
    s = get_settings()
    out: list[tuple[Path, str]] = []
    if s.media_root and Path(s.media_root).is_dir():
        out.append((Path(s.media_root), display(s.media_root) if s.media_host_path else "Media folder"))
    drives = Path(s.drives_dir)
    if drives.is_dir():
        for d in sorted(drives.iterdir()):
            if d.is_dir() and len(d.name) == 1 and not marked(d, NO_DRIVE_MARK):
                try:
                    next(d.iterdir(), None)
                except OSError:
                    continue
                out.append((d, f"{d.name.upper()}:"))
    if os.name == "nt":  # ZiraHive running straight on Windows, without Docker
        for letter in string.ascii_uppercase:
            p = Path(f"{letter}:\\")
            if p.exists():
                out.append((p, f"{letter}:"))
    for _name, path, _kind in s.parsed_libraries():
        p = Path(path)
        if p.is_dir() and all(p != r for r, _ in out):
            out.append((p, path))
    return out


def allowed(path: str | Path) -> Path | None:
    """The folder as picked (tidied, e.g. /drives/e/Movies), if it really lies inside one of the
    roots; links and ../ are followed for the check, so they can't lead anywhere else."""
    try:
        picked = Path(os.path.abspath(path))
        real = picked.resolve()
    except (OSError, RuntimeError):
        return None
    if is_private(real) or is_private(picked):
        return None
    for root, _ in roots():
        r = root.resolve()
        if (real == r or r in real.parents) and (picked == root or root in picked.parents or picked == r or r in picked.parents):
            return picked
    return None


def display(path: str | Path) -> str:
    """/drives/e/Movies/English -> E:\\Movies\\English (how it looks on the PC)."""
    s = get_settings()
    p = PurePosixPath(str(path).replace("\\", "/"))
    if s.media_root and s.media_host_path:
        try:
            rel = p.relative_to(PurePosixPath(s.media_root))
            host = s.media_host_path.replace("/", "\\").rstrip("\\")
            return "\\".join([host, *rel.parts])
        except ValueError:
            pass
    drives = PurePosixPath(s.drives_dir)
    try:
        rel = p.relative_to(drives)
    except ValueError:
        return str(path)
    parts = rel.parts
    if not parts:
        return str(path)
    return f"{parts[0].upper()}:\\" + "\\".join(parts[1:])


def same_folder_key(path: str | Path) -> str:
    """One key per real folder on the PC, however ZiraHive reaches it. With Docker, G:\\Media is
    mounted twice (as the media folder /media and inside the drive /drives/g), so
    /media/English Movies and /drives/g/Media/English Movies get the same key. Windows paths
    ignore case, so the key does too."""
    return display(path).replace("/", "\\").rstrip("\\").lower()


def preferred(path: str | Path) -> str:
    """The media-folder spelling of a folder that lies inside the media folder but was reached
    through a drive (/drives/g/Media/English Movies -> /media/English Movies), so a category is
    always stored the way automatic discovery would store it. Any other folder is returned as is."""
    s = get_settings()
    if not (s.media_root and s.media_host_path):
        return str(path)
    host = display(path).replace("/", "\\").rstrip("\\")
    media_host = s.media_host_path.replace("/", "\\").rstrip("\\")
    if host.lower() == media_host.lower():
        return str(PurePosixPath(s.media_root))
    if host.lower().startswith(media_host.lower() + "\\"):
        rest = [p for p in host[len(media_host) + 1:].split("\\") if p]
        return str(PurePosixPath(s.media_root, *rest))
    return str(path)


def list_folder(path: Path) -> list[Path]:
    try:
        children = [c for c in path.iterdir() if not _SKIP.match(c.name) and not marked(c)]
    except OSError:
        return []
    out = []
    for c in children:
        try:
            if c.is_dir():
                out.append(c)
        except OSError:
            continue
    return sorted(out, key=lambda c: c.name.lower())[:3000]
