import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** A name that won't clash with earlier runs against the same server. */
export const unique = (prefix: string) => `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;

/** A tiny valid PNG in a given colour, so each upload has different bytes. */
export function png(r: number, g: number, b: number): Buffer {
  // 1x1 RGB PNG built by hand: signature, IHDR, IDAT (zlib stored block), IEND
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => { let c = 0xffffffff; for (const x of buf) c = crcTable[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type), data]);
    const c = Buffer.alloc(4); c.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, c]);
  };
  const ihdr = Buffer.from([0, 0, 0, 1, 0, 0, 0, 1, 8, 2, 0, 0, 0]);
  const raw = Buffer.from([0, r, g, b]);
  let a = 1, bsum = 0;
  for (const x of raw) { a = (a + x) % 65521; bsum = (bsum + a) % 65521; }
  const adler = Buffer.alloc(4); adler.writeUInt32BE(((bsum << 16) | a) >>> 0);
  const idat = Buffer.concat([Buffer.from([0x78, 0x01, 0x01, raw.length, 0, (~raw.length) & 0xff, 0xff]), raw, adler]);
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", idat), chunk("IEND", Buffer.alloc(0))]);
}

/** Upload through the real web UI file picker and wait for the tray to finish. */
export async function uploadViaUi(page: Page, files: { name: string; mimeType: string; buffer: Buffer }[]) {
  await page.locator('input[type="file"]').setInputFiles(files);
  await expect(page.locator(".tray header strong")).toHaveText(/uploaded/, { timeout: 30_000 });
}

export async function createUser(api: APIRequestContext, username: string, password: string) {
  const r = await api.post("/api/users", { data: { username, password } });
  expect(r.ok()).toBeTruthy();
  return r.json();
}
