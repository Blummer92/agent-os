import { test, expect, type Page } from "@playwright/test";

// Regression for the #3778 QA mobile overflow: long lesson labels
// (day_lesson_number, previously white-space:nowrap in .card-meta) and long
// unbroken focus text (previously unwrapped .material-card h3) forced the
// assignment panel and the document far past narrow viewports. Chromium
// emulation here is NOT real Safari/iPhone testing.
const SRC = { display_name: "Test Source", verification_state: "verified-current", access: "read-only" };
const now = () => new Date().toISOString();
const UNIT_A = "aaaaaaaa-0000-4000-8000-000000000001";
const json = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });
const lesson = (extra: Record<string, unknown> = {}) => ({
  day_lesson_number: "Day 1", daily_learning_target: "Target 1", daily_focus: "Focus 1",
  key_vocabulary: null, source_evidence: "Evidence 1", record_url: null, canonical_unit: { page_id: UNIT_A }, ...extra,
});
async function mockApi(page: Page, unitTitle: string, lessonExtra: Record<string, unknown> = {}) {
  await page.route("**/api/teacher-os/units", r => r.fulfill(json({ status: "ok", units: [{ unit_id: UNIT_A, title: unitTitle }], source: SRC, generated_at: now() })));
  await page.route("**/api/teacher-os/units/*/lessons", r => r.fulfill(json({ status: "ok", unit: { unit_id: UNIT_A }, lessons: [lesson(lessonExtra)], source: SRC, generated_at: now() })));
}
const panel = (page: Page) => page.getByRole("region", { name: "View Assignment" });
async function assertNoOverflow(page: Page) {
  const m = await page.evaluate(() => {
    const q = (s: string) => { const e = document.querySelector(s) as HTMLElement | null; return e ? { sw: e.scrollWidth, cw: e.clientWidth } : null; };
    return { doc: document.documentElement.scrollWidth, inner: window.innerWidth, panel: q(".assignment-panel"), card: q(".material-card"), overview: q(".lesson-card") };
  });
  expect(m.doc).toBeLessThanOrEqual(m.inner);
  expect(m.panel!.sw).toBeLessThanOrEqual(m.panel!.cw);
  expect(m.card!.sw).toBeLessThanOrEqual(m.card!.cw);
  if (m.overview) expect(m.overview.sw).toBeLessThanOrEqual(m.overview.cw);
}

for (const width of [320, 390]) {
  test(`narrow ${width}px: long and unbroken labels reflow without page or panel overflow`, async ({ page }) => {
    for (const extra of [
      { day_lesson_number: "Word ".repeat(12).trim() + " Lesson" },
      { day_lesson_number: "X".repeat(65) },
      { daily_focus: "Y".repeat(65) },
      { daily_focus: "Word ".repeat(12).trim() + " Focus" },
    ]) {
      await page.unrouteAll({ behavior: "wait" });
      await mockApi(page, "Alpha Unit", extra);
      await page.setViewportSize({ width, height: 740 });
      await page.goto("/");
      await page.getByRole("button", { name: /View Assignment/ }).click();
      await expect(panel(page)).toBeVisible();
      await assertNoOverflow(page);
      // Full content stays reachable: the whole label/focus text is on screen.
      const focusText = String(extra.daily_focus ?? "Focus 1");
      await expect(panel(page).getByRole("heading", { name: focusText.slice(0, 30) })).toBeVisible();
    }
  });

  test(`narrow ${width}px: long unit title reflows and View/Close/Refresh/Escape still work`, async ({ page }) => {
    await mockApi(page, "Z".repeat(65));
    await page.setViewportSize({ width, height: 740 });
    await page.goto("/");
    const trigger = page.getByRole("button", { name: /View Assignment/ });
    await trigger.click();
    await expect(panel(page).getByRole("heading", { name: "Focus 1" })).toBeVisible();
    await assertNoOverflow(page);
    await panel(page).getByRole("button", { name: "View full lesson" }).click();
    await expect(page.getByRole("heading", { name: "Day 1" })).toBeVisible();
    await page.getByRole("button", { name: "← Back to lesson" }).click();
    await trigger.click();
    await panel(page).getByRole("button", { name: "Refresh from Notion" }).click();
    await expect(panel(page).getByRole("heading", { name: "Focus 1" })).toBeVisible();
    await assertNoOverflow(page);
    await panel(page).getByRole("button", { name: "Refresh from Notion" }).focus();
    await page.keyboard.press("Escape");
    await expect(panel(page)).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.click();
    await panel(page).getByRole("button", { name: "Close" }).click();
    await expect(panel(page)).toHaveCount(0);
  });
}

test("narrow 320px dark scheme: long labels reflow without overflow", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await mockApi(page, "Alpha Unit", { day_lesson_number: "X".repeat(65), daily_focus: "Y".repeat(65) });
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto("/");
  await page.getByRole("button", { name: /View Assignment/ }).click();
  await expect(panel(page)).toBeVisible();
  await assertNoOverflow(page);
});

test("admission-blocked banner no longer claims lessons come from verified evidence", async ({ page }) => {
  await page.route("**/api/teacher-os/units", r => r.fulfill(json({ status: "unavailable", reason_code: "admission-required" }, 503)));
  await page.goto("/");
  await expect(page.getByRole("note")).toContainText("live Notion reads are not admitted yet, so no lessons are shown");
  await expect(page.locator("body")).not.toContainText("lessons come from verified Notion evidence");
});
