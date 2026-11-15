import { test, expect } from "@playwright/test";

// Real HTTP chain, no page.route mocking: browser -> Vite proxy -> authenticated
// loopback API -> governed teacher_os reader -> TEST-ONLY stub executor. Every
// unit and lesson is SYNTHETIC (tests/teacher_os_web/fixture_api.py). This is
// not live Notion evidence.
const API = "http://127.0.0.1:8791";
const WEB = "http://127.0.0.1:4175";
const COLOR = "5e0c0000-0000-4000-8000-00000000c010";
const DRAFT = "5e0c0000-0000-4000-8000-00000000c030";

test("approved units and their lessons flow through the authenticated API into the lesson overview", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status", { name: /Curriculum connection: Connected/ })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Synthetic Unit — Color Planning (test data)" })).toBeVisible();
  const overview = page.getByRole("region", { name: "Lesson overview" });
  await expect(overview.getByText("Lesson 1 of 3")).toBeVisible();
  await expect(overview.getByText("Synthetic target: I can name two palette moods.")).toBeVisible();
  await expect(overview.getByText("Synthetic focus: compare warm and cool palettes")).toBeVisible();
  await expect(overview.getByText("hue, value")).toBeVisible();
  await expect(overview.getByText("Daily Generation Packet Dashboard")).toBeVisible();
  await expect(overview.getByText("verified-current")).toBeVisible();
  await overview.getByRole("button", { name: "Next lesson" }).click();
  await overview.getByRole("button", { name: "Next lesson" }).click();
  await expect(overview.getByText("Lesson 3 of 3")).toBeVisible();
  await expect(overview.getByRole("button", { name: "Next lesson" })).toBeDisabled();
  await expect(overview.getByText("Not recorded in Notion").first()).toBeVisible(); // lesson 3 has no target
  await overview.getByRole("button", { name: "Open complete lesson" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Day 3" })).toBeVisible();
  await expect(page.getByText("SYNTHETIC test record 3; not curriculum evidence.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open the Notion record" })).toHaveAttribute("href", /^https:\/\/www\.notion\.so\//);
  await expect(page.locator("body")).not.toContainText("internal planning text");
  await page.getByRole("button", { name: "← Back to lesson" }).click();
  await expect(overview.getByText("Lesson 3 of 3")).toBeVisible();
});

test("only Active, review-cleared units are offered; draft and review-required units never appear", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /View Assignment/ }).click();
  const options = await page.getByLabel("Unit", { exact: true }).locator("option").allTextContents();
  expect(options).toEqual([
    "Synthetic Unit — Color Planning (test data)", "Synthetic Unit — Foreign Lesson Guard (test data)",
    "Synthetic Unit — No Lessons Yet (test data)", "Synthetic Unit — Type Hierarchy (test data)",
  ]);
  await expect(page.locator("body")).not.toContainText(/must stay hidden/);
});

test("an approved unit with no lessons is shown as empty, never filled", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /View Assignment/ }).click();
  await page.getByLabel("Unit", { exact: true }).selectOption({ label: "Synthetic Unit — No Lessons Yet (test data)" });
  await expect(page.getByText("Notion returned no lessons").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Lesson overview" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "View full lesson" })).toHaveCount(0);
});

test("a lesson that names a different unit makes the whole read fail closed", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /View Assignment/ }).click();
  await page.getByLabel("Unit", { exact: true }).selectOption({ label: "Synthetic Unit — Foreign Lesson Guard (test data)" });
  await expect(page.getByRole("alert").first()).toContainText("Could not read lessons from Notion (read-failed)");
  await expect(page.locator("body")).not.toContainText("should never render");
  await expect(page.getByRole("region", { name: "Lesson overview" })).toHaveCount(0);
});

test("requests that bypass the app session are refused", async ({ request }) => {
  // Straight to the API without the session secret.
  const direct = await request.get(`${API}/api/teacher-os/units`);
  expect(direct.status()).toBe(401);
  expect(await direct.json()).toMatchObject({ status: "error", reason_code: "unauthenticated" });
  expect(direct.headers()["access-control-allow-origin"]).toBeUndefined();
  // Through the secret-injecting proxy, but from another site: the API still refuses.
  for (const headers of [{ Origin: "https://evil.example" }, { "Sec-Fetch-Site": "cross-site" }, { Origin: "http://127.0.0.1:3000" }]) {
    const viaProxy = await request.get(`${WEB}/api/teacher-os/units`, { headers });
    expect(viaProxy.status(), JSON.stringify(headers)).toBe(403);
    expect((await viaProxy.json()).reason_code).toBe("origin-not-allowed");
  }
  // DNS-rebinding shape against the proxy: Vite refuses a foreign Host before proxying.
  const rebound = await request.get(`${WEB}/api/teacher-os/units`, { headers: { Host: "evil.example" } });
  expect(rebound.status()).toBe(403);
  // Malformed and unapproved ids fail closed through the proxy.
  expect((await request.get(`${WEB}/api/teacher-os/units/not-a-uuid/lessons`)).status()).toBe(400);
  expect((await (await request.get(`${WEB}/api/teacher-os/units/${DRAFT}/lessons`)).json()).reason_code).toBe("unit-not-approved");
  // A same-origin read through the proxy succeeds and is not cacheable.
  const ok = await request.get(`${WEB}/api/teacher-os/units/${COLOR}/lessons`);
  expect(ok.status()).toBe(200);
  expect(ok.headers()["cache-control"]).toBe("no-store");
});
