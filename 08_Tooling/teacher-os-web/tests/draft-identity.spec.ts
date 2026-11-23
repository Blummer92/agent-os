import { test, expect, type Page } from "@playwright/test";

// Regression for #3778 QA F04: lesson records carry no stable lesson ID, so
// drafts/messages were keyed `unit_id:index` and followed the index after a
// reorder. The fix binds lesson-keyed drafts to one exact list signature
// per unit and drops them when a fresh read changes that signature.
const SRC = { display_name: "Test Source", verification_state: "verified-current", access: "read-only" };
const now = () => new Date().toISOString();
const UNIT_A = "aaaaaaaa-0000-4000-8000-000000000001";
const json = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });
const lesson = (n: number) => ({ day_lesson_number: `Day ${n}`, daily_learning_target: `Target ${n}`, daily_focus: `Focus ${n}`, key_vocabulary: null, source_evidence: `Evidence ${n}`, record_url: null, canonical_unit: { page_id: UNIT_A } });
const panel = (page: Page) => page.getByRole("region", { name: "View Assignment" });
async function setup(page: Page, getLessons: () => unknown[]) {
  await page.route("**/api/teacher-os/units", r => r.fulfill(json({ status: "ok", units: [{ unit_id: UNIT_A, title: "Alpha Unit" }], source: SRC, generated_at: now() })));
  await page.route("**/api/teacher-os/units/*/lessons", r => r.fulfill(json({ status: "ok", unit: { unit_id: UNIT_A }, lessons: getLessons(), source: SRC, generated_at: now() })));
  await page.goto("/");
}
async function editAtIndex(page: Page, index: number) {
  await page.getByRole("button", { name: /View Assignment/ }).click();
  for (let i = 0; i < index; i++) await page.getByRole("button", { name: "Next →" }).click();
  await panel(page).getByRole("button", { name: "Edit in focused chat" }).click();
}

test("reorder on refresh drops the lesson draft and message instead of moving them to another lesson", async ({ page }) => {
  let lessons: unknown[] = [lesson(1), lesson(2), lesson(3)];
  await setup(page, () => lessons);
  await editAtIndex(page, 1);
  await expect(page.getByRole("heading", { name: "Editing: Day 2" })).toBeVisible();
  await page.getByLabel("Describe a proposed edit").fill("MESSAGE-FOR-DAY-2");
  await page.getByRole("button", { name: "Add local message" }).click();
  await expect(page.getByText("MESSAGE-FOR-DAY-2")).toBeVisible();
  await page.getByLabel("Describe a proposed edit").fill("DRAFT-FOR-DAY-2-ONLY");
  await page.getByRole("button", { name: "← Back to lesson" }).click();
  lessons = [lesson(3), lesson(1), lesson(2)];
  await page.getByRole("button", { name: /View Assignment/ }).click();
  await panel(page).getByRole("button", { name: "Refresh from Notion" }).click();
  // Index 1 is now Day 1, not Day 2.
  await expect(panel(page).getByRole("heading", { name: "Focus 1" })).toBeVisible();
  await panel(page).getByRole("button", { name: "Edit in focused chat" }).click();
  await expect(page.getByRole("heading", { name: "Editing: Day 1" })).toBeVisible();
  await expect(page.getByLabel("Describe a proposed edit")).toHaveValue("");
  await expect(page.getByText("MESSAGE-FOR-DAY-2")).toHaveCount(0);
  await expect(page.getByText("DRAFT-FOR-DAY-2-ONLY")).toHaveCount(0);
});

test("identical refresh preserves the lesson draft", async ({ page }) => {
  const lessons: unknown[] = [lesson(1), lesson(2), lesson(3)];
  await setup(page, () => lessons);
  await editAtIndex(page, 1);
  await expect(page.getByRole("heading", { name: "Editing: Day 2" })).toBeVisible();
  await page.getByLabel("Describe a proposed edit").fill("KEEP-ME-DAY-2");
  await page.getByRole("button", { name: "← Back to lesson" }).click();
  await page.getByRole("button", { name: /View Assignment/ }).click();
  await panel(page).getByRole("button", { name: "Refresh from Notion" }).click();
  await expect(panel(page).getByRole("heading", { name: "Focus 2" })).toBeVisible();
  await panel(page).getByRole("button", { name: "Edit in focused chat" }).click();
  await expect(page.getByRole("heading", { name: "Editing: Day 2" })).toBeVisible();
  await expect(page.getByLabel("Describe a proposed edit")).toHaveValue("KEEP-ME-DAY-2");
});

// #3778 review: lessons that agree on day/focus/target but differ in vocabulary, evidence or record link
// must still invalidate drafts when they are reordered.
test("reorder of lessons differing only in vocabulary/evidence drops the draft", async ({ page }) => {
  const twin = (v: string) => ({ ...lesson(1), day_lesson_number: "Day 1", key_vocabulary: v, source_evidence: `Evidence ${v}` });
  let lessons: unknown[] = [twin("alpha"), twin("beta")];
  await setup(page, () => lessons);
  await editAtIndex(page, 0);
  await page.getByLabel("Describe a proposed edit").fill("DRAFT-FOR-ALPHA");
  await page.getByRole("button", { name: "← Back to lesson" }).click();
  lessons = [twin("beta"), twin("alpha")];
  await page.getByRole("button", { name: /View Assignment/ }).click();
  await panel(page).getByRole("button", { name: "Refresh from Notion" }).click();
  await panel(page).getByRole("button", { name: "Edit in focused chat" }).click();
  await expect(page.getByLabel("Describe a proposed edit")).toHaveValue("");
});
