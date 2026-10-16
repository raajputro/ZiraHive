import { expect, test, type Page } from "@playwright/test";
import { createUser, unique } from "./helpers";

const time = (p: Page) => p.locator("video").evaluate((v: HTMLVideoElement) => v.currentTime);
const paused = (p: Page) => p.locator("video").evaluate((v: HTMLVideoElement) => v.paused);

test("two people watch in sync, pause for each other and chat", async ({ page: host, browser, baseURL }) => {
  const titles = await (await host.request.get("/api/titles?q=Big%20Garden")).json();
  const film = titles.find((t: { type: string }) => t.type === "movie");
  test.skip(!film, "Needs the WebM sample (scripts/make-sample-media.sh)");

  const name = unique("guest");
  await createUser(host.request, name, "guest-password-123");
  const guestCtx = await browser.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
  const guest = await guestCtx.newPage();
  expect((await guest.request.post("/api/auth/login", { data: { username: name, password: "guest-password-123" } })).ok()).toBeTruthy();

  // The host starts a party from the player and invites the guest.
  await host.goto(`/play/${film.id}`);
  await host.getByRole("button", { name: "Watch together" }).click();
  await host.getByRole("checkbox", { name }).check();
  await host.getByRole("button", { name: "Start the party" }).click();
  await expect(host).toHaveURL(/\/party\//);
  await expect(host.getByText("1 watching")).toBeVisible();

  // The guest finds it in the list and joins.
  await guest.goto("/watch/parties");
  await guest.getByRole("link", { name: "Join" }).first().click();
  await expect(guest.getByText("2 watching")).toBeVisible();
  await expect(host.getByText("2 watching")).toBeVisible();

  // Host presses play: both start, close together.
  await host.locator("video").evaluate((v: HTMLVideoElement) => v.play());
  await expect.poll(() => paused(guest), { timeout: 15_000 }).toBe(false);
  await host.waitForTimeout(3000);
  const [a, b] = await Promise.all([time(host), time(guest)]);
  expect(a).toBeGreaterThan(1);
  expect(Math.abs(a - b)).toBeLessThan(1);

  // Guest pauses: the host pauses too, at the same spot.
  await guest.locator("video").evaluate((v: HTMLVideoElement) => v.pause());
  await expect.poll(() => paused(host)).toBe(true);
  await host.waitForTimeout(800);
  expect(Math.abs((await time(host)) - (await time(guest)))).toBeLessThan(0.6);
  await expect(host.getByText(`Last change by ${name}`)).toBeVisible();

  // Guest seeks: the host follows.
  await guest.locator("video").evaluate((v: HTMLVideoElement) => { v.currentTime = 30; });
  await expect.poll(() => time(host)).toBeGreaterThan(29);

  // Chat and reactions reach the other side.
  await guest.getByLabel("Chat message").fill("Pass the popcorn");
  await guest.getByRole("button", { name: "Send" }).click();
  await expect(host.locator(".chat-lines")).toContainText("Pass the popcorn");
  await host.getByRole("button", { name: "React 🔥" }).click();
  await expect(guest.locator(".reactions-layer")).toContainText("🔥");

  // The host ends it for everyone.
  host.once("dialog", (d) => d.accept());
  await host.getByRole("button", { name: "End the party" }).click();
  await expect(guest.getByText("This watch party has ended.")).toBeVisible();
  await guestCtx.close();
});
