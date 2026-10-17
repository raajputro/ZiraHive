import { expect, test } from "@playwright/test";
import * as OTPAuth from "otpauth";
import { unique } from "./helpers";

test("two-factor sign-in: set up, then a code is needed to sign in", async ({ page, browser }) => {
  const user = unique("tfa").toLowerCase();
  const password = "two-factor-pass";
  await page.request.post("/api/users", { data: { username: user, password } });

  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const p = await ctx.newPage();
  const signIn = async (code?: string) => {
    await p.goto("/");
    await p.getByLabel("Username").fill(user);
    await p.getByLabel("Password").fill(password);
    await p.getByRole("button", { name: "Sign in", exact: true }).click();
    if (code) {
      await p.getByLabel("Code from your authenticator app").fill(code);
      await p.getByRole("button", { name: "Verify and sign in" }).click();
    }
  };
  await signIn();
  await p.getByRole("link", { name: "Settings" }).first().click();
  await p.getByRole("button", { name: "Set up two-factor sign-in" }).click();
  const secret = (await p.locator(".totp-setup code").textContent())!.trim();
  const totp = new OTPAuth.TOTP({ secret: OTPAuth.Secret.fromBase32(secret) });
  await p.getByLabel("6-digit code from the app").fill(totp.generate());
  await p.getByRole("button", { name: "Turn on" }).click();
  const codes = p.getByRole("dialog", { name: "Save your recovery codes" });
  await expect(codes.locator("li")).toHaveCount(10);
  const recovery = (await codes.locator("li code").first().textContent())!;
  await codes.getByRole("button", { name: "Close" }).click();
  await expect(p.getByText("On. Signing in needs")).toBeVisible();

  await p.getByRole("button", { name: "Sign out" }).first().click();
  await signIn();
  await expect(p.getByLabel("Code from your authenticator app")).toBeVisible();
  await p.getByLabel("Code from your authenticator app").fill("000000");
  await p.getByRole("button", { name: "Verify and sign in" }).click();
  await expect(p.getByRole("alert")).toContainText("didn't work");
  await signIn(recovery);
  await expect(p.getByRole("link", { name: "Photos" }).first()).toBeVisible();
  await ctx.close();

  // the admin's activity log recorded all of it
  await page.goto("/settings#log");
  await expect(page.getByRole("row", { name: new RegExp(`${user}.*Turned on 2FA`) })).toBeVisible();
  await expect(page.getByRole("row", { name: new RegExp(`${user}.*Wrong 2FA code`) })).toBeVisible();
});
