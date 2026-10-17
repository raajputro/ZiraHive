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

    # Every top-level folder in here becomes a category on the Watch page
    # (e.g. /media/English Movies, /media/Web Series). Docker mounts MEDIA_PATH here.
    media_root: str = ""
    media_host_path: str = ""
    ice_servers: str = ""
    server_name: str = ""  # how linked GharBox servers see this one, e.g. "Mahbub's GharBox"  # voice chat: extra STUN servers, comma separated  # the media folder as Windows sees it (G:/Media), for showing paths
    # Extra libraries outside media_root: "Name:/path[:kind],Name2:/path2"
    media_libraries: str = ""
    # Your drives, mounted read-only by Docker as /drives/c, /drives/d, ... (DRIVE_D=D:/ in .env).
    # Settings > Server lets the admin pick any folder on them as a category, where it is.
    drives_dir: str = "/drives"
    tmdb_api_key: str = ""

    # The public address of the share-link gateway, used when making share links, e.g.
    # https://gharbox.tail1234.ts.net:8443  (empty: links use whatever address you're on)
    public_url: str = ""
    # Secure cookies: "auto" = when the request came over HTTPS; "true" / "false" to force
    secure_cookies: str = "auto"
    api_docs: bool = False  # the interactive /docs page; leave off on anything reachable remotely

    max_chunk_mb: int = 64
    cors_origins: str = "http://localhost:5173"

    # Video encoding: "auto" uses an NVIDIA GPU when one works in the container, else the CPU.
    # "nvenc" or "none" force it.
    hw_accel: str = "auto"
    max_transcodes: int = 3  # films converting at the same time
    offline_days: int = 14  # offline copies unused this long are deleted

    # Reading text in files so Files can search inside them (Tesseract, Bangla + English):
    #   documents = PDFs, Word and text files, scans and screenshots;  all = every photo too;  off
    ocr: str = "documents"
    ocr_languages: str = "ben+eng"
    lan_url: str = ""  # e.g. http://192.168.0.105:8080: how TVs and Chromecasts reach GharBox

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
        # Marks this folder as GharBox's own (people's files, the vault, the database), so it is
        # never offered or scanned as media, even when the drive it's on is shared with GharBox.
        mark = self.data_dir / ".gharbox-data"
        if not mark.exists():
            mark.write_text("GharBox's own data. Never shown as media.\n")

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
            if rest.rsplit(":", 1)[-1] in ("movies", "shows", "mixed", "music", "audiobooks", "books", "comics"):
                path, kind = rest.rsplit(":", 1)
            if name and path:
                out.append((name.strip(), path.strip(), kind))
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
