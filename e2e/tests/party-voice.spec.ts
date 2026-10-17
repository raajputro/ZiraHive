import { expect, test } from "@playwright/test";
import { createUser, unique } from "./helpers";

// Chrome's fake microphone (a beeping tone) stands in for real voices; see playwright.config.ts.
test("voice chat in a watch party: join, hear each other, mute, leave", async ({ page: host, browser, baseURL }) => {
  const titles = await (await host.request.get("/api/titles?q=Big%20Garden")).json();
  const film = titles.find((t: { type: string }) => t.type === "movie");
  test.skip(!film, "Needs the WebM sample (scripts/make-sample-media.sh)");

  const name = unique("talker");
  await createUser(host.request, name, "guest-password-123");
  const guestCtx = await browser.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
  const guest = await guestCtx.newPage();
  expect((await guest.request.post("/api/auth/login", { data: { username: name, password: "guest-password-123" } })).ok()).toBeTruthy();

  await host.goto(`/play/${film.id}`);
  await host.getByRole("button", { name: "Watch together" }).click();
  await host.getByRole("checkbox", { name }).check();
  await host.getByRole("button", { name: "Start the party" }).click();
  await expect(host).toHaveURL(/\/party\//);
  await guest.goto(host.url());
  await expect(host.getByText("2 watching")).toBeVisible();

  await host.getByRole("button", { name: "Join voice chat" }).click();
  await expect(host.getByText("Waiting for others to join")).toBeVisible();
  await guest.getByRole("button", { name: "Join voice chat" }).click();

  // a real WebRTC connection both ways, through nothing but the two browsers
  await expect(host.getByText(`Talking with ${name}`)).toBeVisible({ timeout: 20_000 });
  await expect(guest.getByText("Talking with")).toBeVisible();
  const hostRow = guest.locator(".people li").filter({ hasText: /^.*host/ }).first();
  await expect(hostRow.locator(".voice-mic")).toBeVisible();
  // the fake microphone beeps: the other side sees them talking
  await expect(host.locator(".people li", { hasText: name }).locator(".voice-mic.talking")).toBeVisible({ timeout: 10_000 });

  await guest.getByRole("button", { name: "Mute" }).click();
  await expect(guest.getByRole("button", { name: "Unmute" })).toBeVisible();
  await host.waitForTimeout(1500);
  await expect(host.locator(".people li", { hasText: name }).locator(".voice-mic.talking")).toHaveCount(0);

  await guest.getByRole("button", { name: "Leave voice" }).click();
  await expect(host.getByText("Waiting for others to join")).toBeVisible();
  await guestCtx.close();
});
