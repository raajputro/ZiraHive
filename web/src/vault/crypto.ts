// Vault encryption, done entirely in the browser with Web Crypto.
//
//   passphrase --PBKDF2-SHA256 (600,000 rounds, random salt)--> passphrase key
//   recovery key (32 random bytes, shown once)  --SHA-256-->    recovery key
//   master key (32 random bytes) is stored on the server only wrapped by each of those two keys.
//
//   Every file gets its own random key (32 bytes) and nonce prefix (8 bytes), wrapped by the master key.
//   The file is cut into chunks; chunk i is AES-256-GCM with nonce = prefix || i (4 bytes, big-endian)
//   and additional data = i || last-flag, so chunks can't be swapped, dropped or cut off unnoticed.
//   The name, type and size live in an encrypted JSON blob ("meta") under the file key.
//
//   Wrapped values and meta: base64(iv(12) || AES-GCM ciphertext+tag).

export const KDF_ITERATIONS = 600_000;
export const CHUNK = 1024 * 1024;  // plaintext bytes per encrypted chunk
const TAG = 16;

const enc = new TextEncoder();
const dec = new TextDecoder();

export function secureContextOk(): boolean {
  return typeof crypto !== "undefined" && !!crypto.subtle && window.isSecureContext;
}

export const b64 = (buf: ArrayBuffer | Uint8Array): string => {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
export const unb64 = (s: string): Uint8Array => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
export const random = (n: number) => crypto.getRandomValues(new Uint8Array(n));

async function aesKey(raw: Uint8Array, extractable = false): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", raw, "AES-GCM", extractable, ["encrypt", "decrypt"]);
}

export async function passphraseKey(passphrase: string, salt: Uint8Array, iterations = KDF_ITERATIONS): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey("raw", enc.encode(passphrase.normalize("NFKC")), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, base,
    { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

// Recovery key: 32 random bytes written as 13 groups of 4 letters/digits (base32, no look-alikes).
const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
export function recoveryToText(bytes: Uint8Array): string {
  let bits = 0, value = 0, out = "";
  for (const b of bytes) {
    value = (value << 8) | b; bits += 8;
    while (bits >= 5) { out += ALPHABET[(value >>> (bits - 5)) & 31]; bits -= 5; }
  }
  if (bits > 0) out += ALPHABET[(value << (5 - bits)) & 31];
  return out.match(/.{1,4}/g)!.join("-");
}
export function recoveryFromText(text: string): Uint8Array | null {
  const clean = text.toUpperCase().replace(/[^A-Z0-9]/g, "");
  let bits = 0, value = 0;
  const out: number[] = [];
  for (const c of clean) {
    const v = ALPHABET.indexOf(c);
    if (v < 0) return null;
    value = (value << 5) | v; bits += 5;
    if (bits >= 8) { out.push((value >>> (bits - 8)) & 255); bits -= 8; }
  }
  return out.length >= 32 ? new Uint8Array(out.slice(0, 32)) : null;
}
export async function recoveryKey(bytes: Uint8Array): Promise<CryptoKey> {
  return aesKey(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)));
}

export async function seal(key: CryptoKey, data: Uint8Array): Promise<string> {
  const iv = random(12);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data));
  const out = new Uint8Array(12 + ct.length);
  out.set(iv); out.set(ct, 12);
  return b64(out);
}
export async function open(key: CryptoKey, sealed: string | Uint8Array): Promise<Uint8Array> {
  const raw = typeof sealed === "string" ? unb64(sealed) : sealed;
  return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: raw.subarray(0, 12) }, key, raw.subarray(12)));
}

/** A brand-new vault: master key, its two wrapped copies and the recovery key to show once. */
export async function createVault(passphrase: string) {
  const master = random(32), salt = random(16), recovery = random(32);
  const wrapped_key = await seal(await passphraseKey(passphrase, salt), master);
  const recovery_wrapped_key = await seal(await recoveryKey(recovery), master);
  return { setup: { salt: b64(salt), iterations: KDF_ITERATIONS, wrapped_key, recovery_wrapped_key },
    recoveryText: recoveryToText(recovery), master: await aesKey(master), masterRaw: master };
}

export async function unlockWithPassphrase(v: { salt: string; iterations: number; wrapped_key: string }, passphrase: string) {
  const raw = await open(await passphraseKey(passphrase, unb64(v.salt), v.iterations), v.wrapped_key);
  return { master: await aesKey(raw), masterRaw: raw };
}

export async function unlockWithRecovery(v: { recovery_wrapped_key: string }, text: string) {
  const bytes = recoveryFromText(text);
  if (!bytes) throw new Error("bad recovery key");
  const raw = await open(await recoveryKey(bytes), v.recovery_wrapped_key);
  return { master: await aesKey(raw), masterRaw: raw };
}

/** Re-wrap the same master key under a new passphrase. */
export async function rewrap(masterRaw: Uint8Array, passphrase: string) {
  const salt = random(16);
  return { salt: b64(salt), iterations: KDF_ITERATIONS, wrapped_key: await seal(await passphraseKey(passphrase, salt), masterRaw) };
}

// ------------------------------------------------------------------- files

/** `taken`: when a photo or video was taken (ms), if it came from Photos. */
export interface FileMeta { name: string; type: string; size: number; modified: number; width?: number; height?: number; taken?: number }
export interface FileKey { key: CryptoKey; prefix: Uint8Array }

export const encryptedSize = (plain: number, chunk = CHUNK) => plain + TAG * Math.max(1, Math.ceil(plain / chunk));

export async function newFileKey(master: CryptoKey): Promise<{ fk: FileKey; wrapped: string }> {
  const raw = random(32), prefix = random(8);
  const both = new Uint8Array(40);
  both.set(raw); both.set(prefix, 32);
  return { fk: { key: await aesKey(raw), prefix }, wrapped: await seal(master, both) };
}

export async function openFileKey(master: CryptoKey, wrapped: string): Promise<FileKey> {
  const both = await open(master, wrapped);
  return { key: await aesKey(both.subarray(0, 32)), prefix: both.slice(32, 40) };
}

function chunkParams(fk: FileKey, i: number, last: boolean) {
  const iv = new Uint8Array(12);
  iv.set(fk.prefix);
  new DataView(iv.buffer).setUint32(8, i);
  const ad = new Uint8Array(5);
  new DataView(ad.buffer).setUint32(0, i);
  ad[4] = last ? 1 : 0;
  return { name: "AES-GCM", iv, additionalData: ad };
}

export async function encryptChunk(fk: FileKey, i: number, last: boolean, plain: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.encrypt(chunkParams(fk, i, last), fk.key, plain));
}

export async function decryptChunk(fk: FileKey, i: number, last: boolean, cipher: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.decrypt(chunkParams(fk, i, last), fk.key, cipher));
}

export async function sealMeta(fk: FileKey, meta: FileMeta) { return seal(fk.key, enc.encode(JSON.stringify(meta))); }
export async function openMeta(fk: FileKey, sealed: string): Promise<FileMeta> { return JSON.parse(dec.decode(await open(fk.key, sealed))); }

/** Decrypt a whole downloaded file, chunk by chunk, reporting progress. */
export async function decryptStream(fk: FileKey, body: ReadableStream<Uint8Array>, total: number, chunk: number,
                                    onProgress?: (done: number) => void): Promise<Blob> {
  const reader = body.getReader();
  const parts: BlobPart[] = [];
  const cipherChunk = chunk + TAG;
  let buf = new Uint8Array(0), index = 0, seen = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (value) {
      const next = new Uint8Array(buf.length + value.length);
      next.set(buf); next.set(value, buf.length);
      buf = next;
      seen += value.length;
    }
    while (buf.length >= cipherChunk && (seen < total || buf.length > cipherChunk)) {
      parts.push(await decryptChunk(fk, index++, false, buf.subarray(0, cipherChunk)));
      buf = buf.slice(cipherChunk);
      onProgress?.(seen);
    }
    if (done) break;
  }
  if (seen !== total) throw new Error("incomplete download");
  parts.push(await decryptChunk(fk, index, true, buf));  // the last one (also proves nothing was cut off)
  onProgress?.(seen);
  return new Blob(parts);
}
