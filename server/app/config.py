from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="GHARBOX_", extra="ignore")

    # Where GharBox keeps everything it owns: backups, thumbnails, upload scratch, secrets.
    data_dir: Path = Path("./data")
    database_url: str = ""  # empty -> SQLite file inside data_dir
    redis_url: str = ""  # empty -> background jobs run in-process

    secret_key: str = ""  # empty -> generated once and stored in data_dir
    access_token_days: int = 30

    # Media libraries created on first start, "Name:/path[:kind],Name2:/path2"
    media_libraries: str = ""
    tmdb_api_key: str = ""

    max_chunk_mb: int = 64
    cors_origins: str = "http://localhost:5173"

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+aiosqlite:///{(self.data_dir / 'gharbox.db').resolve()}"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.storage_dir, self.cache_dir / "thumbs",
                  self.cache_dir / "posters", self.upload_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_secret(self) -> str:
        if self.secret_key:
            return self.secret_key
        path = self.data_dir / ".secret_key"
        if path.exists():
            return path.read_text().strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        path.write_text(key)
        return key

    def parsed_libraries(self) -> list[tuple[str, str, str]]:
        out = []
        for part in filter(None, (p.strip() for p in self.media_libraries.split(","))):
            name, _, rest = part.partition(":")
            path, kind = rest, "movies"
            # allow an optional ":kind" suffix, but keep Windows-like "C:/x" intact
            if rest.rsplit(":", 1)[-1] in ("movies", "shows", "videos"):
                path, kind = rest.rsplit(":", 1)
            if name and path:
                out.append((name.strip(), path.strip(), kind))
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
