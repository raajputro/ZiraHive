from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SetupIn(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=8, max_length=256)


class LoginIn(BaseModel):
    username: str
    password: str
    code: str | None = None  # 6-digit authenticator code or a recovery code, when 2FA is on


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class UserCreateIn(SetupIn):
    is_admin: bool = False
    quota_gb: float | None = None


class UserOut(ORM):
    id: str
    username: str
    is_admin: bool
    quota_bytes: int | None
    created_at: datetime
    totp_enabled: bool = False


class MeOut(UserOut):
    ntfy_url: str | None = None
    used_bytes: int = 0


class UserAdminOut(UserOut):
    used_bytes: int = 0


class UserUpdateIn(BaseModel):
    is_admin: bool | None = None
    quota_gb: float | None = Field(default=None, ge=0)
    clear_quota: bool = False
    new_password: str | None = Field(default=None, min_length=8, max_length=256)
    reset_2fa: bool = False


class MySettingsIn(BaseModel):
    ntfy_url: str | None = Field(default=None, max_length=512, pattern=r"^(https?://.+)?$")


class TwoFactorSetupOut(BaseModel):
    secret: str
    uri: str
    qr_svg: str


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class PasswordIn(BaseModel):
    password: str


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class TokenOut(BaseModel):
    token: str
    user: UserOut


class AssetOut(ORM):
    id: str
    folder: str
    filename: str
    size: int
    mime: str
    kind: str
    sha256: str
    thumb_ready: bool
    width: int | None
    height: int | None
    duration: float | None
    taken_at: datetime | None
    created_at: datetime
    deleted_at: datetime | None = None
    updated_at: datetime | None = None
    owner_id: str | None = None


class FolderListing(BaseModel):
    folder: str
    folders: list[str]
    assets: list[AssetOut]


class FolderCreateIn(BaseModel):
    path: str


class AssetUpdateIn(BaseModel):
    filename: str | None = None
    folder: str | None = None


class HashCheckIn(BaseModel):
    sha256: list[str] = Field(max_length=5000)


class HashCheckOut(BaseModel):
    existing: list[str]


class UploadCreateIn(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size: int = Field(ge=0)
    folder: str = "/"
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    taken_at: datetime | None = None
    device_asset_id: str | None = None
    # True for camera-roll backup (skip what's already saved anywhere); False when you put a
    # file into a specific folder in Files and expect to see it there.
    dedupe: bool = True


class UploadOut(BaseModel):
    id: str | None = None
    offset: int = 0
    size: int = 0
    status: str  # "uploading" | "complete" | "exists"
    asset: AssetOut | None = None


class PhotoPage(BaseModel):
    items: list[AssetOut]
    next_cursor: str | None


_KIND = r"^(movies|shows|mixed)$"


class LibraryIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1)
    kind: str = Field(default="movies", pattern=_KIND)


class LibraryUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    kind: str | None = Field(default=None, pattern=_KIND)


class LibraryOrderIn(BaseModel):
    ids: list[str]


class LibraryOut(ORM):
    id: str
    name: str
    path: str
    kind: str
    sort_order: int = 0
    last_scan_at: datetime | None
    item_count: int = 0  # movies + series
    available: bool = True  # folder currently reachable


class MediaOut(ORM):
    id: str
    library_id: str
    title: str
    year: int | None
    overview: str | None
    size: int
    container: str | None
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    duration: float | None
    poster_ready: bool
    added_at: datetime
    browser_playable: bool = False
    position: float = 0
    finished: bool = False
    series_id: str | None = None
    series_title: str | None = None
    season: int | None = None
    episode: int | None = None
    episode_title: str | None = None
    next_id: str | None = None  # next episode, when this is an episode


class TitleOut(BaseModel):
    """One card on the Watch page: a movie or a whole series."""
    type: str  # "movie" | "series"
    id: str
    library_id: str
    title: str
    year: int | None
    poster_ready: bool
    added_at: datetime
    duration: float | None = None
    position: float = 0
    finished: bool = False
    browser_playable: bool = False
    episode_count: int = 0
    watched_count: int = 0


class SeasonOut(BaseModel):
    season: int | None
    episodes: list[MediaOut]


class SeriesOut(BaseModel):
    id: str
    library_id: str
    title: str
    year: int | None
    overview: str | None
    poster_ready: bool
    episode_count: int
    seasons: list[SeasonOut]
    up_next: MediaOut | None


class ProgressIn(BaseModel):
    position: float = Field(ge=0)
    duration: float | None = Field(default=None, ge=0)


class StatsOut(BaseModel):
    users: int
    assets: int
    asset_bytes: int
    photos: int
    videos: int
    documents: int
    media_items: int
    disk_total: int
    disk_free: int
    jobs_mode: str


class VersionOut(ORM):
    id: str
    size: int
    sha256: str
    created_at: datetime


class MemoryGroup(BaseModel):
    year: int
    years_ago: int
    items: list[AssetOut]


class ShareIn(BaseModel):
    target_type: str = Field(pattern=r"^(asset|folder|album)$")
    target_id: str = Field(min_length=1, max_length=1024)
    password: str | None = Field(default=None, max_length=256)
    expires_days: int | None = Field(default=None, ge=1, le=3650)
    allow_download: bool = True


class ShareOut(ORM):
    id: str
    token: str
    target_type: str
    target_id: str
    label: str = ""
    has_password: bool = False
    expires_at: datetime | None
    allow_download: bool
    views: int
    created_at: datetime


class PublicShareOut(BaseModel):
    type: str
    title: str
    owner: str
    needs_password: bool
    expires_at: datetime | None
    allow_download: bool


class PublicAsset(BaseModel):
    id: str
    filename: str
    size: int
    mime: str
    kind: str
    width: int | None
    height: int | None
    duration: float | None
    taken_at: datetime | None
    thumb_ready: bool


class PublicListing(BaseModel):
    path: str
    folders: list[str]
    assets: list[PublicAsset]


class UnlockIn(BaseModel):
    password: str


class AlbumIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    asset_ids: list[str] = []


class AlbumUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    cover_asset_id: str | None = None


class AssetIdsIn(BaseModel):
    asset_ids: list[str] = Field(max_length=5000)


class MemberIn(BaseModel):
    user_id: str
    can_add: bool = True


class MembersIn(BaseModel):
    members: list[MemberIn]


class AlbumMemberOut(BaseModel):
    user_id: str
    username: str
    can_add: bool


class AlbumOut(BaseModel):
    id: str
    title: str
    owner_id: str
    owner: str
    is_owner: bool
    can_add: bool
    cover_asset_id: str | None
    item_count: int
    members: list[AlbumMemberOut]
    created_at: datetime


class AlbumDetailOut(AlbumOut):
    items: list[AssetOut]


class NotificationOut(ORM):
    id: str
    kind: str
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationOut]


class BackupReportIn(BaseModel):
    uploaded: int = Field(ge=0)
    skipped: int = Field(ge=0)
    failed: int = Field(ge=0)
    device: str | None = Field(default=None, max_length=128)


class AuditOut(ORM):
    id: str
    username: str | None
    action: str
    detail: str | None
    ip: str | None
    created_at: datetime


class StreamOut(BaseModel):
    username: str
    media_id: str
    title: str
    last_seen: datetime


class DiskOut(BaseModel):
    label: str
    path: str
    total: int
    free: int


class ActivityOut(BaseModel):
    streams: list[StreamOut]
    jobs_queued: int | None
    jobs_mode: str
    disks: list[DiskOut]
    cache_bytes: int
    started_at: datetime
