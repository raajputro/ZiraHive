"""Settings in %APPDATA%\\GharBox Sync\\config.json; the sign-in token in Windows Credential Manager."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP = "GharBox Sync"


def app_dir() -> Path:
    base = os.environ.get("GHARBOX_SYNC_HOME") or os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / APP
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Pair:
    local: str    # C:\Users\me\Documents\GharBox
    remote: str   # /PC Sync

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{os.path.normcase(self.local)}|{self.remote}".encode()).hexdigest()[:16]


@dataclass
class Config:
    server: str = ""
    username: str = ""
    language: str = "en"
    interval: int = 60          # seconds between checks
    paused: bool = False
    pairs: list[Pair] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        path = app_dir() / "config.json"
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text("utf-8"))
        data["pairs"] = [Pair(**p) for p in data.get("pairs", [])]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self) -> None:
        path = app_dir() / "config.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(path)


def _account(cfg: Config) -> str:
    return f"{cfg.server}|{cfg.username}"


def save_token(cfg: Config, token: str) -> None:
    try:
        import keyring

        keyring.set_password(APP, _account(cfg), token)
        (app_dir() / "token").unlink(missing_ok=True)
    except Exception:  # no credential store (some Linux setups): a private file instead
        path = app_dir() / "token"
        path.write_text(token, "utf-8")
        path.chmod(0o600)


def load_token(cfg: Config) -> str | None:
    try:
        import keyring

        token = keyring.get_password(APP, _account(cfg))
        if token:
            return token
    except Exception:
        pass
    path = app_dir() / "token"
    return path.read_text("utf-8").strip() if path.is_file() else None


def forget_token(cfg: Config) -> None:
    try:
        import keyring

        keyring.delete_password(APP, _account(cfg))
    except Exception:
        pass
    (app_dir() / "token").unlink(missing_ok=True)
