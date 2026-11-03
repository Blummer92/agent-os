import { test, expect, type Page } from "@playwright/test";

// Synthetic, obviously fake API payloads used ONLY to drive the UI in isolated tests.
// They are not curriculum and are not Notion evidence.
const SRC = { display_name: "Test Source", verification_state: "verified-current", access: "read-only" };
const now = () => new Date().toISOString();
const lesson = (n: number, extra = {}) => ({
  day_lesson_number: `Day ${n}`, daily_learning_target: `Target ${n}`, daily_focus: `Focus ${n}`,
  key_vocabulary: null, source_evidence: `Evidence ${n}`, record_url: `https://example.test/r/${n}`, ...extra,
});
const UNIT_A = "aaaaaaaa-0000-4000-8000-000000000001";
const UNIT_B = "bbbbbbbb-0000-4000-8000-000000000002";
const json = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });

async function mockApi(page: Page, units: { unit_id: string; title: string }[], lessons: Record<string, unknown[]>, generatedAt = now()) {
  await page.route("**/api/teacher-os/units", r => r.fulfill(json(units.length
    ? { status: "ok", units, source: SRC, generated_at: generatedAt } : { status: "empty", source: SRC, generated_at: generatedAt })));
  await page.route("**/api/teacher-os/units/*/lessons", r => {
    const id = r.request().url().split("/units/")[1].split("/")[0];
    const rows = lessons[id] ?? [];
    return r.fulfill(json(rows.length ? { status: "ok", unit: units.find(u => u.unit_id === id), lessons: rows, source: SRC, generated_at: generatedAt } : { status: "empty", source: SRC, generated_at: generatedAt }));
  });
}
const open = (page: Page) => page.getByRole("button", { name: /View Assignment/ }).click();

test("units and lessons render from the API, with provenance, and no sample content", async ({ page }) => {
  await mockApi(page, [{ unit_id: UNIT_A, title: "Alpha Unit" }, { unit_id: UNIT_B, title: "Added In Notion Later" }], { [UNIT_A]: [lesson(1), lesson(2)], [UNIT_B]: [lesson(9)] });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Alpha Unit" })).toBeVisible();
  await open(page);
  await expect(page.getByRole("heading", { name: "Focus 1" })).toBeVisible();
  await expect(page.getByText("Test Source · verified-current · read-only")).toBeVisible();
  await page.getByRole("button", { name: "Next →" }).click();
  await page.getByRole("button", { name: "View full lesson" }).click();
  await expect(page.getByText("Evidence 2")).toBeVisible();
  await expect(page.getByText("Not recorded in Notion").first()).toBeVisible(); // empty vocabulary is never invented
  await expect(page.getByRole("link", { name: "Open the Notion record" })).toHaveAttribute("href", "https://example.test/r/2");
  await expect(page.getByText(/Google Drive/).first()).toBeVisible();
  await page.getByRole("button", { name: "← Back to lesson" }).click();
  await open(page);
  await page.getByLabel("Unit", { exact: true }).selectOption(UNIT_B); // a unit with no code anywhere in the repo
  await expect(page.getByRole("heading", { name: "Focus 9" })).toBeVisible();
  await expect(page.getByText("Photography Foundations")).toHaveCount(0);
});

test("a slow response for a previous unit never appears under the newly selected unit", async ({ page }) => {
  await mockApi(page, [{ unit_id: UNIT_A, title: "Alpha Unit" }, { unit_id: UNIT_B, title: "Beta Unit" }], { [UNIT_B]: [lesson(7)] });
  await page.route(`**/api/teacher-os/units/${UNIT_A}/lessons`, async r => { await new Promise(res => setTimeout(res, 1200)); await r.fulfill(json({ status: "ok", lessons: [lesson(1, { daily_focus: "LEAK FROM A" })], source: SRC, generated_at: now() })); });
  await page.goto("/");
  await open(page);
  await page.getByLabel("Unit", { exact: true }).selectOption(UNIT_B);
  await expect(page.getByRole("heading", { name: "Focus 7" })).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(page.getByText("LEAK FROM A")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Focus 7" })).toBeVisible();
});

test("empty, error and stale sources are honest and show no lessons", async ({ page }) => {
  await mockApi(page, [], {});
  await page.goto("/");
  await expect(page.getByText("Notion returned no units")).toBeVisible();
  await open(page);
  await expect(page.getByRole("button", { name: "View full lesson" })).toHaveCount(0);

  const err = await page.context().newPage();
  await err.route("**/api/teacher-os/units", r => r.fulfill(json({ status: "error", reason_code: "read-failed" }, 502)));
  await err.goto("/");
  await expect(err.getByRole("alert")).toContainText("Could not read units from Notion (read-failed)");
  await expect(err.getByRole("button", { name: "View full lesson" })).toHaveCount(0);

  const stale = await page.context().newPage();
  await mockApi(stale, [{ unit_id: UNIT_A, title: "Alpha Unit" }], { [UNIT_A]: [lesson(1)] }, "2020-01-01T00:00:00Z");
  await stale.goto("/");
  await expect(stale.getByRole("alert").first()).toContainText("Stale evidence");
});

test("network failure is an unavailable state, never sample lessons", async ({ page }) => {
  await page.route("**/api/teacher-os/**", r => r.abort());
  await page.goto("/");
  await open(page);
  await expect(page.getByRole("alert").first()).toContainText("Notion is unavailable");
  await expect(page.locator("body")).not.toContainText(/Photography|Graphic Design|Rule of Thirds|Unit Overview/);
});

test("negative control: with no Notion credential the real bridge reports unavailable and shows nothing", async ({ page }) => {
  // No route mock: the request reaches the real dev-server bridge and the real Python reader,
  // which has no NOTION_TOKEN in this test environment.
  const requests: string[] = [];
  page.on("request", r => { if (!r.url().startsWith("http://127.0.0.1:4174/src") && !r.url().includes("@vite") && !r.url().includes("node_modules")) requests.push(new URL(r.url()).pathname); });
  await page.goto("/");
  await open(page);
  // The specific reason proves the real Python reader ran and refused for lack of a credential,
  // not merely that the bridge failed.
  await expect(page.getByRole("alert").first()).toContainText("The Notion connection is not configured for this server");
  await expect(page.getByRole("button", { name: "View full lesson" })).toHaveCount(0);
  expect([...new Set(requests.filter(p => p.startsWith("/api/")))]).toEqual(["/api/teacher-os/units"]); // StrictMode may repeat the aborted first request
});

test("local edit chat stays separate from the lesson chat", async ({ page }) => {
  await mockApi(page, [{ unit_id: UNIT_A, title: "Alpha Unit" }], { [UNIT_A]: [lesson(1)] });
  await page.goto("/");
  await open(page);
  await page.getByRole("button", { name: "Edit in focused chat" }).click();
  await expect(page.getByRole("heading", { name: "Editing: Day 1" })).toBeVisible();
  await page.getByLabel("Describe a proposed edit").fill("Please simplify the instructions");
  await page.getByRole("button", { name: "Add local message" }).click();
  await expect(page.getByText("Please simplify the instructions")).toBeVisible();
  await page.getByRole("button", { name: "← Back to lesson" }).click();
  await expect(page.getByText("Please simplify the instructions")).toHaveCount(0);
});

test("keyboard Escape closes the panel and restores trigger focus", async ({ page }) => {
  await mockApi(page, [{ unit_id: UNIT_A, title: "Alpha Unit" }], { [UNIT_A]: [lesson(1)] });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: /View Assignment/ });
  await trigger.focus();
  await trigger.press("Enter");
  await expect(page.getByRole("region", { name: "View Assignment" })).toBeVisible();
  await page.getByLabel("Unit", { exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("region", { name: "View Assignment" })).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("narrow viewport has no horizontal page overflow", async ({ page }) => {
  await mockApi(page, [{ unit_id: UNIT_A, title: "Alpha Unit" }], { [UNIT_A]: [lesson(1)] });
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto("/");
  await open(page);
  await expect(page.getByRole("heading", { name: "Focus 1" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});
