import { expect, test } from "@playwright/test";

test("switch the interface to Bangla and back; the choice follows the account", async ({ page, browser, baseURL }) => {
  await page.goto("/settings");
  await page.getByLabel("Language").selectOption("bn");
  const nav = page.getByRole("navigation", { name: "প্রধান" });
  await expect(nav.getByRole("link", { name: "ছবি" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "দেখুন" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "bn");
  expect((await (await page.request.get("/api/auth/me")).json()).language).toBe("bn");

  // a new browser signed in to the same account opens in Bangla too
  const other = await browser.newContext({ baseURL, storageState: ".auth/admin.json" });
  const p2 = await other.newPage();
  await p2.goto("/photos");
  await expect(p2.getByRole("navigation", { name: "প্রধান" }).getByRole("link", { name: "শুনুন" })).toBeVisible();
  await other.close();

  // server messages are translated too
  await page.goto("/listen/playlist/does-not-exist");
  await expect(page.getByText("প্লেলিস্ট পাওয়া যায়নি")).toBeVisible();

  await page.goto("/settings");
  await page.getByLabel("ভাষা").selectOption("en");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Photos" })).toBeVisible();
});
