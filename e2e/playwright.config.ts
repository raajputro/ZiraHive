import { defineConfig, devices } from "@playwright/test";

// Runs against a GharBox that is already running (Docker on your PC, or the CI stack).
//   E2E_BASE_URL   default http://localhost:8080
//   E2E_ADMIN / E2E_PASSWORD   the admin account; created on a fresh install
export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  globalSetup: "./global-setup.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    storageState: ".auth/admin.json",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /(mobile|player|party)\.spec\.ts/ },
    // Two people in one watch party. Uses the WebM sample, which open-source Chromium can play.
    {
      name: "party",
      testMatch: /party\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] } },
    },
    // Video needs real Chrome: the open-source Chromium build can't decode H.264.
    // npx playwright install chrome
    {
      name: "player",
      testMatch: /player\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], channel: "chrome", launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] } },
    },
    { name: "phone", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
});
