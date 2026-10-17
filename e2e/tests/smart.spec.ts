import { expect, test } from "@playwright/test";
import { createUser, unique } from "./helpers";
import * as zlib from "node:zlib";

/** A small PNG with a pattern of its own, so its fingerprint is real (not a flat colour). */
function patterned(seed: number, w = 64, h = 48): Buffer {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (w * 3 + 1)] = 0;
    for (let x = 0; x < w; x++) {
      const v = ((x * (seed + 3) + y * (seed + 7)) % 64) < 32 ? 230 : 25;
      const o = y * (w * 3 + 1) + 1 + x * 3;
      raw[o] = v; raw[o + 1] = (v + seed * 40) % 256; raw[o + 2] = 255 - v;
    }
  }
  const crcTable = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (b: Buffer) => { let c = 0xffffffff; for (const x of b) c = crcTable[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (t: string, d: Buffer) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([l, td, c]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
}

test("clean up: duplicates found and removed, the best copy kept (a fresh account, nothing else touched)", async ({ page, browser, baseURL }) => {
  const name = unique("tidy");
  await createUser(page.request, name, "tidy-password-123");
  const ctx = await browser.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
  const p = await ctx.newPage();
  expect((await p.request.post("/api/auth/login", { data: { username: name, password: "tidy-password-123" } })).ok()).toBeTruthy();
  const same = patterned(1);
  for (const [file, data] of [["a.png", same], ["a again.png", same], ["other.png", patterned(5)]] as const) {
    const up = await (await p.request.post("/api/uploads", { data: { filename: file, size: data.length, folder: "/Camera", dedupe: false } })).json();
    await p.request.patch(`/api/uploads/${up.id}`, { data, headers: { "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream" } });
  }
  await expect.poll(async () => (await (await p.request.get("/api/photos/cleanup")).json()).duplicates.length, { timeout: 20_000 }).toBe(1);

  await p.goto("/photos/cleanup");
  await expect(p.locator(".dupe-group figure")).toHaveCount(2);
  await expect(p.locator(".dupe-group figure.keep")).toHaveCount(1);
  await p.getByRole("button", { name: /Keep the best of each, remove 1 copies/ }).click();
  await expect(p.getByText("No duplicates.")).toBeVisible();
  const trash = await (await p.request.get("/api/trash")).json();
  expect(trash).toHaveLength(1);
  await ctx.close();
});

test("photo search, people and Ask explain when the local AI is off", async ({ page }) => {
  const st = await (await page.request.get("/api/ai/status")).json();
  test.skip(st.ai || st.ollama, "the local AI is running here");
  await page.goto("/photos");
  await page.getByLabel("Search photos by what's in them").fill("beach");
  await page.getByLabel("Search photos by what's in them").press("Enter");
  await expect(page).toHaveURL(/\/photos\/search\?q=beach/);
  await expect(page.getByRole("heading", { name: "Needs the local AI" })).toBeVisible();
  await page.getByRole("link", { name: "People" }).click();
  await expect(page.getByText("Faces are found by the local AI")).toBeVisible();
  await page.goto("/ask");
  await expect(page.getByText("This needs the local AI, which isn't running")).toBeVisible();
});
