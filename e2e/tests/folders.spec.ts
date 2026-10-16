import { expect, test } from "@playwright/test";

test("add a category by choosing a folder where it already is", async ({ page }) => {
  const top = await (await page.request.get("/api/admin/folders")).json();
  const drive = top.folders.find((f: { label: string }) => f.label === "M:");
  test.skip(!drive, "Needs a test drive M: with an 'Extra Songs' folder (the local test stack makes one)");
  // a leftover from an earlier run
  for (const l of await (await page.request.get("/api/libraries")).json()) if (l.name === "Extra Songs") await page.request.delete(`/api/libraries/${l.id}`);

  await page.goto("/settings#server");
  await page.getByRole("button", { name: "Choose folder" }).click();
  const dialog = page.getByRole("dialog", { name: "Choose a folder" });
  await dialog.getByRole("button", { name: "M:" }).click();
  await dialog.getByRole("button", { name: "Extra Songs" }).click();
  await expect(dialog.locator("code")).toHaveText("M:\\Extra Songs");
  await dialog.getByRole("button", { name: "Use this folder" }).click();

  // name and type are filled in from the folder's name
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue("Extra Songs");
  await expect(page.locator("form.add-category select")).toHaveValue("music");
  await page.getByRole("button", { name: "Add category" }).click();
  await expect(page.getByText("Category added. Scanning has started.")).toBeVisible();
  await expect(page.getByText("M:\\Extra Songs")).toBeVisible();

  const extra = async () => (await (await page.request.get("/api/libraries")).json()).find((l: { name: string }) => l.name === "Extra Songs");
  await expect.poll(async () => (await extra()).item_count).toBe(1);  // its album was found, in place
  const lib = await extra();
  await page.request.delete(`/api/libraries/${lib.id}`);
});
