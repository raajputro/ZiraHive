import { expect, test, type Page } from "@playwright/test";

const audio = (p: Page) => p.locator("audio");
const playing = (p: Page) => audio(p).evaluate((a: HTMLAudioElement) => !a.paused && a.currentTime > 0);

test.beforeEach(async ({ page }) => {
  const libs = await (await page.request.get("/api/libraries")).json();
  test.skip(!libs.some((l: { kind: string; item_count: number }) => l.kind === "music" && l.item_count > 0),
    "No music on this server (scripts/make-sample-media.sh makes some)");
});

test("play an album, use the queue, favourite a song and make a playlist", async ({ page }) => {
  await page.goto("/listen/albums");
  await page.getByRole("link", { name: /Monsoon Songs/ }).click();
  await expect(page.getByRole("heading", { name: "Monsoon Songs" })).toBeVisible();
  await page.getByRole("button", { name: "Play", exact: true }).click();

  const bar = page.getByRole("region", { name: "Now playing" });
  await expect(bar).toContainText("Rain on Tin");
  await expect.poll(() => playing(page), { timeout: 10_000 }).toBe(true);

  // the music keeps playing while you move around the app
  await page.getByRole("link", { name: "Photos" }).first().click();
  await expect(bar).toContainText("Rain on Tin");
  expect(await playing(page)).toBe(true);
  await page.goBack();

  await bar.getByRole("button", { name: "Next" }).click();
  await expect(bar).toContainText("Rickshaw Bell");

  // the full panel and the queue
  await bar.getByRole("button", { name: "Open now playing" }).click();
  const panel = page.getByRole("dialog", { name: "Now playing" });
  await expect(panel.getByRole("heading", { name: "Rickshaw Bell" })).toBeVisible();
  await panel.getByRole("button", { name: "Queue" }).click();
  await panel.getByRole("button", { name: /^Evening Tea/ }).click();
  await expect(bar).toContainText("Evening Tea");
  await panel.getByRole("button", { name: "Close" }).click();

  // favourite, then make a playlist from the song menu
  await page.getByRole("button", { name: "Add Evening Tea to favourites" }).click();
  await page.getByRole("button", { name: "More for Evening Tea" }).click();
  await page.getByRole("menuitem", { name: "Add to playlist…" }).click();
  const name = `Tea time ${Date.now().toString(36)}`;
  await page.getByLabel("New playlist").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText(`Made ${name} with Evening Tea.`)).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();

  await page.goto("/listen/playlists");
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page.getByRole("button", { name: "Play Evening Tea" })).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete playlist" }).click();
  await expect(page).toHaveURL(/\/listen\/playlists$/);

  await page.goto("/listen/songs?favorites=1");
  await expect(page.getByRole("button", { name: "Play Evening Tea" })).toBeVisible();
  await page.getByRole("button", { name: "Remove Evening Tea from favourites" }).click();
});

test("a WMA song is converted, then plays", async ({ page }) => {
  await page.goto("/listen/songs");
  await page.getByLabel("Search songs").fill("Old Radio");
  await page.getByRole("button", { name: "Play Old Radio" }).click();
  await expect.poll(() => playing(page), { timeout: 20_000 }).toBe(true);
  await page.getByRole("region", { name: "Now playing" }).getByRole("button", { name: "Stop and close" }).click();
});

test("an audiobook remembers where you stopped, with chapters and speed", async ({ page }) => {
  await page.goto("/listen/audiobooks");
  await page.getByRole("link", { name: /The River Journey/ }).click();
  const book = page.url().split("/").pop()!;
  await page.request.delete(`/api/books/${book}/progress`);
  await page.reload();
  await page.getByRole("button", { name: /Chapter 2: The Delta/ }).click();
  const bar = page.getByRole("region", { name: "Now playing" });
  await expect(bar).toContainText("Chapter 2: The Delta");
  await expect.poll(() => playing(page)).toBe(true);
  await expect.poll(() => audio(page).evaluate((a: HTMLAudioElement) => a.currentTime)).toBeGreaterThan(4.3);

  await bar.getByRole("button", { name: "Open now playing" }).click();
  const panel = page.getByRole("dialog", { name: "Now playing" });
  await panel.getByLabel("Speed").selectOption("1.5");
  expect(await audio(page).evaluate((a: HTMLAudioElement) => a.playbackRate)).toBe(1.5);
  await panel.getByRole("button", { name: "Pause" }).click();
  await panel.getByRole("button", { name: "Close" }).click();

  // pausing saves the position
  await expect.poll(async () => (await (await page.request.get(`/api/books/${book}`)).json()).progress?.position ?? 0).toBeGreaterThan(4);
  await page.reload();
  await expect(page.getByRole("button", { name: /Resume from 0:0[4-9]/ })).toBeVisible();
  await page.goto("/listen");
  await expect(page.getByRole("heading", { name: "Continue listening" })).toBeVisible();
});
