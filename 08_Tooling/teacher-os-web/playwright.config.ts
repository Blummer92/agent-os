import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests", testMatch: "*.spec.ts", timeout: 30000,
  use: { baseURL: "http://127.0.0.1:4174", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["iPhone 13"], browserName: "chromium" } },
  ],
  webServer: { command: "npm run dev -- --host 127.0.0.1 --port 4174", url: "http://127.0.0.1:4174", reuseExistingServer: false, timeout: 60000 },
});
