from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint, Index, false, true)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    quota_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # bumped on password change / sign out everywhere, which invalidates older tokens
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    ntfy_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # push notifications
    # Kids' profiles: only titles rated for this age or younger are shown. None = no limit.
    max_age: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Folder(Base):
    """Explicit folders, so empty folders survive. Paths look like '/Documents/Tax'."""

    __tablename__ = "folders"
    __table_args__ = (UniqueConstraint("owner_id", "path"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Asset(Base):
    """A backed-up file: photo, video, document or anything else."""

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_owner_sha", "owner_id", "sha256"),
        Index("ix_assets_owner_folder", "owner_id", "folder"),
        Index("ix_assets_owner_taken", "owner_id", "taken_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    folder: Mapped[str] = mapped_column(String(1024), default="/")
    filename: Mapped[str] = mapped_column(String(512))
    size: Mapped[int] = mapped_column(BigInteger)
    mime: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    kind: Mapped[str] = mapped_column(String(16), default="other")  # photo|video|document|other
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)  # relative to storage_dir
    thumb_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UploadSession(Base):
    """A resumable upload in progress. Bytes live in data/uploads/<id>.part."""

    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    folder: Mapped[str] = mapped_column(String(1024), default="/")
    size: Mapped[int] = mapped_column(BigInteger)
    offset: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dedupe: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class Library(Base):
    """One category on the Watch page, e.g. 'English Movies' or 'Web Series'.

    kind: movies = every file is a movie; shows = every file is an episode;
          mixed = files named like S01E02 are episodes, the rest are movies (good for Animation).
    """

    __tablename__ = "libraries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128))
    path: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="movies")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Default age rating for titles here that have none of their own (e.g. Animation = 7)
    age_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Series(Base):
    """A web series / TV show inside a library. Its episodes are MediaItems."""

    __tablename__ = "series"
    __table_args__ = (UniqueConstraint("library_id", "key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(512))  # normalised title, for matching
    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_ready: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    certification: Mapped[str | None] = mapped_column(String(16), nullable=True)  # from TMDB
    age_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # admin's choice
    # Skip-intro markers that apply to every episode (seconds); credits = seconds before the end
    intro_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    intro_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    credits_before_end: Mapped[float | None] = mapped_column(Float, nullable=True)


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (UniqueConstraint("library_id", "rel_path"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), index=True)
    rel_path: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0)
    container: Mapped[str | None] = mapped_column(String(32), nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    poster_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # set when this file is an episode of a series
    series_id: Mapped[str | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), nullable=True, index=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # audio / subtitle tracks and chapters found by ffprobe (JSON)
    tracks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # markers found in the file's chapters (seconds)
    intro_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    intro_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    credits_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    certification: Mapped[str | None] = mapped_column(String(16), nullable=True)
    age_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WatchProgress(Base):
    __tablename__ = "watch_progress"
    __table_args__ = (UniqueConstraint("user_id", "media_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_items.id", ondelete="CASCADE"))
    position: Mapped[float] = mapped_column(Float, default=0)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RecoveryCode(Base):
    """Single-use codes for signing in when the authenticator phone is lost."""

    __tablename__ = "recovery_codes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssetVersion(Base):
    """An older copy of a document. The newest copy is always the Asset itself."""

    __tablename__ = "asset_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShareLink(Base):
    """A link anyone can open, for one file, a folder or an album."""

    __tablename__ = "share_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(16))  # asset | folder | album
    target_id: Mapped[str] = mapped_column(String(1024))  # asset id, folder path or album id
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    allow_download: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(256))
    cover_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlbumItem(Base):
    __tablename__ = "album_items"
    __table_args__ = (UniqueConstraint("album_id", "asset_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    added_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlbumMember(Base):
    """Family members an album is shared with. can_add lets them add their own photos."""

    __tablename__ = "album_members"
    __table_args__ = (UniqueConstraint("album_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    album_id: Mapped[str] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    can_add: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)  # kept if user is deleted
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OfflineCopy(Base):
    """A smaller MP4 of a movie or episode, made to download and watch without internet."""

    __tablename__ = "offline_copies"
    __table_args__ = (UniqueConstraint("media_id", "quality"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_items.id", ondelete="CASCADE"), index=True)
    quality: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|working|ready|failed
    progress: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
