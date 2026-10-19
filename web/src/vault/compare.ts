// Duplicate and blurry photos, and duplicate documents, in the vault. The server can't read vault
// files, so all of this runs here in the browser on the decrypted thumbnails and files. The rules
// match the server's (server/app/services/photo_quality.py and doc_compare.py).
import { decryptItem, FOLDER_TYPE, hexSha256, isPhotoMeta, kindOf, type Opened } from "./files";

// ------------------------------------------------------------------ photos

export const SAME = 5;        // at most this many of 64 bits different: the same picture
export const BLURRY = 60;     // sharpness below this: likely blurry

export interface PhotoPrint { hash: bigint; sharpness: number }

function gray(img: ImageBitmap, w: number, h: number): Float32Array {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(img, 0, 0, w, h);
  const px = ctx.getImageData(0, 0, w, h).data;
  const out = new Float32Array(w * h);
  for (let i = 0; i < out.length; i++) out[i] = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2];
  return out;
}

/** A 64-bit "difference hash" (each bit: is this pixel darker than the one to its right, on a
 * 9x8 version) and the sharpness (variance of the Laplacian, on a version at most 512 px). */
export async function printPhoto(thumb: Blob): Promise<PhotoPrint> {
  const img = await createImageBitmap(thumb);
  try {
    const small = gray(img, 9, 8);
    let hash = 0n;
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) hash = (hash << 1n) | (small[y * 9 + x + 1] > small[y * 9 + x] ? 1n : 0n);
    const scale = Math.min(1, 512 / Math.max(img.width, img.height));
    const w = Math.max(3, Math.round(img.width * scale)), h = Math.max(3, Math.round(img.height * scale));
    const g = gray(img, w, h);
    let sum = 0, sum2 = 0, n = 0;
    for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const lap = g[i - 1] + g[i + 1] + g[i - w] + g[i + w] - 4 * g[i];
      sum += lap; sum2 += lap * lap; n++;
    }
    const mean = sum / n;
    return { hash, sharpness: Math.round((sum2 / n - mean * mean) * 100) / 100 };
  } finally { img.close(); }
}

export function bitsApart(a: bigint, b: bigint): number {
  let x = a ^ b, n = 0;
  while (x) { x &= x - 1n; n++; }
  return n;
}

/** Groups of ids whose pictures look the same. Banding as on the server: 8 bands of 8 bits, so two
 * hashes within 7 bits always share a band and only those pairs are compared. */
export function photoGroups(prints: Map<string, PhotoPrint>, same = SAME): string[][] {
  const ids = [...prints.keys()].filter((id) => prints.get(id)!.hash !== 0n);  // a plain one-colour picture says nothing
  const parent = new Map(ids.map((id) => [id, id]));
  const find = (x: string): string => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x)!)!); x = parent.get(x)!; } return x; };
  const buckets = new Map<string, string[]>();
  for (const id of ids) {
    const h = prints.get(id)!.hash;
    for (let b = 0; b < 8; b++) {
      const key = `${b}:${(h >> BigInt(56 - 8 * b)) & 0xffn}`;
      const list = buckets.get(key) ?? [];
      list.push(id);
      buckets.set(key, list);
    }
  }
  for (const list of buckets.values()) {
    for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
      if (bitsApart(prints.get(list[i])!.hash, prints.get(list[j])!.hash) <= same) {
        const a = find(list[i]), b = find(list[j]);
        if (a !== b) parent.set(b, a);
      }
    }
  }
  const groups = new Map<string, string[]>();
  for (const id of ids) { const r = find(id); groups.set(r, [...(groups.get(r) ?? []), id]); }
  return [...groups.values()].filter((g) => g.length > 1);
}

export interface PhotoCleanup { duplicates: { keep: string; ids: string[] }[]; blurry: string[] }

/** Duplicate groups (best first: most pixels, then sharpest, then largest file) and blurry photos.
 * `thumbs` maps item id to its decrypted thumbnail (an object URL the vault page already made). */
export async function cleanUpPhotos(items: Opened[], thumbs: Record<string, string>,
                                    onProgress: (done: number, total: number) => void, isCancelled: () => boolean): Promise<PhotoCleanup> {
  const photos = items.filter((o) => isPhotoMeta(o.meta) && kindOf(o.meta.type, o.meta.name) === "image" && thumbs[o.item.id]);
  const prints = new Map<string, PhotoPrint>();
  for (const [i, o] of photos.entries()) {
    if (isCancelled()) break;
    try { prints.set(o.item.id, await printPhoto(await (await fetch(thumbs[o.item.id])).blob())); } catch { /* skip it */ }
    if (i % 10 === 9) { onProgress(i + 1, photos.length); await new Promise((r) => setTimeout(r)); }
  }
  onProgress(photos.length, photos.length);
  const byId = new Map(photos.map((o) => [o.item.id, o]));
  const rank = (id: string) => {
    const o = byId.get(id)!;
    return [(o.meta.width ?? 0) * (o.meta.height ?? 0), prints.get(id)!.sharpness, o.meta.size];
  };
  const better = (a: string, b: string) => {
    const ra = rank(a), rb = rank(b);
    for (let i = 0; i < ra.length; i++) if (ra[i] !== rb[i]) return rb[i] - ra[i];
    return 0;
  };
  const duplicates = photoGroups(prints).map((g) => { const ids = g.sort(better); return { keep: ids[0], ids }; })
    .sort((a, b) => b.ids.length - a.ids.length);
  const grouped = new Set(duplicates.flatMap((g) => g.ids));
  const blurry = [...prints.entries()].filter(([id, p]) => p.sharpness < BLURRY && !grouped.has(id))
    .sort((a, b) => a[1].sharpness - b[1].sharpness).map(([id]) => id);
  return { duplicates, blurry };
}

// ------------------------------------------------------------------ documents

export const SIMILAR = 0.8;   // share of 3-word phrases two documents must have in common
const MIN_WORDS = 30;
const MAX_READ = 50 * 1024 * 1024;  // bigger files are only compared as exact copies (by size first)
const TEXT_EXT = /\.(txt|md|csv|json|log|srt|html?|xml)$/i;

/** Letters, digits and combining marks, so Bangla words aren't split at vowel signs. */
const WORD = /[\p{L}\p{N}\p{M}_]+/gu;

function hash32(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return h >>> 0;
}

export function shingles(text: string): Set<number> {
  const words = text.toLowerCase().match(WORD) ?? [];
  const out = new Set<number>();
  if (words.length < MIN_WORDS) return out;
  for (let i = 0; i + 2 < words.length; i++) out.add(hash32(`${words[i]} ${words[i + 1]} ${words[i + 2]}`));
  return out;
}

export function jaccard(a: Set<number>, b: Set<number>): number {
  if (!a.size || !b.size) return 0;
  const [small, big] = a.size < b.size ? [a, b] : [b, a];
  let both = 0;
  for (const x of small) if (big.has(x)) both++;
  return both / (a.size + b.size - both);
}

export async function pdfText(blob: Blob): Promise<string> {
  const pdfjs = await import("pdfjs-dist");
  const worker = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
  pdfjs.GlobalWorkerOptions.workerSrc = worker;
  const doc = await pdfjs.getDocument({ data: new Uint8Array(await blob.arrayBuffer()), isEvalSupported: false }).promise;
  try {
    const parts: string[] = [];
    for (let p = 1; p <= Math.min(doc.numPages, 300); p++) {
      const content = await (await doc.getPage(p)).getTextContent();
      parts.push(content.items.map((it) => ("str" in it ? it.str : "")).join(" "));
    }
    return parts.join("\n");
  } finally { void doc.destroy(); }
}

async function readText(o: Opened, blob: Blob): Promise<string | null> {
  if (/\.pdf$/i.test(o.meta.name) || o.meta.type === "application/pdf") return pdfText(blob);
  if (TEXT_EXT.test(o.meta.name) || o.meta.type.startsWith("text/")) return blob.text();
  return null;  // Word, Excel and the like: exact copies only
}

export interface DocCleanupGroup { keep: string; same: boolean; similarity: number; ids: string[] }

/** Documents in the vault that are copies or edited versions of each other; the newest is kept.
 * Each file is decrypted at most once. */
export async function cleanUpDocuments(items: Opened[], onProgress: (done: number, total: number) => void,
                                       isCancelled: () => boolean): Promise<DocCleanupGroup[]> {
  const docs = items.filter((o) => o.meta.type !== FOLDER_TYPE && o.item.complete && o.meta.size > 0
    && kindOf(o.meta.type, o.meta.name) === "file" && !isPhotoMeta(o.meta));
  const sizeCount = new Map<number, number>();
  for (const o of docs) sizeCount.set(o.meta.size, (sizeCount.get(o.meta.size) ?? 0) + 1);
  const readable = (o: Opened) => o.meta.size <= MAX_READ
    && (/\.pdf$/i.test(o.meta.name) || o.meta.type === "application/pdf" || TEXT_EXT.test(o.meta.name) || o.meta.type.startsWith("text/"));
  // exact copies have the same size, so only files sharing a size need their contents hashed
  const todo = docs.filter((o) => (sizeCount.get(o.meta.size)! > 1 && o.meta.size <= 4 * MAX_READ) || readable(o));
  const sha = new Map<string, string>();
  const sets = new Map<string, Set<number>>();
  for (const [i, o] of todo.entries()) {
    if (isCancelled()) break;
    onProgress(i, todo.length);
    try {
      const blob = await decryptItem(o);
      if (sizeCount.get(o.meta.size)! > 1) sha.set(o.item.id, await hexSha256(blob));
      if (readable(o)) {
        const text = await readText(o, blob).catch(() => null);
        const sh = text ? shingles(text) : new Set<number>();
        if (sh.size) sets.set(o.item.id, sh);
      }
    } catch { /* couldn't decrypt or read it: leave it out */ }
  }
  onProgress(todo.length, todo.length);

  const parent = new Map(docs.map((o) => [o.item.id, o.item.id]));
  const find = (x: string): string => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x)!)!); x = parent.get(x)!; } return x; };
  const sims: { a: string; b: string; s: number }[] = [];
  const join = (a: string, b: string, s: number) => { const ra = find(a), rb = find(b); if (ra !== rb) parent.set(rb, ra); sims.push({ a, b, s }); };
  const bySha = new Map<string, string[]>();
  for (const [id, h] of sha) bySha.set(h, [...(bySha.get(h) ?? []), id]);
  for (const ids of bySha.values()) for (const other of ids.slice(1)) join(ids[0], other, 1);
  // edited versions: compare texts whose sizes could reach the threshold (a set can't overlap
  // another by 80% when it is less than 80% of its size)
  const withText = [...sets.entries()].sort((x, y) => x[1].size - y[1].size);
  for (let i = 0; i < withText.length; i++) {
    for (let j = i + 1; j < withText.length; j++) {
      if (withText[i][1].size < SIMILAR * withText[j][1].size) break;
      const s = jaccard(withText[i][1], withText[j][1]);
      if (s >= SIMILAR) join(withText[i][0], withText[j][0], Math.round(s * 1000) / 1000);
    }
  }

  const byId = new Map(docs.map((o) => [o.item.id, o]));
  const newest = (o: Opened) => o.meta.modified ?? Date.parse(o.item.created_at);
  const members = new Map<string, string[]>();
  for (const o of docs) { const r = find(o.item.id); members.set(r, [...(members.get(r) ?? []), o.item.id]); }
  const out: DocCleanupGroup[] = [];
  for (const ids of members.values()) {
    if (ids.length < 2) continue;
    const inside = new Set(ids);
    const groupSims = sims.filter((x) => inside.has(x.a) && inside.has(x.b)).map((x) => x.s);
    ids.sort((a, b) => newest(byId.get(b)!) - newest(byId.get(a)!) || byId.get(b)!.meta.size - byId.get(a)!.meta.size);
    const shas = new Set(ids.map((id) => sha.get(id) ?? id));
    out.push({ keep: ids[0], ids, same: shas.size === 1, similarity: groupSims.length ? Math.min(...groupSims) : 1 });
  }
  return out.sort((a, b) => b.ids.length - a.ids.length);
}
