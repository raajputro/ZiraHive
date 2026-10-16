import { expect, test } from "@playwright/test";

test("watch categories, series page and player", async ({ page }) => {
  const libs = await (await page.request.get("/api/libraries")).json();
  const withTitles = libs.filter((l: { item_count: number }) => l.item_count > 0);
  test.skip(withTitles.length === 0, "No media folders on this server (CI creates sample media)");

  await page.goto("/watch");
  const tabs = page.getByRole("navigation", { name: "Categories" });
  for (const l of withTitles) await expect(tabs.getByRole("link", { name: l.name, exact: true })).toBeVisible();

  const series = (await (await page.request.get("/api/titles?sort=title")).json()).find((t: { type: string }) => t.type === "series");
  if (series) {
    await page.goto(`/watch/series/${series.id}`);
    await expect(page.getByRole("heading", { name: series.title })).toBeVisible();
    await page.getByRole("link", { name: /Play S1 E1|Resume|Play/ }).click();
    await expect(page.locator("video")).toBeVisible();
    await expect(page.getByText(series.title).first()).toBeVisible();
  }
});
