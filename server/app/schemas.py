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
    max_age: int | None = None


class MeOut(UserOut):
    ntfy_url: str | None = None
    language: str | None = None
    used_bytes: int = 0


class UserAdminOut(UserOut):
    used_bytes: int = 0


class UserUpdateIn(BaseModel):
    max_age: int | None = Field(default=None, ge=-1, le=18)  # -1 = no limit
    is_admin: bool | None = None
    quota_gb: float | None = Field(default=None, ge=0)
    clear_quota: bool = False
    new_password: str | None = Field(default=None, min_length=8, max_length=256)
    reset_2fa: bool = False


class MySettingsIn(BaseModel):
    """Only the fields sent are changed."""
    ntfy_url: str | None = Field(default=None, max_length=512, pattern=r"^(https?://.+)?$")
    language: str | None = Field(default=None, pattern=r"^(en|bn)?$")


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
    # The PC sync client: replace the file with this name in this folder (any kind of file),
    # keeping the old one as a version, instead of adding "name (1).jpg".
    replace: bool = False


class UploadOut(BaseModel):
    id: str | None = None
    offset: int = 0
    size: int = 0
    status: str  # "uploading" | "complete" | "exists"
    asset: AssetOut | None = None


class PhotoPage(BaseModel):
    items: list[AssetOut]
    next_cursor: str | None


_KIND = r"^(movies|shows|mixed|music|audiobooks|books|comics|quran)$"


class LibraryIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1)
    kind: str = Field(default="movies", pattern=_KIND)


class LibraryUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    kind: str | None = Field(default=None, pattern=_KIND)
    age_rating: int | None = Field(default=None, ge=-1, le=18)  # -1 clears it


class LibraryOrderIn(BaseModel):
    ids: list[str]


class LibraryOut(ORM):
    id: str
    name: str
    path: str
    kind: str
    sort_order: int = 0
    age_rating: int | None = None
    last_scan_at: datetime | None
    item_count: int = 0  # movies + series
    available: bool = True  # folder currently reachable
    display_path: str = ""  # E:\Movies\English


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
    intro_start: float | None = None
    intro_end: float | None = None
    credits_start: float | None = None
    age: int | None = None  # effective age rating


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
    age: int | None = None


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
    age: int | None = None
    age_rating: int | None = None  # the admin's own choice, if any
    intro_start: float | None = None
    intro_end: float | None = None
    credits_before_end: float | None = None


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


class TranscodeOut(BaseModel):
    title: str
    quality: str
    encoder: str
    paused: bool
    running: bool
    viewers: list[str]


class ActivityOut(BaseModel):
    streams: list[StreamOut]
    transcodes: list[TranscodeOut] = []
    jobs_queued: int | None
    jobs_mode: str
    disks: list[DiskOut]
    cache_bytes: int
    started_at: datetime


class SecurityCheck(BaseModel):
    ok: bool
    title: str
    fix: str | None
    level: str  # high | medium | info


class RatingIn(BaseModel):
    age_rating: int | None = Field(default=None, ge=0, le=18)  # None clears the admin's choice


class MarkersIn(BaseModel):
    intro_start: float | None = Field(default=None, ge=0)
    intro_end: float | None = Field(default=None, ge=0)
    credits_before_end: float | None = Field(default=None, ge=0)


class AudioTrack(BaseModel):
    index: int
    label: str
    language: str | None
    codec: str | None
    default: bool = False


class SubtitleTrack(BaseModel):
    id: str
    label: str
    language: str | None
    usable: bool
    forced: bool = False


class TracksOut(BaseModel):
    audio: list[AudioTrack]
    subtitles: list[SubtitleTrack]
    qualities: list[str]
    direct_play: bool
    encoder: str
    ai_subtitles: str | None = None  # None, queued, working, done:<lang>, failed:<reason>


class OfflineIn(BaseModel):
    quality: str = Field(default="480p", pattern=r"^(1080p|720p|480p|360p)$")


class OfflineOut(ORM):
    id: str
    media_id: str
    quality: str
    status: str
    progress: float
    size: int | None
    error: str | None
    created_at: datetime


class PartyIn(BaseModel):
    media_id: str
    scheduled_at: datetime | None = None
    invite: list[str] = []
    control: str = Field(default="everyone", pattern=r"^(host|everyone)$")
    wait_for_all: bool = True


class PartyUpdateIn(BaseModel):
    scheduled_at: datetime | None = None
    clear_schedule: bool = False
    control: str | None = Field(default=None, pattern=r"^(host|everyone)$")
    wait_for_all: bool | None = None


class RsvpIn(BaseModel):
    rsvp: str = Field(pattern=r"^(going|declined)$")


class InviteIn(BaseModel):
    user_ids: list[str]


class PartyMemberOut(BaseModel):
    user_id: str
    username: str
    rsvp: str
    online: bool


class PartyOut(BaseModel):
    id: str
    title: str
    host_id: str
    host: str
    is_host: bool
    media_id: str
    media_title: str
    series_title: str | None
    poster_ready: bool
    scheduled_at: datetime | None
    control: str
    wait_for_all: bool
    ended_at: datetime | None
    created_at: datetime
    my_rsvp: str | None
    members: list[PartyMemberOut]
    online: int


class ChatOut(BaseModel):
    id: str
    username: str
    text: str
    created_at: datetime


# ------------------------------------------------------------------ music

class MusicAlbumOut(ORM):
    id: str
    library_id: str
    title: str
    artist: str
    year: int | None
    genre: str | None
    cover_ready: bool
    added_at: datetime
    track_count: int = 0
    duration: float = 0


class TrackOut(ORM):
    id: str
    library_id: str
    album_id: str | None
    title: str
    artist: str | None
    album_title: str | None
    track_no: int | None
    disc_no: int | None
    year: int | None
    genre: str | None
    duration: float | None
    codec: str | None
    playable: bool
    favorite: bool = False
    plays: int = 0
    cover_ready: bool = False  # the album's cover


class MusicAlbumDetailOut(MusicAlbumOut):
    tracks: list[TrackOut] = []


class ArtistOut(BaseModel):
    name: str
    album_count: int
    track_count: int
    cover_album_id: str | None


class ArtistDetailOut(BaseModel):
    name: str
    albums: list[MusicAlbumOut]
    tracks: list[TrackOut]  # most played first


class PlaylistIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    track_ids: list[str] = []


class PlaylistUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    track_ids: list[str] | None = None  # replaces the order and contents


class PlaylistAddIn(BaseModel):
    track_ids: list[str] = Field(min_length=1, max_length=2000)


class PlaylistOut(ORM):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    track_count: int = 0
    duration: float = 0
    cover_album_ids: list[str] = []


class PlaylistDetailOut(PlaylistOut):
    tracks: list[TrackOut] = []


class FavoriteIn(BaseModel):
    favorite: bool


class MusicHomeOut(BaseModel):
    recent_albums: list[MusicAlbumOut]
    recently_played: list[TrackOut]
    most_played: list[TrackOut]
    playlists: list[PlaylistOut]
    favorite_count: int


class AudioReadyOut(BaseModel):
    ready: bool
    failed: bool = False


# ------------------------------------------------------- audiobooks, ebooks, comics

class BookProgressOut(BaseModel):
    position: float = 0
    locator: str | None = None
    fraction: float = 0
    finished: bool = False
    updated_at: datetime | None = None


class BookOut(ORM):
    id: str
    library_id: str
    kind: str
    format: str
    title: str
    author: str | None
    narrator: str | None
    series_name: str | None
    series_index: float | None
    year: int | None
    cover_ready: bool
    size: int
    duration: float | None
    pages: int | None
    added_at: datetime
    progress: BookProgressOut | None = None


class AudioPartOut(BaseModel):
    index: int
    title: str
    start: float
    duration: float
    playable: bool


class ChapterOut(BaseModel):
    title: str
    start: float


class BookDetailOut(BookOut):
    description: str | None
    language: str | None
    parts: list[AudioPartOut] = []
    chapters: list[ChapterOut] = []
    rtl: bool = False
    downloadable: bool = False
    next_in_series: str | None = None


class BookProgressIn(BaseModel):
    position: float = Field(ge=0)
    locator: str | None = Field(default=None, max_length=2000)
    fraction: float = Field(ge=0, le=1)
    finished: bool | None = None


# ------------------------------------------------------------------ vault

_B64 = r"^[A-Za-z0-9+/=_-]+$"


class VaultSetupIn(BaseModel):
    salt: str = Field(min_length=16, max_length=64, pattern=_B64)
    iterations: int = Field(ge=100_000, le=10_000_000)
    wrapped_key: str = Field(min_length=40, max_length=512, pattern=_B64)
    recovery_wrapped_key: str = Field(min_length=40, max_length=512, pattern=_B64)


class VaultKeysIn(BaseModel):
    """New passphrase (and optionally a new recovery key). Needs the account password."""
    password: str
    salt: str = Field(min_length=16, max_length=64, pattern=_B64)
    iterations: int = Field(ge=100_000, le=10_000_000)
    wrapped_key: str = Field(min_length=40, max_length=512, pattern=_B64)
    recovery_wrapped_key: str | None = Field(default=None, min_length=40, max_length=512, pattern=_B64)


class VaultResetIn(BaseModel):
    password: str


class VaultOut(BaseModel):
    set_up: bool
    kdf: str | None = None
    salt: str | None = None
    iterations: int | None = None
    wrapped_key: str | None = None
    recovery_wrapped_key: str | None = None
    item_count: int = 0
    bytes: int = 0


class VaultItemIn(BaseModel):
    size: int = Field(ge=16)
    chunk_size: int = Field(ge=64 * 1024, le=16 * 1024 * 1024)
    wrapped_key: str = Field(min_length=40, max_length=512, pattern=_B64)
    meta: str = Field(min_length=16, max_length=16384, pattern=_B64)


class VaultItemUpdateIn(BaseModel):
    meta: str = Field(min_length=16, max_length=16384, pattern=_B64)


class VaultItemOut(ORM):
    id: str
    size: int
    received: int
    chunk_size: int
    wrapped_key: str
    meta: str
    has_thumb: bool
    complete: bool
    created_at: datetime


# ------------------------------------------------------------------ offsite backup

class BackupConfigIn(BaseModel):
    repository: str = Field(min_length=2, max_length=1024)
    password: str | None = Field(default=None, min_length=12, max_length=256)  # None -> keep, or make one
    env: dict[str, str] | None = None  # None -> keep
    hour: int = Field(default=2, ge=0, le=23)  # UTC
    include_media: bool = False
    enabled: bool = True


class BackupRunOut(ORM):
    id: str
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    snapshot_id: str | None
    files_new: int | None
    files_changed: int | None
    bytes_added: int | None
    total_bytes: int | None
    message: str | None


class BackupOut(BaseModel):
    configured: bool
    enabled: bool = False
    repository: str | None = None
    env_keys: list[str] = []
    hour: int = 2
    include_media: bool = False
    restic: str | None = None
    runs: list[BackupRunOut] = []
    password: str | None = None  # only right after it was made, to write down
    created: bool = False        # the repository was just created


class SnapshotOut(BaseModel):
    id: str
    time: str
    paths: list[str]


# ------------------------------------------------------------------ search and scans

class SearchHit(BaseModel):
    asset: "AssetOut"
    snippet: str | None = None
    in_text: bool = False  # found in the words inside the file, not its name


class ScanFinishIn(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    folder: str = "/Scans"


class FolderPick(BaseModel):
    path: str
    label: str           # E:\\Movies\\English
    name: str
    guess: str | None = None  # the category type its name suggests


class FolderBrowseOut(BaseModel):
    path: str | None     # None = the list of drives
    label: str | None
    parent: str | None
    guess: str | None = None  # category type this folder's own name suggests
    folders: list[FolderPick]


class CastSubtitle(BaseModel):
    url: str
    label: str
    language: str | None = None


class CastOut(BaseModel):
    """Everything a Chromecast (or a TV) needs to play one title by itself."""
    url: str
    content_type: str
    title: str
    subtitle: str | None = None
    poster: str | None = None
    duration: float | None = None
    start: float = 0
    subtitles: list[CastSubtitle] = []
    converted: bool = False  # True: an HLS stream converted on the fly
