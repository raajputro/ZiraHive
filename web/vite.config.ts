/// <reference types="node" />
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The production Content-Security-Policy lives in the Caddyfile. `vite preview` (used by the
// end-to-end tests) sends the same header, so the tests catch anything it would block.
const csp = readFileSync(new URL("./Caddyfile", import.meta.url), "utf8").match(/Content-Security-Policy "([^"]+)"/)?.[1];

// In dev, the API runs on :8000 and Vite proxies /api to it (same-origin, so cookies work).
// ws: true carries the watch-party WebSocket through the proxy too.
const proxy = { "/api": { target: process.env.ZIRAHIVE_API ?? "http://localhost:8000", ws: true } };

export default defineConfig({
  plugins: [react()],
  build: { target: "es2022" },  // pdf.js uses modern JavaScript; every current browser has it
  server: { proxy },
  preview: { proxy, headers: csp ? { "Content-Security-Policy": csp } : {} },
});
