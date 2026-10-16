import { expect, test } from "@playwright/test";

test("turn on offsite backup, back up now and check it", async ({ page }) => {
  const info = await (await page.request.get("/api/admin/backup")).json();
  test.skip(!info.restic, "restic isn't installed on this server");
  const folder = `/tmp/gharbox-e2e-backup-${Date.now().toString(36)}`;

  await page.goto("/settings#server");
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "Offsite backup" }) });
  if (info.configured) await panel.getByRole("button", { name: "Change" }).click();
  await panel.getByLabel("Where to keep it").selectOption("disk");
  await panel.getByLabel("Folder", { exact: true }).fill(folder);
  await panel.getByRole("button", { name: info.configured ? "Save" : "Turn on offsite backup" }).click();

  // the password is shown so it can be written down
  await expect(panel.getByText("Write down the backup password")).toBeVisible({ timeout: 30_000 });
  await expect(panel.locator(".backup-password code")).toHaveText(/^[a-z2-9]{5}(-[a-z2-9]{5}){5}$|.{12,}/);
  await panel.getByRole("button", { name: "I've written it down" }).click();
  await expect(panel.getByText(folder)).toBeVisible();

  const newest = panel.locator("table.runs tbody tr").first();
  await panel.getByRole("button", { name: "Back up now" }).click();
  await expect(newest).toContainText(/new or changed files/, { timeout: 60_000 });
  await panel.getByRole("button", { name: "Check the backup" }).click();
  await expect(newest).toContainText("Check");
  await expect(newest).toContainText("Readable", { timeout: 60_000 });
  await panel.getByRole("button", { name: "Show saved copies" }).click();
  await expect(panel.getByText(/1 saved copies, newest/)).toBeVisible();

  // the security check now counts the copy away from this PC
  await page.reload();
  await expect(page.getByText("The offsite backup is up to date")).toBeVisible();
});
