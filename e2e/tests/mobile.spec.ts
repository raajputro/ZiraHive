import { expect, test } from "@playwright/test";

test("phone layout: bottom navigation and notifications", async ({ page }) => {
  await page.goto("/photos");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav).toBeVisible();
  const box = await nav.boundingBox();
  expect(box!.y).toBeGreaterThan(600); // pinned to the bottom of the screen
  await nav.getByRole("link", { name: "Files" }).click();
  await expect(page).toHaveURL(/\/files/);
  await page.locator(".mobile-top").getByRole("button", { name: /Notifications/ }).click();
  await expect(page.getByRole("region", { name: "Notifications" })).toBeVisible();
});
