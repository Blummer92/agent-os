import { randomBytes } from "node:crypto";
import { defineConfig, devices } from "@playwright/test";

// Real-process integration: browser -> Vite proxy (adds the per-run session
// secret server-side) -> authenticated loopback API -> governed teacher_os
// reader -> TEST-ONLY stub executor with SYNTHETIC records. No page.route
// mocking. This proves the HTTP path and its controls; it is not live Notion.
const API_PORT = 8791;
const WEB_PORT = 4175;
const secret = randomBytes(32).toString("base64url");

export default defineConfig({
  testDir: "./tests/integration", testMatch: "*.integration.ts", timeout: 30000,
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["iPhone 13"], browserName: "chromium" } },
  ],
  webServer: [
    {
      command: `python3 -I ../../tests/teacher_os_web/fixture_api.py --port ${API_PORT} --allowed-origin http://127.0.0.1:${WEB_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/teacher-os/units`, // 401 without the secret counts as "up"
      env: { TEACHER_OS_API_SESSION_SECRET: secret }, reuseExistingServer: false, timeout: 60000,
    },
    {
      command: `npx vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { TEACHER_OS_API_PORT: String(API_PORT), TEACHER_OS_API_SESSION_SECRET: secret }, reuseExistingServer: false, timeout: 60000,
    },
  ],
});
