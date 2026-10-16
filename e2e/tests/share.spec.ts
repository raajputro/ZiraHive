import { expect, test } from "@playwright/test";
import { unique, uploadViaUi } from "./helpers";

test("a password-protected link opens for someone without an account", async ({ page, browser }) => {
  const folder = unique("E2E Share");
  await page.request.post("/api/folders", { data: { path: `/${folder}` } });
  await page.goto(`/files/${encodeURIComponent(folder)}`);
  await uploadViaUi(page, [{ name: "invitation.txt", mimeType: "text/plain", buffer: Buffer.from("Wedding on Friday") }]);

  await page.getByRole("button", { name: "Share invitation.txt" }).click();
  const dialog = page.getByRole("dialog", { name: "Share invitation.txt" });
  await dialog.getByLabel("Password (optional)").fill("biye2026");
  await dialog.getByRole("button", { name: "Create and copy link" }).click();
  const link = await dialog.getByLabel("Share link").first().inputValue();
  expect(link).toMatch(/\/s\/[\w-]+$/);

  const visitor = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const v = await visitor.newPage();
  await v.goto(link);
  await v.getByLabel("Password").fill("wrong");
  await v.getByRole("button", { name: "Open" }).click();
  await expect(v.getByRole("alert")).toHaveText("Wrong password");
  await v.getByLabel("Password").fill("biye2026");
  await v.getByRole("button", { name: "Open" }).click();
  await expect(v.getByRole("heading", { name: "invitation.txt" })).toBeVisible();
  const file = await v.request.get(await v.getByRole("link", { name: "Download invitation.txt" }).getAttribute("href") as string);
  expect(await file.text()).toBe("Wedding on Friday");
  // the visitor can't reach the signed-in app
  await v.goto("/files");
  await expect(v.getByRole("button", { name: "Sign in" })).toBeVisible();
  await visitor.close();

  // deleting the link stops it working
  await dialog.getByRole("button", { name: "Delete link" }).first().click();
  await expect(dialog.getByLabel("Share link")).toHaveCount(0);
  const gone = await page.request.get(`/api/s/${link.split("/s/")[1]}`);
  expect(gone.status()).toBe(404);
});
