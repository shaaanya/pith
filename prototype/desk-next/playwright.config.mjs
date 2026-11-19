import { defineConfig } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
const here = fileURLToPath(new URL(".", import.meta.url));
const require = createRequire(
  new URL("../../frontend/package.json", import.meta.url),
);
const current = require("@playwright/test");
const browserProjects = ["chromium", "firefox", "webkit"].flatMap((name) => {
  const standard = current[name].executablePath();
  if (!existsSync(standard)) {
    console.warn(
      `Skipping ${name}: exact browser revision unavailable. Existing older engines are checked separately with cross-browser.mjs and their matching runtime.`,
    );
    return [];
  }
  return [
    {
      name,
      ...(name === "chromium" ? {} : { grep: /@cross-browser/ }),
      use: { browserName: name },
      metadata: { browserExecutable: standard },
    },
  ];
});
export default defineConfig({
  testDir: `${here}tests`,
  outputDir: `${here}test-results`,
  timeout: 60000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ["list"],
    ["json", { outputFile: `${here}evidence/test-results.json` }],
  ],
  use: {
    baseURL: "http://127.0.0.1:5175",
    viewport: { width: 1280, height: 900 },
    screenshot: "only-on-failure",
  },
  webServer: {
    command:
      "node ../../frontend/node_modules/vite/bin/vite.js --config vite.config.mjs --configLoader native --host 127.0.0.1 --port 5175 --strictPort",
    cwd: here,
    url: "http://127.0.0.1:5175",
    reuseExistingServer: true,
  },
  projects: browserProjects,
});
