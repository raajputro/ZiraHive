from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint, Index, false)
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
        UniqueConstraint("owner_id", "sha256"),
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
