import { expect, test, type Page } from "@playwright/test";

type Title = { id: string; title: string; type: string };

async function findFilm(page: Page) {
  const titles: Title[] = await (await page.request.get("/api/titles?q=Dhaka%20Nights")).json();
  return titles.find((t) => t.type === "movie");
}

// Open-source Chromium can't decode H.264; real Chrome (as in CI) can.
async function needsH264(page: Page) {
  await page.goto("/watch");
  const ok = await page.evaluate(() => MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01E"'));
  test.skip(!ok, "This browser can't play H.264 video. Run with real Chrome: npx playwright install chrome");
}

const playing = (page: Page) => page.waitForFunction(() => {
  const v = document.querySelector("video");
  return !!v && v.currentTime > 0.5 && !v.paused;
}, undefined, { timeout: 30_000 });

test("a film browsers can't play is converted: skip intro, audio, subtitles, quality", async ({ page }) => {
  const film = await findFilm(page);
  test.skip(!film, "Needs the sample film from scripts/make-sample-media.sh");
  await needsH264(page);
  const hls: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/hls/")) hls.push(r.url()); });
  await page.goto(`/play/${film!.id}`);
  await playing(page);
  expect(hls.some((u) => /\/hls\/360p\/0\/seg\/0\.ts/.test(u))).toBeTruthy();

  // the file's Intro chapter gives a Skip intro button
  await page.getByRole("button", { name: "Skip intro" }).click();
  await expect.poll(() => page.evaluate(() => document.querySelector("video")!.currentTime)).toBeGreaterThanOrEqual(5);
  await expect(page.getByRole("button", { name: "Skip intro" })).toBeHidden();

  // English audio: a new stream on audio track 1, continuing from the same moment
  const before = await page.evaluate(() => document.querySelector("video")!.currentTime);
  await page.getByLabel("Audio").selectOption({ label: "English" });
  await expect.poll(() => hls.some((u) => u.includes("/hls/360p/1/"))).toBeTruthy();
  await playing(page);
  expect(await page.evaluate(() => document.querySelector("video")!.currentTime)).toBeGreaterThanOrEqual(before - 1);

  // subtitles from inside the file
  await page.getByLabel("Subtitles").selectOption({ label: "Bangla" });
  await expect.poll(() => page.evaluate(() =>
    Array.from(document.querySelector("video")!.textTracks).find((t) => t.mode === "showing")?.label)).toBe("Bangla");
});

test("make an offline copy and download it", async ({ page }) => {
  const film = await findFilm(page);
  test.skip(!film, "Needs the sample film from scripts/make-sample-media.sh");
  await page.goto(`/play/${film!.id}`);
  const offline = page.locator(".offline");
  await offline.getByLabel("Quality").selectOption("360p");
  await offline.getByRole("button", { name: "Make a copy" }).click();
  const save = offline.getByRole("link", { name: "Save file" });
  await expect(save).toBeVisible({ timeout: 90_000 });
  const download = page.waitForEvent("download");
  await save.click();
  expect((await download).suggestedFilename()).toBe("Dhaka Nights (2024) 360p.mp4");
});

test("next episode counts down when the credits start", async ({ page }) => {
  const titles: Title[] = await (await page.request.get("/api/titles?q=Mirzapur")).json();
  const series = titles.find((t) => t.type === "series");
  test.skip(!series, "Needs the sample series from scripts/make-sample-media.sh");
  await needsH264(page);
  const detail = await (await page.request.put(`/api/series/${series!.id}/markers`, {
    data: { intro_start: null, intro_end: null, credits_before_end: 3 } })).json();
  const [first, second] = detail.seasons[0].episodes;
  await page.goto(`/play/${first.id}`);
  await expect(page.getByText(/Next episode in \d+/)).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Play now" }).click();
  await expect(page).toHaveURL(new RegExp(`/play/${second.id}`));
  await page.request.put(`/api/series/${series!.id}/markers`, { data: { intro_start: null, intro_end: null, credits_before_end: null } });
});
