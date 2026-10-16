import { request, type FullConfig } from "@playwright/test";
import { mkdirSync } from "node:fs";

export const ADMIN = process.env.E2E_ADMIN ?? "e2eadmin";
export const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-password-123";

/** Sign in once (creating the admin on a fresh install) and save the session for every test. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL!;
  const api = await request.newContext({ baseURL });
  const { needs_setup } = await (await api.get("/api/setup/status")).json();
  const res = needs_setup
    ? await api.post("/api/setup", { data: { username: ADMIN, password: PASSWORD } })
    : await api.post("/api/auth/login", { data: { username: ADMIN, password: PASSWORD } });
  if (!res.ok()) {
    throw new Error(`Couldn't sign in as ${ADMIN} (${res.status()}). On an existing install, set E2E_ADMIN and E2E_PASSWORD.`);
  }
  mkdirSync(".auth", { recursive: true });
  await api.storageState({ path: ".auth/admin.json" });
  await api.dispose();
}
