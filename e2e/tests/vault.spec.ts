import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { png } from "./helpers";
import { PASSWORD } from "../global-setup";

const SECRET = "Bank account notes: keep this private " + Date.now();

test("vault: set up, upload encrypted, lock, unlock by passphrase and by recovery key", async ({ page }) => {
  // start clean (an earlier run may have left a vault)
  await page.request.delete("/api/vault", { data: { password: PASSWORD } });
  await page.goto("/vault");
  await page.getByLabel("Vault passphrase").fill("our quiet river house");
  await page.getByLabel("Type it again").fill("our quiet river house");
  await page.getByRole("button", { name: "Create my vault" }).click();
  const recovery = (await page.getByLabel("Recovery key", { exact: true }).innerText()).trim();
  expect(recovery).toMatch(/^([A-Z2-9]{4}-){12}[A-Z2-9]{4}$/);
  await page.getByLabel("I've saved my recovery key somewhere safe").check();
  await page.getByRole("button", { name: "Open my vault" }).click();

  await page.locator('input[type="file"]').setInputFiles([
    { name: "passport.png", mimeType: "image/png", buffer: png(20, 120, 200) },
    { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from(SECRET) },
  ]);
  await expect(page.getByRole("button", { name: "Open notes.txt" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open passport.png" }).locator("img")).toBeVisible();

  // the server only has scrambled bytes: no PNG header, no text, no names
  const items = await (await page.request.get("/api/vault/items")).json();
  expect(items).toHaveLength(2);
  for (const it of items) {
    const raw = await (await page.request.get(`/api/vault/items/${it.id}/data`)).body();
    expect(raw.includes(Buffer.from("PNG"))).toBe(false);
    expect(raw.includes(Buffer.from("Bank account"))).toBe(false);
    expect(JSON.stringify(it)).not.toContain("notes");
  }

  // open and save the text file
  await page.getByRole("button", { name: "Open notes.txt" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Save" }).click();
  const file = await (await download).path();
  expect(readFileSync(file, "utf8")).toBe(SECRET);
  await page.getByRole("button", { name: "Close" }).click();

  // lock; a wrong passphrase doesn't open it
  await page.getByRole("button", { name: "Lock", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your vault is locked" })).toBeVisible();
  await page.getByLabel("Vault passphrase").fill("wrong guess here");
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByText("That passphrase didn't open the vault.")).toBeVisible();
  await page.getByLabel("Vault passphrase").fill("our quiet river house");
  await page.getByRole("button", { name: "Unlock" }).click();
  await page.getByRole("button", { name: "Open passport.png" }).click();
  await expect(page.getByRole("dialog").getByRole("img", { name: "passport.png" })).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();

  // a reload forgets the key; the recovery key opens it and sets a new passphrase
  await page.reload();
  await page.getByRole("button", { name: "Forgot the passphrase? Use the recovery key" }).click();
  await page.getByLabel("Recovery key", { exact: true }).fill(recovery.toLowerCase());
  await page.getByRole("button", { name: "Unlock" }).click();
  await page.getByLabel("New vault passphrase").fill("a brand new passphrase");
  await page.getByLabel("Type it again").fill("a brand new passphrase");
  await page.getByLabel("Your ZiraHive account password").fill(PASSWORD);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("button", { name: "Open notes.txt" })).toBeVisible();
  await page.reload();
  await page.getByLabel("Vault passphrase").fill("a brand new passphrase");
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByRole("button", { name: "Open notes.txt" })).toBeVisible();

  // delete one file
  await page.getByRole("button", { name: "Open notes.txt" }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete forever" }).click();
  await expect(page.getByRole("button", { name: "Open notes.txt" })).toHaveCount(0);
});
