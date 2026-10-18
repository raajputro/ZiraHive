// Moving photos between Photos and the vault.
//
// Into the vault: the original is downloaded, checked against its stored SHA-256, encrypted here
// and uploaded; then the vault copy is downloaded again, decrypted and checked once more. Only
// when it reads back byte-for-byte identical is the unencrypted photo deleted for good (not to
// the trash, where it would stay readable for 30 days). Any failure leaves the photo where it was.
import { api, ApiError, url, type Asset } from "../api";
import { decryptItem, encryptAndUpload, hexSha256, openItem, type Opened } from "./files";
import { t as tr } from "../i18n";

const UPLOAD_CHUNK = 8 * 1024 * 1024;

async function fetchBlob(src: string): Promise<Blob> {
  const res = await fetch(src, { credentials: "same-origin" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

export async function moveToVault(master: CryptoKey, a: Asset, onProgress?: (fraction: number) => void): Promise<void> {
  const original = await fetchBlob(url.file(a));
  onProgress?.(0.2);
  if ((await hexSha256(original)) !== a.sha256.toLowerCase()) throw new Error(tr("The photo didn't download completely. Nothing was moved."));
  const thumbFrom = a.thumb_ready ? await fetchBlob(a.kind === "video" ? url.thumb(a) : url.preview(a)).catch(() => null) : null;
  const taken = new Date(a.taken_at ?? a.created_at).getTime();
  const file = new File([original], a.filename, { type: a.mime || original.type, lastModified: taken });
  const item = await encryptAndUpload(master, file, { taken, thumbFrom }, (done) => onProgress?.(0.2 + 0.6 * (done / Math.max(1, file.size))));
  // read it back before anything is deleted
  try {
    const back = await decryptItem(await openItem(master, item));
    if ((await hexSha256(back)) !== a.sha256.toLowerCase()) throw new Error("mismatch");
  } catch {
    await api.deleteVaultItem(item.id).catch(() => undefined);
    throw new Error(tr("The vault copy couldn't be checked. Nothing was moved."));
  }
  onProgress?.(0.9);
  await api.trashAsset(a.id);
  await api.deleteForever(a.id);
  // This browser may still hold the thumbnail and preview in its cache: ask again past the cache
  // so the stored copies are replaced by the server's "not found".
  await Promise.all([url.thumb(a), url.preview(a), url.file(a)].map((u) =>
    fetch(u, { cache: "reload", credentials: "same-origin" }).catch(() => undefined)));
  onProgress?.(1);
}

/** Decrypt a vault photo and put it back in Photos; the vault copy is deleted once the upload is confirmed. */
export async function moveToPhotos(o: Opened, onProgress?: (fraction: number) => void): Promise<void> {
  const blob = await decryptItem(o, (d) => onProgress?.(0.4 * d / Math.max(1, o.item.size)));
  const taken = o.meta.taken ?? o.meta.modified;
  const file = new File([blob], o.meta.name, { type: o.meta.type, lastModified: taken });
  const sha256 = await hexSha256(file);
  let res = await api.uploadCreate({ filename: file.name, size: file.size, folder: "/Uploads", sha256, dedupe: true,
    taken_at: new Date(taken).toISOString() });
  let offset = res.offset;
  while (res.status === "uploading" && res.id) {
    try { res = await api.uploadChunk(res.id, offset, file.slice(offset, offset + UPLOAD_CHUNK)); }
    catch (e) {
      if (e instanceof ApiError && e.status !== 409 && e.status < 500) throw e;
      await new Promise((r) => setTimeout(r, 1500));
      res = await api.uploadStatus(res.id!);
    }
    offset = res.offset;
    onProgress?.(0.4 + 0.55 * offset / Math.max(1, file.size));
  }
  if (!res.asset || res.asset.sha256.toLowerCase() !== sha256) throw new Error(tr("The photo couldn't be put back. It's still in the vault."));
  await api.deleteVaultItem(o.item.id);
  onProgress?.(1);
}
