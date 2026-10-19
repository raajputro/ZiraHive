from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String,
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
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "en" or "bn"; None = the browser's
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
    # Photo clean-up (no AI needed): a 64-bit picture fingerprint and how sharp it is
    phash: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    sharpness: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    # sync client: a file with this name in this folder gets new contents (old one kept as a version)
    replace: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


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
    # AI subtitles: None, "queued", "working", "done:<language>" or "failed:<reason>"
    ai_subtitles: Mapped[str | None] = mapped_column(String(300), nullable=True)


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


class WatchParty(Base):
    """Watching a movie or episode together, now or at a set time."""

    __tablename__ = "watch_parties"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    host_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_items.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(256))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # who may press play/pause/seek: "host" or "everyone"
    control: Mapped[str] = mapped_column(String(16), default="everyone", server_default="everyone")
    # pause everyone while someone's video is loading
    wait_for_all: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_notice_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # last known playback state, so a party survives a server restart
    position: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartyMember(Base):
    __tablename__ = "party_members"
    __table_args__ = (UniqueConstraint("party_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    party_id: Mapped[str] = mapped_column(ForeignKey("watch_parties.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rsvp: Mapped[str] = mapped_column(String(16), default="invited")  # invited | going | declined


class PartyMessage(Base):
    __tablename__ = "party_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    party_id: Mapped[str] = mapped_column(ForeignKey("watch_parties.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ------------------------------------------------------------------ music

class MusicAlbum(Base):
    """One album: the tracks in one folder that share an album name."""

    __tablename__ = "music_albums"
    __table_args__ = (UniqueConstraint("library_id", "key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(1024))  # folder + album name, for matching on rescans
    title: Mapped[str] = mapped_column(String(512))
    artist: Mapped[str] = mapped_column(String(512), default="Unknown artist")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cover_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (UniqueConstraint("library_id", "rel_path"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), index=True)
    album_id: Mapped[str | None] = mapped_column(
        ForeignKey("music_albums.id", ondelete="SET NULL"), nullable=True, index=True)
    rel_path: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(512))
    artist: Mapped[str | None] = mapped_column(String(512), nullable=True)
    album_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    track_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    codec: Mapped[str | None] = mapped_column(String(32), nullable=True)
    playable: Mapped[bool] = mapped_column(Boolean, default=True)  # browsers can play it as it is
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Set by the duplicate-song check (services/music_audit.py): this file is another copy of that
    # track, so it's left out of Listen. dup_moved: the file was moved to .zirahive-duplicates.
    # dup_kept: someone chose to keep it, so the check leaves it alone from then on.
    duplicate_of: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    dup_moved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    dup_kept: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # A Quran recitation: in a Quran category, or in a Quran-named folder inside a music category.
    # Recitations are only ever shown in Quran & Namaz, never among songs.
    quran: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


def track_shown():
    """Audio files to list: on disk and not a duplicate copy."""
    from sqlalchemy import and_
    return and_(Track.missing.is_(False), Track.duplicate_of.is_(None))


def song_shown():
    """Songs (Listen): shown, and not a Quran recitation."""
    from sqlalchemy import and_
    return and_(track_shown(), Track.quran.is_(False))


class TrackStat(Base):
    """Per person: favourite, play count, last played."""

    __tablename__ = "track_stats"
    __table_args__ = (UniqueConstraint("user_id", "track_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    plays: Mapped[int] = mapped_column(Integer, default=0)
    last_played: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)


# ------------------------------------------------------- audiobooks, ebooks, comics

class Book(Base):
    """An audiobook (one file or a folder of parts), an ebook (EPUB, PDF) or a comic
    (CBZ, CBR, CB7, CBT, or a folder of page images)."""

    __tablename__ = "books"
    __table_args__ = (UniqueConstraint("library_id", "rel_path"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    library_id: Mapped[str] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), index=True)
    rel_path: Mapped[str] = mapped_column(Text)  # the file, or the folder for multi-part books
    kind: Mapped[str] = mapped_column(String(16))  # audiobook | ebook | comic
    format: Mapped[str] = mapped_column(String(16))  # epub pdf cbz cbr cb7 cbt images audio
    title: Mapped[str] = mapped_column(String(512))
    author: Mapped[str | None] = mapped_column(String(512), nullable=True)
    narrator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    series_name: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    series_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)  # audiobooks
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)  # comics and PDFs
    # audiobooks: [{"rel": ..., "duration": ..., "playable": bool}]; comics: page entry names
    parts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapters_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # [{"title", "start"}]
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BookProgress(Base):
    __tablename__ = "book_progress"
    __table_args__ = (UniqueConstraint("user_id", "book_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    position: Mapped[float] = mapped_column(Float, default=0)  # seconds, or page number
    locator: Mapped[str | None] = mapped_column(Text, nullable=True)  # EPUB location (CFI)
    fraction: Mapped[float] = mapped_column(Float, default=0)  # 0..1
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ------------------------------------------------------------------ vault

class Vault(Base):
    """End-to-end encrypted space. The server only keeps the master key wrapped (encrypted) with
    the person's vault passphrase and with their recovery key; it can never open it."""

    __tablename__ = "vaults"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    kdf: Mapped[str] = mapped_column(String(32), default="pbkdf2-sha256")
    salt: Mapped[str] = mapped_column(String(64))
    iterations: Mapped[int] = mapped_column(Integer)
    wrapped_key: Mapped[str] = mapped_column(Text)           # master key, by the passphrase
    recovery_wrapped_key: Mapped[str] = mapped_column(Text)  # master key, by the recovery key
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VaultItem(Base):
    """One encrypted file. Name, type and dates are inside `meta`, encrypted too."""

    __tablename__ = "vault_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    size: Mapped[int] = mapped_column(BigInteger)          # encrypted size
    received: Mapped[int] = mapped_column(BigInteger, default=0)
    chunk_size: Mapped[int] = mapped_column(Integer)       # plaintext bytes per encrypted chunk
    wrapped_key: Mapped[str] = mapped_column(Text)         # file key + nonce, by the master key
    meta: Mapped[str] = mapped_column(Text)                # encrypted JSON
    has_thumb: Mapped[bool] = mapped_column(Boolean, default=False)
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ------------------------------------------------------------------ offsite backup

class BackupConfig(Base):
    """Where the encrypted offsite backup goes (one row). restic encrypts everything with
    `password` before it leaves this PC; the storage provider only ever sees ciphertext."""

    __tablename__ = "backup_config"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="main")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    repository: Mapped[str] = mapped_column(Text)       # /backup-disk/zirahive, s3:..., sftp:..., rclone:...
    password: Mapped[str] = mapped_column(Text)         # restic repository password
    env_json: Mapped[str] = mapped_column(Text, default="{}")  # e.g. AWS_ACCESS_KEY_ID for S3
    hour: Mapped[int] = mapped_column(Integer, default=2)       # local hour of the daily run
    include_media: Mapped[bool] = mapped_column(Boolean, default=False)
    keep_daily: Mapped[int] = mapped_column(Integer, default=7)
    keep_weekly: Mapped[int] = mapped_column(Integer, default=5)
    keep_monthly: Mapped[int] = mapped_column(Integer, default=12)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16), default="backup")  # backup | check
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    files_new: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_changed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_added: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


# ------------------------------------------------------------------ text inside files

class AssetText(Base):
    """Words found in a file (PDF/Word text, or OCR of scans and pictures), for search."""

    __tablename__ = "asset_texts"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    text: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(16))  # text | ocr | none | failed
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))  # of the file it was read from
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Passkey(Base):
    """A passkey (WebAuthn): sign in with the phone's or laptop's fingerprint, face or PIN.
    It works only on the address it was made on (rp_id), as browsers require."""

    __tablename__ = "passkeys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[str] = mapped_column(String(512), unique=True, index=True)  # base64url
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    name: Mapped[str] = mapped_column(String(100))
    rp_id: Mapped[str] = mapped_column(String(255))
    transports: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PluginState(Base):
    """Whether a plugin is on, its settings, and the last thing that went wrong."""

    __tablename__ = "plugin_states"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # the plugin's id
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FedGuest(Base):
    """Another ZiraHive this server shares some categories with (this server is the host)."""

    __tablename__ = "fed_guests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))          # e.g. "Rahim's house"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    library_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of shared categories
    max_age: Mapped[int | None] = mapped_column(Integer, nullable=True)  # age limit for what they see
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FedLink(Base):
    """Another ZiraHive whose shared categories people here can watch (this server is the guest)."""

    __tablename__ = "fed_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(512))
    token: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RemoteProgress(Base):
    """Where someone here stopped in a title on a linked ZiraHive."""

    __tablename__ = "remote_progress"
    __table_args__ = (UniqueConstraint("user_id", "link_id", "media_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    link_id: Mapped[str] = mapped_column(ForeignKey("fed_links.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512), default="")
    position: Mapped[float] = mapped_column(Float, default=0)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)



class PhotoVector(Base):
    """What a photo shows, as a CLIP vector, for searching by description (local AI)."""

    __tablename__ = "photo_vectors"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # float32, unit length


class Person(Base):
    """Faces that look like the same person, in one account's photos."""

    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Face(Base):
    __tablename__ = "faces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), nullable=True, index=True)
    box: Mapped[str] = mapped_column(String(100))  # JSON [x, y, w, h] as parts of the picture
    score: Mapped[float] = mapped_column(Float, default=0)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # put there by a person, not guessed


class DocChunk(Base):
    """A passage of a document's text with its meaning as a vector, for Ask your files."""

    __tablename__ = "doc_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    n: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))  # of the file the passage came from


class IptvSource(Base):
    """An IPTV subscription (Xtream Codes API: server address, username, password).
    The password never leaves the server; the web app only sees the name."""

    __tablename__ = "iptv_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    server: Mapped[str] = mapped_column(String(512))  # http://host:port, no path
    username: Mapped[str] = mapped_column(String(255))
    password: Mapped[str] = mapped_column(Text)
    # shared by an admin: everyone in the family can watch it (but not see the login)
    shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IptvFavorite(Base):
    __tablename__ = "iptv_favorites"
    __table_args__ = (UniqueConstraint("user_id", "source_id", "kind", "stream_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("iptv_sources.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # live, vod or series
    stream_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    ext: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PrayerSettings(Base):
    """Where someone prays and how their prayer times are worked out (one row per person).
    `settings` is JSON: {lat, lng, place, method, asr, offsets: {fajr: 2, ...}, reminders: {...}}."""

    __tablename__ = "prayer_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    settings: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PrayerLog(Base):
    """One prayer on one day: prayed on time, prayed late (qaza) or missed."""

    __tablename__ = "prayer_log"
    __table_args__ = (UniqueConstraint("user_id", "day", "prayer"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)   # YYYY-MM-DD, the person's own calendar day
    prayer: Mapped[str] = mapped_column(String(8))              # fajr dhuhr asr maghrib isha (or witr, jumuah)
    status: Mapped[str] = mapped_column(String(8))              # ontime | late | missed
    jamaah: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
