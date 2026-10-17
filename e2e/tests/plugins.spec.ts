import { expect, test } from "@playwright/test";

test("plugins: settings, turn on, send a test, see the problem, turn off", async ({ page }) => {
  await page.goto("/settings#server");
  const card = page.locator("article.plugin", { has: page.getByRole("heading", { name: /Webhook/ }) });
  await expect(card).toBeVisible();
  await expect(page.locator("article.plugin", { has: page.getByRole("heading", { name: /Telegram messages/ }) })).toBeVisible();

  const toggle = card.getByRole("checkbox", { name: /On|Off/ });
  if (await toggle.isChecked()) { await toggle.click(); await expect(toggle).not.toBeChecked(); }

  if (!(await card.locator("details").getAttribute("open"))) await card.locator("summary", { hasText: "Settings" }).click();
  // nothing listens on this port, so the test send fails and says why
  await card.getByLabel("Address to send to").fill("http://127.0.0.1:9/hook");
  await card.getByLabel("Signing secret").fill("s3cret");
  await card.getByRole("button", { name: "Save settings" }).click();
  await expect(card.getByRole("status")).toHaveText("Saved.");
  await expect(card.getByLabel("Signing secret")).toHaveAttribute("placeholder", "Saved. Type to change it.");

  await toggle.click();
  await expect(toggle).toBeChecked();
  await card.getByRole("button", { name: "Send a test" }).click();
  await expect(card.getByRole("status")).toContainText("The test failed");

  await toggle.click();
  await expect(toggle).not.toBeChecked();
});
