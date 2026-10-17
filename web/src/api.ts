import { digits, t as tr, tx } from "./i18n";
// Typed client for the ZiraHive API. Auth uses the httpOnly cookie set at login.

export interface User { id: string; username: string; is_admin: boolean; quota_bytes: number | null; created_at: string; totp_enabled: boolean; max_age: number | null; language?: string | null }
export interface Me extends User { ntfy_url: string | null; used_bytes: number; language: string | null }
export interface AdminUser extends User { used_bytes: number }
export interface Asset {
  id: string; folder: string; filename: string; size: number; mime: string;
  kind: "photo" | "video" | "document" | "other"; sha256: string; thumb_ready: boolean;
  width: number | null; height: number | null; duration: number | null;
  taken_at: string | null; created_at: string; deleted_at: string | null; updated_at: string | null;
  owner_id: string | null;
}
export interface Party {
  id: string; title: string; host_id: string; host: string; is_host: boolean; media_id: string; media_title: string;
  series_title: string | null; poster_ready: boolean; scheduled_at: string | null; control: "host" | "everyone";
  wait_for_all: boolean; ended_at: string | null; created_at: string; my_rsvp: "invited" | "going" | "declined" | null;
  members: { user_id: string; username: string; rsvp: string; online: boolean }[]; online: number;
}
export interface Version { id: string; size: number; sha256: string; created_at: string }
export interface Memory { year: number; years_ago: number; items: Asset[] }
export type ShareTarget = "asset" | "folder" | "album";
export interface Share {
  id: string; token: string; target_type: ShareTarget; target_id: string; label: string; has_password: boolean;
  expires_at: string | null; allow_download: boolean; views: number; created_at: string;
}
export interface PublicShare { type: ShareTarget; title: string; owner: string; needs_password: boolean; expires_at: string | null; allow_download: boolean }
export interface PublicAsset {
  id: string; filename: string; size: number; mime: string; kind: Asset["kind"]; width: number | null;
  height: number | null; duration: number | null; taken_at: string | null; thumb_ready: boolean;
}
export interface PublicListing { path: string; folders: string[]; assets: PublicAsset[] }
export interface AlbumMember { user_id: string; username: string; can_add: boolean }
export interface Album {
  id: string; title: string; owner_id: string; owner: string; is_owner: boolean; can_add: boolean;
  cover_asset_id: string | null; item_count: number; members: AlbumMember[]; created_at: string;
}
export interface AlbumDetail extends Album { items: Asset[] }
export interface Notice { id: string; kind: string; title: string; body: string | null; link: string | null; read_at: string | null; created_at: string }
export interface AuditEvent { id: string; username: string | null; action: string; detail: string | null; ip: string | null; created_at: string }
export interface Activity {
  streams: { username: string; media_id: string; title: string; last_seen: string }[];
  transcodes: { title: string; quality: string; encoder: string; paused: boolean; running: boolean; viewers: string[] }[];
  jobs_queued: number | null; jobs_mode: string; cache_bytes: number; started_at: string;
  disks: { label: string; path: string; total: number; free: number }[];
}
export interface FolderListing { folder: string; folders: string[]; assets: Asset[] }
export interface PhotoPage { items: Asset[]; next_cursor: string | null }
export type LibraryKind = "movies" | "shows" | "mixed" | "music" | "audiobooks" | "books" | "comics";
export const VIDEO_KINDS: LibraryKind[] = ["movies", "shows", "mixed"];

// ------------------------------------------------------------------ music
export interface MusicAlbum {
  id: string; library_id: string; title: string; artist: string; year: number | null; genre: string | null;
  cover_ready: boolean; added_at: string; track_count: number; duration: number;
}
export interface Track {
  id: string; library_id: string; album_id: string | null; title: string; artist: string | null; album_title: string | null;
  track_no: number | null; disc_no: number | null; year: number | null; genre: string | null; duration: number | null;
  codec: string | null; playable: boolean; favorite: boolean; plays: number; cover_ready: boolean;
}
export interface MusicAlbumDetail extends MusicAlbum { tracks: Track[] }
export interface Artist { name: string; album_count: number; track_count: number; cover_album_id: string | null }
export interface ArtistDetail { name: string; albums: MusicAlbum[]; tracks: Track[] }
export interface Playlist { id: string; name: string; created_at: string; updated_at: string; track_count: number; duration: number; cover_album_ids: string[] }
export interface PlaylistDetail extends Playlist { tracks: Track[] }
export interface MusicHome { recent_albums: MusicAlbum[]; recently_played: Track[]; most_played: Track[]; playlists: Playlist[]; favorite_count: number }

// ------------------------------------------------------- audiobooks, ebooks, comics
export type BookKind = "audiobook" | "ebook" | "comic";
export interface BookProgress { position: number; locator: string | null; fraction: number; finished: boolean; updated_at: string | null }
export interface Book {
  id: string; library_id: string; kind: BookKind; format: string; title: string; author: string | null; narrator: string | null;
  series_name: string | null; series_index: number | null; year: number | null; cover_ready: boolean; size: number;
  duration: number | null; pages: number | null; added_at: string; progress: BookProgress | null;
}
export interface AudioPart { index: number; title: string; start: number; duration: number; playable: boolean }
export interface Chapter { title: string; start: number }
export interface BookDetail extends Book {
  description: string | null; language: string | null; parts: AudioPart[]; chapters: Chapter[]; rtl: boolean;
  downloadable: boolean; next_in_series: string | null;
}
export interface BookProgressIn { position: number; fraction: number; locator?: string | null; finished?: boolean }
export interface Library {
  id: string; name: string; path: string; kind: LibraryKind; sort_order: number; age_rating: number | null;
  last_scan_at: string | null; item_count: number; available: boolean; display_path: string;
}
export interface Media {
  id: string; library_id: string; title: string; year: number | null; overview: string | null;
  size: number; container: string | null; video_codec: string | null; audio_codec: string | null;
  width: number | null; height: number | null; duration: number | null; poster_ready: boolean;
  added_at: string; browser_playable: boolean; position: number; finished: boolean;
  series_id: string | null; series_title: string | null; season: number | null; episode: number | null;
  episode_title: string | null; next_id: string | null;
  intro_start: number | null; intro_end: number | null; credits_start: number | null; age: number | null;
  base?: string; link_id?: string;  // a title on a linked ZiraHive, fetched through this server
}
export type Quality = "original" | "1080p" | "720p" | "480p" | "360p";
export interface Tracks {
  audio: { index: number; label: string; language: string | null; codec: string | null; default: boolean }[];
  subtitles: { id: string; label: string; language: string | null; usable: boolean; forced: boolean }[];
  qualities: Exclude<Quality, "original">[]; direct_play: boolean; encoder: string; ai_subtitles?: string | null;
}
export interface OfflineCopy {
  id: string; media_id: string; quality: string; status: "queued" | "working" | "ready" | "failed";
  progress: number; size: number | null; error: string | null; created_at: string;
}
export interface Title {
  type: "movie" | "series"; id: string; library_id: string; title: string; year: number | null;
  poster_ready: boolean; added_at: string; duration: number | null; position: number; finished: boolean;
  browser_playable: boolean; episode_count: number; watched_count: number; age: number | null;
}
export interface SeriesDetail {
  id: string; library_id: string; title: string; year: number | null; overview: string | null;
  poster_ready: boolean; episode_count: number;
  seasons: { season: number | null; episodes: Media[] }[];
  up_next: Media | null;
  age: number | null; age_rating: number | null;
  intro_start: number | null; intro_end: number | null; credits_before_end: number | null;
}
export interface Stats {
  users: number; assets: number; asset_bytes: number; photos: number; videos: number;
  documents: number; media_items: number; disk_total: number; disk_free: number; jobs_mode: string;
}
export interface UploadResult { id: string | null; offset: number; size: number; status: "uploading" | "complete" | "exists"; asset: Asset | null }

export interface SecurityItem { ok: boolean; title: string; fix: string | null; level: "high" | "medium" | "info" }

let publicBase = "";
/** Loads the public share-link address once (ZIRAHIVE_PUBLIC_URL on the server). */
export async function loadConfig() {
  try {
    const r = await fetch("/api/config");
    if (r.ok) publicBase = (await r.json()).public_url || "";
  } catch { /* offline: fall back to this address */ }
}
export const hasPublicBase = () => !!publicBase;
export const publicAddress = () => publicBase;

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) { super(message); }
}

async function request<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  let payload: BodyInit | undefined;
  if (body instanceof Blob) payload = body;
  else if (body !== undefined) { payload = JSON.stringify(body); headers["Content-Type"] = "application/json"; }
  const res = await fetch(path, { ...init, method, body: payload, headers, credentials: "same-origin" });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    let code: string | undefined;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join("; ");
      else if (data.detail && typeof data.detail === "object") { message = data.detail.message; code = data.detail.code; }
    } catch { /* not JSON */ }
    message = tx(message);  // server messages in the interface language
    if (res.status === 401 && !path.startsWith("/api/auth/login") && !path.startsWith("/api/auth/passkeys/login") && !path.startsWith("/api/s/"))
      window.dispatchEvent(new Event("zirahive:signed-out"));
    throw new ApiError(res.status, message, code);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") s.set(k, String(v)); });
  const str = s.toString();
  return str ? `?${str}` : "";
};

export interface VaultInfo {
  set_up: boolean; kdf: string | null; salt: string | null; iterations: number | null; wrapped_key: string | null;
  recovery_wrapped_key: string | null; item_count: number; bytes: number;
}
export interface VaultItem { id: string; size: number; received: number; chunk_size: number; wrapped_key: string; meta: string; has_thumb: boolean; complete: boolean; created_at: string }

export interface BackupRun {
  id: string; kind: "backup" | "check"; status: "running" | "ok" | "failed"; started_at: string; finished_at: string | null;
  snapshot_id: string | null; files_new: number | null; files_changed: number | null; bytes_added: number | null;
  total_bytes: number | null; message: string | null;
}
export interface BackupInfo {
  configured: boolean; enabled: boolean; repository: string | null; env_keys: string[]; hour: number; include_media: boolean;
  restic: string | null; runs: BackupRun[]; password: string | null; created: boolean;
}

export interface FolderBrowse {
  path: string | null; label: string | null; parent: string | null; guess: string | null;
  folders: { path: string; label: string; name: string; guess: string | null }[];
}
export interface SearchHit { asset: Asset; snippet: string | null; in_text: boolean }

export interface PluginSetting { key: string; label: string; type: "text" | "secret" | "bool" | "choice" | "number"; help: string | null; choices: string[]; value: unknown; has_value: boolean }
export interface Plugin {
  id: string; name: string; description: string; version: string; author: string | null; builtin: boolean;
  enabled: boolean; events: string[]; settings: PluginSetting[]; error: string | null;
  last_error: string | null; last_error_at: string | null; last_ok_at: string | null; has_pages: boolean;
}

export interface HealthItem { id: string; title: string; status: "ok" | "warn" | "fail" | "info"; detail: string; fix: string | null }
export interface AiStatus { ai: boolean; ollama: boolean; models: Record<string, string>; photos: number; photos_indexed: number; people: number; documents_ready: number; llm_model: string; embed_model: string }
export interface PersonSummary { id: string; name: string | null; photos: number; cover_face: string | null; hidden: boolean }
export interface Cleanup { duplicates: { keep: string; photos: Asset[] }[]; blurry: Asset[]; measured: number; waiting: number }
export interface AskAnswer { answer: string; sources: { n: number; asset_id: string; filename: string; folder: string; passage: string }[] }

export interface LinkedServer { id: string; name: string; url: string | null; ok: boolean; last_error: string | null; libraries: { id: string; name: string; kind: string }[] }
export interface LinkGuest { id: string; name: string; library_ids: string[]; max_age: number | null; created_at: string; last_seen_at: string | null; code: string | null }

export interface Passkey { id: string; name: string; rp_id: string; created_at: string; last_used_at: string | null }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface PasskeyChallenge { options: any; state: string }

export interface CastInfo {
  url: string; content_type: string; title: string; subtitle: string | null; poster: string | null;
  duration: number | null; start: number; converted: boolean;
  subtitles: { url: string; label: string; language: string | null }[];
}

export const api = {
  browseFolders: (path?: string) => request<FolderBrowse>("GET", `/api/admin/folders${q({ path })}`),
  search: (text: string) => request<SearchHit[]>("GET", `/api/search${q({ q: text })}`),
  startScan: () => request<{ id: string }>("POST", "/api/scans"),
  scanPage: (id: string, n: number, jpeg: Blob) => request<void>("PUT", `/api/scans/${id}/pages/${n}`, jpeg),
  finishScan: (id: string, title: string, folder: string) => request<Asset>("POST", `/api/scans/${id}/finish`, { title, folder }),
  cancelScan: (id: string) => request<void>("DELETE", `/api/scans/${id}`),
  backup: () => request<BackupInfo>("GET", "/api/admin/backup"),
  saveBackup: (body: { repository: string; password?: string; env?: Record<string, string>; hour: number; include_media: boolean; enabled: boolean }) =>
    request<BackupInfo>("PUT", "/api/admin/backup", body),
  backupNow: () => request<void>("POST", "/api/admin/backup/run"),
  checkBackup: () => request<void>("POST", "/api/admin/backup/check"),
  backupSnapshots: () => request<{ id: string; time: string; paths: string[] }[]>("GET", "/api/admin/backup/snapshots"),
  backupPassword: () => request<{ password: string }>("GET", "/api/admin/backup/password"),
  // vault (everything sent here is already encrypted)
  vault: () => request<VaultInfo>("GET", "/api/vault"),
  setUpVault: (body: { salt: string; iterations: number; wrapped_key: string; recovery_wrapped_key: string }) => request<VaultInfo>("POST", "/api/vault", body),
  changeVaultKeys: (body: { password: string; salt: string; iterations: number; wrapped_key: string; recovery_wrapped_key?: string }) =>
    request<VaultInfo>("PUT", "/api/vault/keys", body),
  resetVault: (password: string) => request<void>("DELETE", "/api/vault", { password }),
  vaultItems: () => request<VaultItem[]>("GET", "/api/vault/items"),
  createVaultItem: (body: { size: number; chunk_size: number; wrapped_key: string; meta: string }) => request<VaultItem>("POST", "/api/vault/items", body),
  vaultChunk: (id: string, offset: number, data: Uint8Array) =>
    request<VaultItem>("PATCH", `/api/vault/items/${id}/data`, new Blob([data]), { headers: { "Upload-Offset": String(offset) } }),
  vaultThumb: (id: string, data: Uint8Array) => request<void>("PUT", `/api/vault/items/${id}/thumb`, new Blob([data])),
  renameVaultItem: (id: string, meta: string) => request<VaultItem>("PATCH", `/api/vault/items/${id}`, { meta }),
  deleteVaultItem: (id: string) => request<void>("DELETE", `/api/vault/items/${id}`),

  // music
  musicHome: () => request<MusicHome>("GET", "/api/music/home"),
  musicAlbums: (params: { library_id?: string; q?: string; artist?: string; sort?: "added" | "title" | "artist" | "year"; limit?: number } = {}) =>
    request<MusicAlbum[]>("GET", `/api/music/albums${q(params)}`),
  musicAlbum: (id: string) => request<MusicAlbumDetail>("GET", `/api/music/albums/${id}`),
  artists: () => request<Artist[]>("GET", "/api/music/artists"),
  artist: (name: string) => request<ArtistDetail>("GET", `/api/music/artist${q({ name })}`),
  songs: (params: { q?: string; favorites?: boolean; sort?: "title" | "artist" | "added" | "album"; limit?: number } = {}) =>
    request<Track[]>("GET", `/api/music/tracks${q({ ...params, favorites: params.favorites ? "true" : undefined })}`),
  prepareTrack: (id: string, force = false) => request<{ ready: boolean; failed: boolean }>("GET", `/api/music/tracks/${id}/prepare${force ? "?force=true" : ""}`),
  trackPlayed: (id: string) => request<void>("POST", `/api/music/tracks/${id}/played`),
  setFavorite: (id: string, favorite: boolean) => request<void>("PUT", `/api/music/tracks/${id}/favorite`, { favorite }),
  playlists: () => request<Playlist[]>("GET", "/api/music/playlists"),
  playlist: (id: string) => request<PlaylistDetail>("GET", `/api/music/playlists/${id}`),
  createPlaylist: (name: string, track_ids: string[] = []) => request<PlaylistDetail>("POST", "/api/music/playlists", { name, track_ids }),
  updatePlaylist: (id: string, change: { name?: string; track_ids?: string[] }) => request<PlaylistDetail>("PATCH", `/api/music/playlists/${id}`, change),
  addToPlaylist: (id: string, track_ids: string[]) => request<PlaylistDetail>("POST", `/api/music/playlists/${id}/tracks`, { track_ids }),
  deletePlaylist: (id: string) => request<void>("DELETE", `/api/music/playlists/${id}`),
  // audiobooks, ebooks, comics
  books: (params: { kind?: BookKind | "reading"; library_id?: string; q?: string; series?: string; sort?: "added" | "title" | "author" | "series"; limit?: number } = {}) =>
    request<Book[]>("GET", `/api/books${q(params)}`),
  continueBooks: (kind?: BookKind | "reading") => request<Book[]>("GET", `/api/books/continue${q({ kind })}`),
  book: (id: string) => request<BookDetail>("GET", `/api/books/${id}`),
  prepareBookPart: (id: string, part: number, force = false) =>
    request<{ ready: boolean; failed: boolean }>("GET", `/api/books/${id}/audio/${part}/prepare${force ? "?force=true" : ""}`),
  saveBookProgress: (id: string, p: BookProgressIn, keepalive = false) =>
    request<BookProgress>("PUT", `/api/books/${id}/progress`, p, keepalive ? { keepalive: true } : {}),
  resetBookProgress: (id: string) => request<void>("DELETE", `/api/books/${id}/progress`),

  setupStatus: () => request<{ needs_setup: boolean }>("GET", "/api/setup/status"),
  setup: (username: string, password: string) => request<{ user: User }>("POST", "/api/setup", { username, password }),
  login: (username: string, password: string, code?: string) =>
    request<{ user: User }>("POST", "/api/auth/login", { username, password, code: code || undefined }),
  logout: () => request<void>("POST", "/api/auth/logout"),
  logoutAll: () => request<void>("POST", "/api/auth/logout-all"),
  me: () => request<Me>("GET", "/api/auth/me"),
  saveMySettings: (ntfy_url: string) => request<Me>("PUT", "/api/auth/me/settings", { ntfy_url }),
  saveLanguage: (language: "en" | "bn") => request<Me>("PUT", "/api/auth/me/settings", { language }),
  testNotification: () => request<void>("POST", "/api/auth/me/test-notification"),
  changePassword: (current_password: string, new_password: string) =>
    request<{ user: User }>("POST", "/api/auth/password", { current_password, new_password }),
  health: () => request<HealthItem[]>("GET", "/api/admin/health"),
  aiStatus: () => request<AiStatus>("GET", "/api/ai/status"),
  aiCatchUp: () => request<void>("POST", "/api/admin/ai/catch-up"),
  searchPhotos: (text: string) => request<{ query: string; searched_for: string; hits: { asset: Asset; score: number }[] }>(
    "GET", `/api/photos/search?q=${encodeURIComponent(text)}`),
  people: (hidden = false) => request<PersonSummary[]>("GET", `/api/people${hidden ? "?hidden=true" : ""}`),
  personPhotos: (id: string) => request<Asset[]>("GET", `/api/people/${id}/photos`),
  personFaces: (id: string) => request<{ id: string; asset_id: string }[]>("GET", `/api/people/${id}/faces`),
  updatePerson: (id: string, change: { name?: string; hidden?: boolean }) => request<PersonSummary>("PATCH", `/api/people/${id}`, change),
  mergePeople: (id: string, into: string) => request<void>("POST", `/api/people/${id}/merge`, { into }),
  notThisPerson: (id: string, faceId: string) => request<void>("DELETE", `/api/people/${id}/faces/${faceId}`),
  cleanup: () => request<Cleanup>("GET", "/api/photos/cleanup"),
  trashAsset: (id: string) => request<void>("DELETE", `/api/assets/${id}`),
  makeSubtitles: (mediaId: string, language?: string) =>
    request<{ status: string }>("POST", `/api/media/${mediaId}/ai-subtitles`, { language: language || undefined }),
  ask: (question: string) => request<AskAnswer>("POST", "/api/ask", { question }),
  links: () => request<LinkedServer[]>("GET", "/api/links"),
  addLink: (code: string, name?: string) => request<LinkedServer>("POST", "/api/admin/links", { code, name: name || undefined }),
  removeLink: (id: string) => request<void>("DELETE", `/api/admin/links/${id}`),
  linkGuests: () => request<LinkGuest[]>("GET", "/api/admin/link-guests"),
  createLinkGuest: (body: { name: string; library_ids: string[]; max_age: number | null; url: string }) =>
    request<LinkGuest>("POST", "/api/admin/link-guests", body),
  removeLinkGuest: (id: string) => request<void>("DELETE", `/api/admin/link-guests/${id}`),
  linkTitles: (linkId: string, libraryId: string) =>
    request<Title[]>("GET", `/api/links/${linkId}/titles?library_id=${encodeURIComponent(libraryId)}`),
  linkSeries: (linkId: string, seriesId: string) => request<SeriesDetail>("GET", `/api/links/${linkId}/series/${seriesId}`),
  linkMedia: (linkId: string, mediaId: string) => request<Media>("GET", `/api/links/${linkId}/media/${mediaId}`),
  linkTracks: (linkId: string, mediaId: string) => request<Tracks>("GET", `/api/links/${linkId}/media/${mediaId}/tracks`),
  linkProgress: (linkId: string, mediaId: string, position: number, duration: number | undefined, title: string) =>
    request<void>("PUT", `/api/links/${linkId}/media/${mediaId}/progress`, { position, duration, title }),
  plugins: () => request<Plugin[]>("GET", "/api/admin/plugins"),
  updatePlugin: (id: string, change: { enabled?: boolean; settings?: Record<string, unknown> }) =>
    request<Plugin>("PUT", `/api/admin/plugins/${id}`, change),
  testPlugin: (id: string) => request<{ ok: boolean; error: string | null }>("POST", `/api/admin/plugins/${id}/test`),
  passkeys: () => request<Passkey[]>("GET", "/api/auth/passkeys"),
  passkeyRegisterOptions: () => request<PasskeyChallenge>("POST", "/api/auth/passkeys/register/options"),
  passkeyRegister: (state: string, credential: unknown, name: string) =>
    request<Passkey>("POST", "/api/auth/passkeys/register", { state, credential, name }),
  removePasskey: (id: string) => request<void>("DELETE", `/api/auth/passkeys/${id}`),
  passkeyLoginOptions: () => request<PasskeyChallenge>("POST", "/api/auth/passkeys/login/options"),
  passkeyLogin: (state: string, credential: unknown) =>
    request<{ user: User }>("POST", "/api/auth/passkeys/login", { state, credential }),
  twoFactorSetup: () => request<{ secret: string; uri: string; qr_svg: string }>("POST", "/api/auth/2fa/setup"),
  twoFactorEnable: (code: string) => request<{ recovery_codes: string[] }>("POST", "/api/auth/2fa/enable", { code }),
  twoFactorDisable: (password: string) => request<void>("POST", "/api/auth/2fa/disable", { password }),

  versions: (id: string) => request<Version[]>("GET", `/api/assets/${id}/versions`),
  restoreVersion: (id: string, vid: string) => request<Asset>("POST", `/api/assets/${id}/versions/${vid}/restore`),
  onThisDay: () => request<Memory[]>("GET", "/api/photos/on-this-day"),

  shares: () => request<Share[]>("GET", "/api/shares"),
  createShare: (body: { target_type: ShareTarget; target_id: string; password?: string; expires_days?: number; allow_download: boolean }) =>
    request<Share>("POST", "/api/shares", body),
  deleteShare: (id: string) => request<void>("DELETE", `/api/shares/${id}`),
  publicShare: (token: string) => request<PublicShare>("GET", `/api/s/${token}`),
  unlockShare: (token: string, password: string) => request<{ key: string }>("POST", `/api/s/${token}/unlock`, { password }),
  publicItems: (token: string, path: string, key?: string) =>
    request<PublicListing>("GET", `/api/s/${token}/items${q({ path, key })}`),

  albums: () => request<Album[]>("GET", "/api/albums"),
  album: (id: string) => request<AlbumDetail>("GET", `/api/albums/${id}`),
  createAlbum: (title: string, asset_ids: string[] = []) => request<Album>("POST", "/api/albums", { title, asset_ids }),
  updateAlbum: (id: string, change: { title?: string; cover_asset_id?: string }) => request<Album>("PATCH", `/api/albums/${id}`, change),
  deleteAlbum: (id: string) => request<void>("DELETE", `/api/albums/${id}`),
  addToAlbum: (id: string, asset_ids: string[]) => request<Album>("POST", `/api/albums/${id}/items`, { asset_ids }),
  removeFromAlbum: (id: string, asset_ids: string[]) => request<Album>("POST", `/api/albums/${id}/items/remove`, { asset_ids }),
  setAlbumMembers: (id: string, members: { user_id: string; can_add: boolean }[]) =>
    request<Album>("PUT", `/api/albums/${id}/members`, { members }),
  directory: () => request<User[]>("GET", "/api/users/directory"),

  notifications: () => request<{ unread: number; items: Notice[] }>("GET", "/api/notifications"),
  markNotificationsRead: () => request<void>("POST", "/api/notifications/read"),
  audit: (before?: string) => request<AuditEvent[]>("GET", `/api/admin/audit${q({ before, limit: 100 })}`),
  activity: () => request<Activity>("GET", "/api/admin/activity"),
  security: () => request<SecurityItem[]>("GET", "/api/admin/security"),
  updateUser: (id: string, change: { max_age?: number; is_admin?: boolean; quota_gb?: number; clear_quota?: boolean; new_password?: string; reset_2fa?: boolean }) =>
    request<AdminUser>("PATCH", `/api/users/${id}`, change),

  files: (folder: string) => request<FolderListing>("GET", `/api/files${q({ folder })}`),
  createFolder: (path: string) => request<{ path: string }>("POST", "/api/folders", { path }),
  deleteFolder: (path: string) => request<void>("DELETE", `/api/folders${q({ path })}`),
  updateAsset: (id: string, change: { filename?: string; folder?: string }) => request<Asset>("PATCH", `/api/assets/${id}`, change),
  trash: () => request<Asset[]>("GET", "/api/trash"),
  restore: (id: string) => request<Asset>("POST", `/api/trash/${id}/restore`),
  deleteForever: (id: string) => request<void>("DELETE", `/api/trash/${id}`),
  emptyTrash: () => request<void>("DELETE", "/api/trash"),
  photos: (cursor?: string | null) => request<PhotoPage>("GET", `/api/photos${q({ cursor, limit: 200 })}`),

  libraries: () => request<Library[]>("GET", "/api/libraries"),
  addLibrary: (name: string, path: string, kind: LibraryKind) => request<Library>("POST", "/api/libraries", { name, path, kind }),
  updateLibrary: (id: string, change: { name?: string; kind?: LibraryKind; age_rating?: number }) => request<Library>("PATCH", `/api/libraries/${id}`, change),
  reorderLibraries: (ids: string[]) => request<Library[]>("PUT", "/api/libraries/order", { ids }),
  discoverLibraries: () => request<Library[]>("POST", "/api/libraries/discover"),
  titles: (params: { library_id?: string; q?: string; sort?: "added" | "title" | "year"; limit?: number }) =>
    request<Title[]>("GET", `/api/titles${q(params)}`),
  series: (id: string) => request<SeriesDetail>("GET", `/api/series/${id}`),
  removeLibrary: (id: string) => request<void>("DELETE", `/api/libraries/${id}`),
  scanLibrary: (id: string) => request<void>("POST", `/api/libraries/${id}/scan`),
  media: (search?: string) => request<Media[]>("GET", `/api/media${q({ q: search })}`),
  continueWatching: () => request<Media[]>("GET", "/api/media/continue"),
  mediaItem: (id: string) => request<Media>("GET", `/api/media/${id}`),
  tracks: (id: string) => request<Tracks>("GET", `/api/media/${id}/tracks`),
  offlineCopies: (id: string) => request<OfflineCopy[]>("GET", `/api/media/${id}/offline`),
  requestOffline: (id: string, quality: string) => request<OfflineCopy>("POST", `/api/media/${id}/offline`, { quality }),
  deleteOffline: (copyId: string) => request<void>("DELETE", `/api/offline/${copyId}`),
  setMediaRating: (id: string, age_rating: number | null) => request<void>("PUT", `/api/media/${id}/rating`, { age_rating }),
  setSeriesRating: (id: string, age_rating: number | null) => request<void>("PUT", `/api/series/${id}/rating`, { age_rating }),
  setSeriesMarkers: (id: string, m: { intro_start: number | null; intro_end: number | null; credits_before_end: number | null }) =>
    request<SeriesDetail>("PUT", `/api/series/${id}/markers`, m),
  parties: () => request<Party[]>("GET", "/api/parties"),
  party: (id: string) => request<Party>("GET", `/api/parties/${id}`),
  createParty: (body: { media_id: string; scheduled_at?: string; invite: string[]; control: "host" | "everyone"; wait_for_all: boolean }) =>
    request<Party>("POST", "/api/parties", body),
  updateParty: (id: string, change: { scheduled_at?: string; clear_schedule?: boolean; control?: "host" | "everyone"; wait_for_all?: boolean }) =>
    request<Party>("PATCH", `/api/parties/${id}`, change),
  rsvp: (id: string, rsvp: "going" | "declined") => request<Party>("PUT", `/api/parties/${id}/rsvp`, { rsvp }),
  inviteToParty: (id: string, user_ids: string[]) => request<Party>("POST", `/api/parties/${id}/invite`, { user_ids }),
  endParty: (id: string) => request<Party>("POST", `/api/parties/${id}/end`),
  castInfo: (id: string, quality: string, audio: number) =>
    request<CastInfo>("GET", `/api/media/${id}/cast?quality=${encodeURIComponent(quality)}&audio=${audio}`),
  streamLink: (id: string) => request<{ path: string }>("GET", `/api/media/${id}/link`),
  saveProgress: (id: string, position: number, duration?: number) =>
    request<void>("PUT", `/api/media/${id}/progress`, { position, duration }),

  users: () => request<AdminUser[]>("GET", "/api/users"),
  createUser: (username: string, password: string, is_admin: boolean) =>
    request<User>("POST", "/api/users", { username, password, is_admin }),
  deleteUser: (id: string) => request<void>("DELETE", `/api/users/${id}`),
  stats: () => request<Stats>("GET", "/api/admin/stats"),

  uploadCreate: (body: { filename: string; size: number; folder: string; sha256?: string; taken_at?: string; dedupe?: boolean }) =>
    request<UploadResult>("POST", "/api/uploads", body),
  uploadChunk: (id: string, offset: number, chunk: Blob, signal?: AbortSignal) =>
    request<UploadResult>("PATCH", `/api/uploads/${id}`, chunk, { headers: { "Upload-Offset": String(offset) }, signal }),
  reportBackup: (r: { uploaded: number; skipped: number; failed: number; device: string }) =>
    request<void>("POST", "/api/events/backup", { uploaded: r.uploaded, skipped: r.skipped, failed: r.failed, device: r.device }),
  uploadStatus: (id: string) => request<UploadResult>("GET", `/api/uploads/${id}`),
};

const mediaBase = (m: { id: string; base?: string }) => m.base ?? `/api/media/${m.id}`;

export const url = {
  thumb: (a: { id: string }) => `/api/assets/${a.id}/thumb`,
  preview: (a: { id: string }) => `/api/assets/${a.id}/preview`,
  version: (a: { id: string }, v: { id: string }) => `/api/assets/${a.id}/versions/${v.id}/file`,
  shareLink: (s: { token: string }) => `${publicBase || location.origin}/s/${s.token}`,
  publicFile: (token: string, a: { id: string }, key?: string, download = false) =>
    `/api/s/${token}/assets/${a.id}/file${q({ key, download: download ? "true" : undefined })}`,
  publicThumb: (token: string, a: { id: string }, key?: string) => `/api/s/${token}/assets/${a.id}/thumb${q({ key })}`,
  publicPreview: (token: string, a: { id: string }, key?: string) => `/api/s/${token}/assets/${a.id}/preview${q({ key })}`,
  file: (a: Asset, download = false) => `/api/assets/${a.id}/file${download ? "?download=true" : ""}`,
  poster: (m: { id: string; base?: string }) => `${mediaBase(m)}/poster`,
  seriesPoster: (s: { id: string }) => `/api/series/${s.id}/poster`,
  titlePoster: (t: Title) => (t.type === "series" ? `/api/series/${t.id}/poster` : `/api/media/${t.id}/poster`),
  stream: (m: Media) => `${mediaBase(m)}/stream`,
  face: (faceId: string) => `/api/faces/${faceId}/crop`,
  hls: (m: { id: string; base?: string }, quality: string, audio: number) => `${mediaBase(m)}/hls/${quality}/${audio}/index.m3u8`,
  subtitle: (m: { id: string; base?: string }, subId: string) => `${mediaBase(m)}/subtitles/${subId}.vtt`,
  linkPoster: (linkId: string, t: { id: string; type: "movie" | "series" }) =>
    `/api/links/${linkId}/${t.type === "series" ? "series" : "media"}/${t.id}/poster`,
  offlineFile: (c: { id: string }) => `/api/offline/${c.id}/file`,
  albumCover: (a: { id: string }) => `/api/music/albums/${a.id}/cover`,
  trackStream: (t: { id: string }, converted = false) => `/api/music/tracks/${t.id}/stream${converted ? "?converted=true" : ""}`,
  bookCover: (b: { id: string }) => `/api/books/${b.id}/cover`,
  bookFile: (b: { id: string }, download = false) => `/api/books/${b.id}/file${download ? "?download=true" : ""}`,
  bookAudio: (b: { id: string }, part: number, converted = false) => `/api/books/${b.id}/audio/${part}${converted ? "?converted=true" : ""}`,
  bookPage: (b: { id: string }, page: number, width: number) => `/api/books/${b.id}/pages/${page}?w=${width}`,
};

export function formatBytes(n: number): string {
  if (n < 1024) return digits(`${n} B`);
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return digits(`${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`);
}

export function episodeCode(m: { season: number | null; episode: number | null }): string {
  if (m.episode == null) return m.season != null ? tr("Season {n}", { n: m.season }) : "";
  return tr("S{s} E{e}", { s: m.season ?? 1, e: m.episode });
}

export const AGE_LABEL: Record<number, string> = { 0: tr("All ages"), 7: "7+", 13: "13+", 16: "16+", 18: "18+" };
export const AGE_OPTIONS = [0, 7, 13, 16, 18];

/** "1:23" or "1:02:03" for a number of seconds. */
export function clock(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

/** Parses "1:23", "1:02:03" or "83" into seconds; empty means no value, undefined means invalid. */
export function parseClock(text: string): number | null | undefined {
  const t = text.trim();
  if (!t) return null;
  if (!/^\d+(:\d{1,2}){0,2}$/.test(t)) return undefined;
  return t.split(":").reduce((acc, part) => acc * 60 + Number(part), 0);
}

export function formatDuration(sec: number | null): string {
  if (!sec) return "";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return h ? tr("{h} h {m} min", { h, m }) : digits(`${m}:${String(s).padStart(2, "0")}`);
}
