import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT ?? 8793);

// Journeys run against the REAL Python backend serving the REAL built page (static/index.html, CSP included).
// Run `pnpm build` first (the `e2e` script does). The Vite dev server is deliberately not used: it has no CSP.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: {
    command: "node e2e/backend.mjs",
    // The port answers before seeding ends; wait for the script's own "ready" line instead.
    wait: { stdout: /e2e backend ready/ },
    timeout: 180_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
});
