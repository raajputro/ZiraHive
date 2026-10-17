import { expect, test } from "@playwright/test";
import { unique } from "./helpers";

// The server under test links to itself: it shares a category, then adds its own code, so the
// whole round trip (code, token, proxied streaming) runs for real over HTTP.
test("share a category with another GharBox, add the code there, watch from the linked shelf", async ({ page }) => {
  const titles = await (await page.request.get("/api/titles?q=Big%20Garden")).json();
  const film = titles.find((t: { type: string }) => t.type === "movie");
  test.skip(!film, "Needs the WebM sample (scripts/make-sample-media.sh)");
  const libs = await (await page.request.get("/api/libraries")).json();
  const lib = libs.find((l: { id: string }) => l.id === film.library_id);
  const who = unique("cousins");

  await page.goto("/settings#server");
  const panel = page.locator("section.links-panel");
  await panel.getByLabel("Who is it for?").fill(who);
  await panel.getByRole("checkbox", { name: lib.name }).check();
  await panel.getByRole("button", { name: "Make a link code" }).click();
  const code = await page.getByRole("dialog").getByLabel("Link code", { exact: true }).inputValue();
  expect(code).toMatch(/^ghx1\./);
  await page.getByRole("button", { name: "Close" }).click();
  await expect(panel.locator(".link-list strong", { hasText: who })).toBeVisible();

  await panel.getByLabel("Link code from the other GharBox").fill(code);
  await panel.getByRole("button", { name: "Link", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Linked with");

  await page.goto("/watch");
  const shelf = page.locator(".shelf-block", { hasText: "from" }).filter({ hasText: lib.name }).first();
  await expect(shelf).toBeVisible();
  await shelf.getByRole("link", { name: /Big Garden/ }).first().click();
  await expect(page).toHaveURL(/\/play\/link\//);
  await page.locator("video").evaluate((v: HTMLVideoElement) => { v.muted = true; return v.play(); });
  await expect.poll(() => page.locator("video").evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 15_000 }).toBeGreaterThan(0.5);

  // tidy up both sides
  await page.goto("/settings#server");
  page.on("dialog", (d) => d.accept());
  const linkRows = panel.locator("li", { has: page.getByRole("button", { name: /^Remove / }) });
  while (await linkRows.count()) { await linkRows.first().getByRole("button").click(); await page.waitForTimeout(300); }
  await panel.getByRole("button", { name: `Stop sharing with ${who}` }).click();
  await expect(panel.locator(".link-list strong", { hasText: who })).toBeHidden();
});
