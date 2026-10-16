// Typed client for the GharBox API. Auth uses the httpOnly cookie set at login.

export interface User { id: string; username: string; is_admin: boolean; quota_bytes: number | null; created_at: string }
export interface Asset {
  id: string; folder: string; filename: string; size: number; mime: string;
  kind: "photo" | "video" | "document" | "other"; sha256: string; thumb_ready: boolean;
  width: number | null; height: number | null; duration: number | null;
  taken_at: string | null; created_at: string; deleted_at: string | null;
}
export interface FolderListing { folder: string; folders: string[]; assets: Asset[] }
export interface PhotoPage { items: Asset[]; next_cursor: string | null }
export interface Library { id: string; name: string; path: string; kind: string; last_scan_at: string | null; item_count: number }
export interface Media {
  id: string; library_id: string; title: string; year: number | null; overview: string | null;
  size: number; container: string | null; video_codec: string | null; audio_codec: string | null;
  width: number | null; height: number | null; duration: number | null; poster_ready: boolean;
  added_at: string; browser_playable: boolean; position: number; finished: boolean;
}
export interface Stats {
  users: number; assets: number; asset_bytes: number; photos: number; videos: number;
  documents: number; media_items: number; disk_total: number; disk_free: number; jobs_mode: string;
}
export interface UploadResult { id: string | null; offset: number; size: number; status: "uploading" | "complete" | "exists"; asset: Asset | null }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  let payload: BodyInit | undefined;
  if (body instanceof Blob) payload = body;
  else if (body !== undefined) { payload = JSON.stringify(body); headers["Content-Type"] = "application/json"; }
  const res = await fetch(path, { ...init, method, body: payload, headers, credentials: "same-origin" });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch { /* not JSON */ }
    if (res.status === 401 && path !== "/api/auth/login") window.dispatchEvent(new Event("gharbox:signed-out"));
    throw new ApiError(res.status, message);
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

export const api = {
  setupStatus: () => request<{ needs_setup: boolean }>("GET", "/api/setup/status"),
  setup: (username: string, password: string) => request<{ user: User }>("POST", "/api/setup", { username, password }),
  login: (username: string, password: string) => request<{ user: User }>("POST", "/api/auth/login", { username, password }),
  logout: () => request<void>("POST", "/api/auth/logout"),
  me: () => request<User>("GET", "/api/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("POST", "/api/auth/password", { current_password, new_password }),

  files: (folder: string) => request<FolderListing>("GET", `/api/files${q({ folder })}`),
  createFolder: (path: string) => request<{ path: string }>("POST", "/api/folders", { path }),
  deleteFolder: (path: string) => request<void>("DELETE", `/api/folders${q({ path })}`),
  updateAsset: (id: string, change: { filename?: string; folder?: string }) => request<Asset>("PATCH", `/api/assets/${id}`, change),
  trashAsset: (id: string) => request<void>("DELETE", `/api/assets/${id}`),
  trash: () => request<Asset[]>("GET", "/api/trash"),
  restore: (id: string) => request<Asset>("POST", `/api/trash/${id}/restore`),
  deleteForever: (id: string) => request<void>("DELETE", `/api/trash/${id}`),
  emptyTrash: () => request<void>("DELETE", "/api/trash"),
  photos: (cursor?: string | null) => request<PhotoPage>("GET", `/api/photos${q({ cursor, limit: 200 })}`),

  libraries: () => request<Library[]>("GET", "/api/libraries"),
  addLibrary: (name: string, path: string) => request<Library>("POST", "/api/libraries", { name, path }),
  removeLibrary: (id: string) => request<void>("DELETE", `/api/libraries/${id}`),
  scanLibrary: (id: string) => request<void>("POST", `/api/libraries/${id}/scan`),
  media: (search?: string) => request<Media[]>("GET", `/api/media${q({ q: search })}`),
  continueWatching: () => request<Media[]>("GET", "/api/media/continue"),
  mediaItem: (id: string) => request<Media>("GET", `/api/media/${id}`),
  streamLink: (id: string) => request<{ path: string }>("GET", `/api/media/${id}/link`),
  saveProgress: (id: string, position: number, duration?: number) =>
    request<void>("PUT", `/api/media/${id}/progress`, { position, duration }),

  users: () => request<User[]>("GET", "/api/users"),
  createUser: (username: string, password: string, is_admin: boolean) =>
    request<User>("POST", "/api/users", { username, password, is_admin }),
  deleteUser: (id: string) => request<void>("DELETE", `/api/users/${id}`),
  stats: () => request<Stats>("GET", "/api/admin/stats"),

  uploadCreate: (body: { filename: string; size: number; folder: string; sha256?: string; taken_at?: string }) =>
    request<UploadResult>("POST", "/api/uploads", body),
  uploadChunk: (id: string, offset: number, chunk: Blob, signal?: AbortSignal) =>
    request<UploadResult>("PATCH", `/api/uploads/${id}`, chunk, { headers: { "Upload-Offset": String(offset) }, signal }),
  uploadStatus: (id: string) => request<UploadResult>("GET", `/api/uploads/${id}`),
};

export const url = {
  thumb: (a: Asset) => `/api/assets/${a.id}/thumb`,
  file: (a: Asset, download = false) => `/api/assets/${a.id}/file${download ? "?download=true" : ""}`,
  poster: (m: Media) => `/api/media/${m.id}/poster`,
  stream: (m: Media) => `/api/media/${m.id}/stream`,
};

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
}

export function formatDuration(sec: number | null): string {
  if (!sec) return "";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return h ? `${h}h ${m}m` : `${m}:${String(s).padStart(2, "0")}`;
}
