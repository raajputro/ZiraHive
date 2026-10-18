// Putting files into the vault and getting them back out. Everything here runs in the browser:
// the server only ever receives and returns encrypted bytes.
import { api, type VaultItem } from "../api";
import {
  CHUNK, decryptStream, encryptChunk, encryptedSize, newFileKey, open, openFileKey, openMeta, seal, sealMeta, unb64,
  type FileKey, type FileMeta,
} from "./crypto";

export interface Opened { item: VaultItem; fk: FileKey; meta: FileMeta }

export function kindOf(type: string) {
  return type.startsWith("image/") ? "image" : type.startsWith("video/") ? "video" : type.startsWith("audio/") ? "audio" : "file";
}
/** Photos and videos (HEIC/HEIF included, whatever type the browser gave them). */
export const isPhotoMeta = (m: FileMeta) => /^(image|video)\//.test(m.type) || /\.(heic|heif|dng)$/i.test(m.name);

export async function hexSha256(data: Blob | ArrayBuffer): Promise<string> {
  const buf = data instanceof Blob ? await data.arrayBuffer() : data;
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** A small preview, drawn from the file itself or (for HEIC, which browsers can't draw) from `fallback`. */
export async function makeThumb(file: Blob, fallback?: Blob | null): Promise<{ blob: Blob; width: number; height: number } | null> {
  const draw = async (src: Blob) => {
    let source: CanvasImageSource, w: number, h: number;
    if (src.type.startsWith("video/")) {
      const v = document.createElement("video");
      v.muted = true; v.preload = "metadata"; v.src = URL.createObjectURL(src);
      try {
        await new Promise((res, rej) => { v.onloadeddata = res; v.onerror = rej; setTimeout(rej, 8000); });
        v.currentTime = Math.min(1, (v.duration || 2) / 2);
        await new Promise((res) => { v.onseeked = res; setTimeout(res, 3000); });
        source = v; w = v.videoWidth; h = v.videoHeight;
      } finally { setTimeout(() => URL.revokeObjectURL(v.src), 1000); }
    } else {
      const bmp = await createImageBitmap(src);
      source = bmp; w = bmp.width; h = bmp.height;
    }
    const scale = Math.min(1, 480 / Math.max(w, h));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(w * scale)); c.height = Math.max(1, Math.round(h * scale));
    c.getContext("2d")!.drawImage(source, 0, 0, c.width, c.height);
    const blob = await new Promise<Blob | null>((res) => c.toBlob(res, "image/webp", 0.8));
    return blob ? { blob, width: w, height: h } : null;
  };
  try { return await draw(file); } catch { /* e.g. HEIC */ }
  if (fallback) { try { return await draw(fallback); } catch { /* give up: shown with an icon */ } }
  return null;
}

/** Encrypt `file` and upload it into the vault. Returns the finished item. */
export async function encryptAndUpload(master: CryptoKey, file: File, opts: { taken?: number; thumbFrom?: Blob | null } = {},
                                       onProgress?: (done: number) => void): Promise<VaultItem> {
  const { fk, wrapped } = await newFileKey(master);
  const thumb = await makeThumb(file, opts.thumbFrom);
  const meta: FileMeta = { name: file.name, type: file.type || "application/octet-stream", size: file.size, modified: file.lastModified,
    width: thumb?.width, height: thumb?.height, ...(opts.taken ? { taken: opts.taken } : {}) };
  const item = await api.createVaultItem({ size: encryptedSize(file.size), chunk_size: CHUNK, wrapped_key: wrapped, meta: await sealMeta(fk, meta) });
  try {
    const n = Math.max(1, Math.ceil(file.size / CHUNK));
    let offset = 0, last: VaultItem = item;
    for (let i = 0; i < n; i++) {
      const plain = new Uint8Array(await file.slice(i * CHUNK, (i + 1) * CHUNK).arrayBuffer());
      const cipher = await encryptChunk(fk, i, i === n - 1, plain);
      for (let attempt = 0; ; attempt++) {
        try { last = await api.vaultChunk(item.id, offset, cipher); break; }
        catch (e) { if (attempt >= 3) throw e; await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt)); }
      }
      offset += cipher.length;
      onProgress?.(Math.min(file.size, (i + 1) * CHUNK));
    }
    if (!last.complete) throw new Error("The upload didn't finish");
    if (thumb) await api.vaultThumb(item.id, unb64(await seal(fk.key, new Uint8Array(await thumb.blob.arrayBuffer()))));
    return last;
  } catch (e) {
    await api.deleteVaultItem(item.id).catch(() => undefined);  // don't leave half an item behind
    throw e;
  }
}

/** Download and decrypt a whole item. */
export async function decryptItem(o: Opened, onProgress?: (done: number) => void): Promise<Blob> {
  const res = await fetch(`/api/vault/items/${o.item.id}/data`, { credentials: "same-origin" });
  if (!res.ok || !res.body) throw new Error(String(res.status));
  const blob = await decryptStream(o.fk, res.body, o.item.size, o.item.chunk_size, onProgress);
  return new Blob([blob], { type: o.meta.type });
}

export async function openItem(master: CryptoKey, item: VaultItem): Promise<Opened> {
  const fk = await openFileKey(master, item.wrapped_key);
  return { item, fk, meta: await openMeta(fk, item.meta) };
}

/** Everything in the vault this key can read (anything else is skipped). */
export async function openAll(master: CryptoKey): Promise<Opened[]> {
  const out: Opened[] = [];
  for (const item of await api.vaultItems()) {
    try { out.push(await openItem(master, item)); } catch { /* not ours to read */ }
  }
  return out;
}

/** Decrypted thumbnails, a few at a time. Calls `got` for each; returns the object URLs made. */
export async function loadThumbs(items: Opened[], got: (id: string, url: string) => void, isCancelled: () => boolean): Promise<string[]> {
  const made: string[] = [];
  const queue = items.filter((o) => o.item.has_thumb);
  const worker = async () => {
    for (let o = queue.shift(); o && !isCancelled(); o = queue.shift()) {
      try {
        const res = await fetch(`/api/vault/items/${o.item.id}/thumb`, { credentials: "same-origin" });
        const plain = await open(o.fk.key, new Uint8Array(await res.arrayBuffer()));
        const url = URL.createObjectURL(new Blob([plain], { type: "image/webp" }));
        made.push(url);
        got(o.item.id, url);
      } catch { /* leave the icon */ }
    }
  };
  await Promise.all([worker(), worker(), worker(), worker()]);
  return made;
}
