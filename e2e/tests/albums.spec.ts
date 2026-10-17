import { expect, test } from "@playwright/test";
import { png, unique } from "./helpers";

const rnd = () => Math.floor(Math.random() * 256);

test("select photos, make an album and share it with a family member", async ({ page, browser }) => {
  const album = unique("E2E Album");
  const member = unique("fam").toLowerCase();
  await page.goto("/photos");
  await page.locator('input[type="file"]').setInputFiles([
    // random colours, so the photo backup's duplicate check never matches an earlier run
    { name: `${album}-1.png`, mimeType: "image/png", buffer: png(rnd(), rnd(), rnd()) },
    { name: `${album}-2.png`, mimeType: "image/png", buffer: png(rnd(), rnd(), rnd()) },
  ]);
  await expect(page.locator(".tray header strong")).toHaveText(/uploaded/, { timeout: 30_000 });
  await page.waitForTimeout(2000);
  await page.reload();

  await page.getByRole("button", { name: "Select" }).click();
  await page.getByRole("button", { name: `Select ${album}-1.png` }).click();
  await page.getByRole("button", { name: `Select ${album}-2.png` }).click();
  await expect(page.getByText("2 selected")).toBeVisible();
  await page.getByRole("button", { name: "Add to album" }).click();
  await page.getByRole("button", { name: "New album" }).click();
  await page.getByLabel("Name").fill(album);
  await page.getByRole("button", { name: "Create album" }).click();

  await page.getByRole("link", { name: "Albums" }).click();
  await page.getByRole("link", { name: new RegExp(album) }).click();
  await expect(page.locator(".tile")).toHaveCount(2);

  // share with a family member, who then sees it under Albums
  await page.request.post("/api/users", { data: { username: member, password: "family-pass-1" } });
  await page.getByRole("button", { name: "Share with family" }).click();
  await page.getByLabel(member).check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(`with ${member}`)).toBeVisible();

  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const m = await ctx.newPage();
  await m.goto("/");
  await m.getByLabel("Username").fill(member);
  await m.getByLabel("Password").fill("family-pass-1");
  await m.getByRole("button", { name: "Sign in", exact: true }).click();
  await m.getByRole("link", { name: "Photos" }).first().click();
  await m.getByRole("link", { name: "Albums" }).click();
  await expect(m.getByRole("link", { name: new RegExp(album) })).toContainText("from");
  await ctx.close();
});
