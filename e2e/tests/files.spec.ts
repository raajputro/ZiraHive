import { expect, test } from "@playwright/test";
import { unique, uploadViaUi } from "./helpers";

test("folders, upload, rename, trash and restore", async ({ page }) => {
  const folder = unique("E2E Folder");
  await page.goto("/files");
  page.once("dialog", (d) => d.accept(folder));
  await page.getByRole("button", { name: "New folder" }).click();
  await page.getByRole("link", { name: folder }).click();
  await expect(page.getByText("This folder is empty")).toBeVisible();

  await uploadViaUi(page, [{ name: "receipt.txt", mimeType: "text/plain", buffer: Buffer.from(`paid ${folder}`) }]);
  const row = page.getByRole("row", { name: /receipt\.txt/ });
  await expect(row).toBeVisible();

  page.once("dialog", (d) => d.accept("receipt-march.txt"));
  await page.getByRole("button", { name: "Rename receipt.txt" }).click();
  await expect(page.getByRole("row", { name: /receipt-march\.txt/ })).toBeVisible();

  await page.getByRole("button", { name: "Move receipt-march.txt to trash" }).click();
  await expect(page.getByText("This folder is empty")).toBeVisible();

  await page.getByRole("link", { name: "Trash" }).first().click();
  await page.getByRole("button", { name: "Restore receipt-march.txt" }).first().click();
  await page.goto(`/files/${encodeURIComponent(folder)}`);
  await expect(page.getByRole("row", { name: /receipt-march\.txt/ })).toBeVisible();
});

test("uploading the same document again keeps the old version", async ({ page }) => {
  const folder = unique("E2E Versions");
  await page.request.post("/api/folders", { data: { path: `/${folder}` } });
  await page.goto(`/files/${encodeURIComponent(folder)}`);
  await uploadViaUi(page, [{ name: "plan.md", mimeType: "text/markdown", buffer: Buffer.from("first draft") }]);
  await uploadViaUi(page, [{ name: "plan.md", mimeType: "text/markdown", buffer: Buffer.from("second draft, longer") }]);
  await expect(page.getByRole("row", { name: /plan/ })).toHaveCount(1);
  await page.getByRole("button", { name: "Versions of plan.md" }).click();
  const dialog = page.getByRole("dialog", { name: "Versions of plan.md" });
  await expect(dialog.getByRole("button", { name: "Restore this version" })).toHaveCount(1);
  await dialog.getByRole("button", { name: "Restore this version" }).click();
  await expect(dialog.getByRole("status")).toContainText("Restored");
  const content = await (await page.request.get(await page.getByRole("link", { name: "Download plan.md" }).getAttribute("href") as string)).text();
  expect(content).toBe("first draft");
});
