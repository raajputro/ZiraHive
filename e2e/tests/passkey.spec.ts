import { expect, test } from "@playwright/test";
import { unique } from "./helpers";

test("add a passkey, sign out, sign in with it", async ({ page }) => {
  const name = unique("laptop");
  // Chrome's built-in stand-in for a phone's fingerprint sensor
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", { options: {
    protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true,
  } });

  await page.goto("/settings#account");
  const panel = page.locator("section.passkeys");
  await panel.getByLabel("Name for this device").fill(name);
  await panel.getByRole("button", { name: "Add a passkey" }).click();
  await expect(panel.getByRole("status")).toContainText(`Passkey "${name}" added`);
  await expect(panel.locator(".passkey-list strong", { hasText: name })).toBeVisible();

  await page.getByRole("button", { name: "Sign out", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Welcome home" })).toBeVisible();
  await page.getByRole("button", { name: "Sign in with a passkey" }).click();
  await expect(page.getByRole("link", { name: "Photos" })).toBeVisible();

  // tidy up: remove it again
  await page.goto("/settings#account");
  page.once("dialog", (d) => d.accept());
  await panel.getByRole("button", { name: `Remove ${name}` }).click();
  await expect(panel.locator(".passkey-list strong", { hasText: name })).toBeHidden();
});
