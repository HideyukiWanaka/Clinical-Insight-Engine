import { defineConfig, devices } from "@playwright/test";

// The environment ships a pre-installed Chromium under PLAYWRIGHT_BROWSERS_PATH;
// we never download one. If the bundled revision differs from what this
// @playwright/test version expects, CIE_CHROMIUM_PATH pins the exact binary.
const chromiumPath =
  process.env.CIE_CHROMIUM_PATH ||
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const port = Number(process.env.VITE_PORT ?? 5173);

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "off",
    screenshot: "off",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: { executablePath: chromiumPath },
      },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
