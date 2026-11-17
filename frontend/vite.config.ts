import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import { fileURLToPath } from "node:url";

// The Python server serves exactly one file (static/index.html) under a nonce-only CSP, so the
// production build is a single self-contained HTML file (see scripts/finalize.mjs).
// Dev: proxy /api to a running `pith` and inject its token (header auth skips the Origin check).
const target = process.env.PITH_URL ?? "http://127.0.0.1:8791";
const token = process.env.PITH_TOKEN ?? "";

export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: { target: "es2022", cssMinify: true, chunkSizeWarningLimit: 2000 },
  server: {
    proxy: {
      "/api": {
        target,
        changeOrigin: true,
        headers: token ? { "X-Token": token } : {},
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
