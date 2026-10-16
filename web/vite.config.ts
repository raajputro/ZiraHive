/// <reference types="node" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the API runs on :8000 and Vite proxies /api to it (same-origin, so cookies work).
export default defineConfig({
  plugins: [react()],
  // ws: true carries the watch-party WebSocket through the proxy too.
  server: { proxy: { "/api": { target: process.env.GHARBOX_API ?? "http://localhost:8000", ws: true } } },
});
