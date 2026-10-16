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


class UploadOut(BaseModel):
    id: str | None = None
    offset: int = 0
    size: int = 0
    status: str  # "uploading" | "complete" | "exists"
    asset: AssetOut | None = None


class PhotoPage(BaseModel):
    items: list[AssetOut]
    next_cursor: str | None


class LibraryIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1)
    kind: str = Field(default="movies", pattern=r"^(movies|shows|videos)$")


class LibraryOut(ORM):
    id: str
    name: str
    path: str
    kind: str
    last_scan_at: datetime | None
    item_count: int = 0


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
