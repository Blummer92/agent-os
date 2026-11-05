import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// Acceptance coverage for the synthetic classroom fixture (#2801). Everything
// here is the committed SYNTHETIC fixture or a mutation of it; none of it is
// Notion or Drive evidence.
const FIXTURE_URL = "**/fixture/classroom-fixture.v1.json";
const BODY = JSON.parse(readFileSync(new URL("../public/fixture/classroom-fixture.v1.json", import.meta.url), "utf8"));
const json = (body: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });
const go = async (page: Page, scenario = "current") => { await page.goto(`/fixture.html?scenario=${scenario}`); };
const summary = (page: Page) => page.getByRole("status").filter({ has: page.locator("#summary-title") });
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

test("current: the canonical fixture shows plan, approved visuals, guided practice, materials and provenance", async ({ page }) => {
  await go(page);
  await expect(page.getByRole("heading", { level: 1, name: "Photography Foundations" })).toBeVisible();
  await expect(page.getByRole("note").filter({ hasText: "FIXTURE" })).toContainText("not Notion or Drive evidence");
  await expect(summary(page)).toContainText("Context is current");
  await expect(page.getByText("Teacher-reviewed")).toBeVisible();
  await expect(page.getByRole("list", { name: "Visual selections" }).getByRole("listitem")).toHaveCount(3);
  await expect(page.getByText("Approved", { exact: true })).toHaveCount(2);
  await expect(page.getByText("Pending review")).toBeVisible();
  await expect(page.getByRole("list", { name: "Guided practice steps" }).getByRole("listitem")).toHaveCount(3);
  await expect(page.getByText("20 minutes in total.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Classroom materials" }).getByText("Notion and Drive agree")).toHaveCount(2);
  await expect(page.getByText("not instructional readiness and not permission to publish")).toBeVisible();
  for (const name of ["Fixture planning projection", "Fixture visual-selection evidence", "Fixture guided-practice context", "Fixture classroom-artifact projection"])
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  await expect(page.getByText("Current", { exact: true })).toHaveCount(4);
});

test("read-only boundary: only the fixture file is fetched; no write, no API, no Notion, no Drive", async ({ page }) => {
  const seen: string[] = [];
  page.on("request", r => seen.push(`${r.method()} ${new URL(r.url()).pathname}`));
  await go(page, "context-changed");
  await page.getByLabel("What should change?").fill("Add an exit question");
  await page.getByRole("button", { name: "Prepare intent preview" }).click();
  await page.getByRole("button", { name: "Check lesson is unchanged" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "withdrawn" })).toBeVisible();
  expect(seen.filter(s => !s.startsWith("GET "))).toEqual([]);
  expect(seen.filter(s => /\/api\/|notion|drive|google/i.test(s))).toEqual([]);
  expect(new Set(seen.filter(s => s.includes("/fixture/")))).toEqual(new Set(["GET /fixture/classroom-fixture.v1.json"]));
});

test("loading: a slow read shows an honest loading state and no content", async ({ page }) => {
  let release!: () => void; const gate = new Promise<void>(r => { release = r; });
  await page.route(FIXTURE_URL, async r => { await gate; await r.fulfill(json(BODY)); });
  await go(page);
  await expect(page.getByRole("status").filter({ hasText: "Loading the sample classroom" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(0);
  release();
  await expect(page.getByRole("heading", { level: 1, name: "Photography Foundations" })).toBeVisible();
});

test("error: an unavailable fixture shows nothing in its place and Try again recovers", async ({ page }) => {
  await page.route(FIXTURE_URL, r => r.fulfill(json({ nope: true }, 503)));
  await go(page);
  await expect(page.getByRole("alert")).toContainText("not available");
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(0);
  await page.unroute(FIXTURE_URL);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Photography Foundations" })).toBeVisible();
});

test("interrupted network: the read fails visibly, then recovers when the network returns", async ({ page }) => {
  await page.route(FIXTURE_URL, r => r.abort("internetdisconnected"));
  await go(page);
  await expect(page.getByRole("alert")).toContainText("network interrupted");
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(0);
  await page.unroute(FIXTURE_URL);
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(summary(page)).toContainText("Context is current");
});

test("interrupted network after content loaded: revalidation fails closed and keeps the intent unsent", async ({ page }) => {
  await go(page);
  await page.getByLabel("What should change?").fill("Shorten step 2");
  await page.getByRole("button", { name: "Prepare intent preview" }).click();
  await page.route(FIXTURE_URL, r => r.abort("internetdisconnected"));
  await page.getByRole("button", { name: "Check lesson is unchanged" }).click();
  await expect(page.getByRole("alert")).toContainText("could not be re-read");
  await expect(page.getByRole("alert")).toContainText("not sent");
});

test("a malformed, non-synthetic or foreign payload renders no classroom", async ({ page }) => {
  for (const body of [{ schema: "other/v1" }, { ...BODY, fixture: { ...BODY.fixture, synthetic: false } }, [], "text"]) {
    await page.route(FIXTURE_URL, r => r.fulfill(json(body)));
    await go(page);
    await expect(page.getByRole("alert")).toContainText("did not match its contract");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(0);
    await page.unroute(FIXTURE_URL);
  }
});

test("empty: no lesson planned shows an empty state, not sample content", async ({ page }) => {
  await go(page, "empty");
  await expect(page.getByRole("heading", { name: "No lesson is planned for tomorrow" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(0);
});

test("stale: every old source is called out and the summary asks for a refresh", async ({ page }) => {
  await go(page, "stale");
  await expect(summary(page)).toContainText("Needs your attention (4)");
  await expect(page.getByText("Stale", { exact: true })).toHaveCount(4);
  await expect(summary(page)).toContainText("refresh before relying on it");
});

test("degraded: Drive unavailable keeps the Notion-side lesson and claims nothing about Drive", async ({ page }) => {
  await go(page, "degraded");
  await expect(page.getByRole("alert").filter({ hasText: "Classroom materials are unavailable" })).toContainText("reader-unreachable");
  await expect(page.getByRole("list", { name: "Classroom materials" })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Guided practice steps" })).toBeVisible();
  await expect(summary(page)).toContainText("Needs your attention (1)");
});

test("Notion and Drive disagree: a removed file is flagged and not presented as usable", async ({ page }) => {
  await go(page, "disagreement");
  const card = page.getByRole("list", { name: "Classroom materials" }).getByRole("listitem").filter({ hasText: "Composition Comparison Worksheet" });
  await expect(card).toContainText("Removed from Drive");
  await expect(card).toContainText("Notion still lists it");
  await expect(card).not.toContainText("Notion and Drive agree");
  await expect(summary(page)).toContainText("Composition Comparison Worksheet: Removed from Drive.");
});

test("moved artifact: the new location is reported but the file stays withheld", async ({ page }) => {
  await go(page, "moved");
  const card = page.getByRole("list", { name: "Classroom materials" }).getByRole("listitem").filter({ hasText: "Rule of Thirds Slides" });
  await expect(card).toContainText("Moved in Drive");
  await expect(card).toContainText("Archive > Photography Foundations");
  await expect(summary(page)).toContainText("Needs your attention (1)");
});

test("permission mismatch: a restricted file is withheld and its location is not shown", async ({ page }) => {
  await go(page, "permission");
  const card = page.getByRole("list", { name: "Classroom materials" }).getByRole("listitem").filter({ hasText: "Rule of Thirds Slides" });
  await expect(card).toContainText("Permission mismatch");
  await expect(card).not.toContainText("Drive > Digital Media 1");
});

test("unknown projection values render as inert text and are never treated as approved or usable", async ({ page }) => {
  await go(page, "unknown");
  await expect(page.getByText("Unrecognized status")).toBeVisible();
  await expect(page.getByText("<b>approved!</b>")).toBeVisible(); // literal text
  await expect(page.locator("li.visual-card b")).toHaveCount(0); // never parsed as markup
  await expect(page.getByText("Approved", { exact: true })).toHaveCount(2);
  await expect(page.getByRole("list", { name: "Classroom materials" }).getByText("Unrecognized source value")).toBeVisible();
  await expect(page.locator(".diagram--unknown")).toHaveCount(1);
});

test("stale lesson context: a changed lesson withdraws the unsent intent, keeps the teacher's words and sends nothing", async ({ page }) => {
  await go(page, "context-changed");
  await expect(page.getByText("revision 3")).toBeVisible();
  await page.getByLabel("What should change?").fill("Add an exit question about balance");
  await page.getByRole("button", { name: "Prepare intent preview" }).click();
  const preview = page.getByText("Intent preview — not sent");
  await expect(preview).toBeVisible();
  await expect(page.getByText("Being on this page grants no write, readiness or publication authority")).toBeVisible();
  await page.getByRole("button", { name: "Check lesson is unchanged" }).click();
  await expect(page.getByRole("alert")).toContainText("revision 3 → 4");
  await expect(preview).toHaveCount(0);
  await expect(page.getByLabel("What should change?")).toHaveValue("Add an exit question about balance");
  await expect(page.getByText("revision 4")).toBeVisible();
  await expect(page.getByText("including a tilted horizon")).toBeVisible();
});

test("unchanged lesson: revalidation confirms but the intent is still only a preview (no send control exists)", async ({ page }) => {
  await go(page);
  await page.getByLabel("What should change?").fill("Add a thumbnail template");
  await page.getByRole("button", { name: "Prepare intent preview" }).click();
  await page.getByRole("button", { name: "Check lesson is unchanged" }).click();
  await expect(page.getByRole("status").filter({ hasText: "unchanged (revision 3)" })).toContainText("nothing was sent");
  await expect(page.getByRole("button", { name: /send|submit|publish|apply|save|dispatch/i })).toHaveCount(0);
  await page.getByRole("button", { name: "Discard preview" }).click();
  await expect(page.getByText("Intent preview — not sent")).toHaveCount(0);
});

test("changing the sample state drops an unsent intent instead of carrying it to different evidence", async ({ page }) => {
  await go(page);
  await page.getByLabel("What should change?").fill("x");
  await page.getByRole("button", { name: "Prepare intent preview" }).click();
  await page.getByText("Fixture review controls").click();
  await page.getByLabel("Sample state").selectOption("stale");
  await expect(page.getByText("Intent preview — not sent")).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get("scenario")).toBe("stale");
  await expect(summary(page)).toContainText("Needs your attention (4)");
});

test("unknown scenario query falls back to the current fixture, never to anything else", async ({ page }) => {
  await go(page, "__proto__");
  await expect(summary(page)).toContainText("Context is current");
});

test("keyboard: the whole flow is operable without a pointer and focus is visible", async ({ page }) => {
  await go(page);
  await page.getByRole("link", { name: /Live Teacher OS/ }).focus();
  await page.keyboard.press("Tab"); // textarea comes next in reading order after the content links
  const input = page.getByLabel("What should change?");
  await input.focus();
  await page.keyboard.type("Add a gallery walk");
  await page.keyboard.press("Tab");
  const prepare = page.getByRole("button", { name: "Prepare intent preview" });
  await expect(prepare).toBeFocused();
  expect(await prepare.evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Intent preview — not sent")).toBeVisible();
  await page.getByRole("button", { name: "Check lesson is unchanged" }).focus();
  await page.keyboard.press("Space");
  await expect(page.getByRole("status").filter({ hasText: "unchanged" })).toBeVisible();
  const details = page.locator("details.review-controls");
  await details.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(details).toHaveAttribute("open", "");
  await page.keyboard.press("Tab");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByLabel("Sample state")).not.toHaveValue("current");
});

test("accessible structure: landmarks, one h1, named lists, images with text alternatives", async ({ page }) => {
  await go(page);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  const imgs = page.getByRole("img");
  await expect(imgs).toHaveCount(3);
  for (const img of await imgs.all()) expect(((await img.getAttribute("aria-label")) ?? "").length).toBeGreaterThan(10);
  await expect(page.getByRole("contentinfo")).toBeVisible();
});

const VIEWPORTS = [["Chromebook", 1366, 768], ["tablet portrait", 768, 1024], ["tablet landscape", 1024, 768], ["phone", 390, 844], ["small phone", 320, 568]] as const;
for (const [name, width, height] of VIEWPORTS) {
  test(`responsive ${name} ${width}x${height}: no horizontal overflow, every section reachable, in every state`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    for (const scenario of ["current", "stale", "disagreement", "unknown", "degraded"]) {
      await go(page, scenario);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await overflow(page), `${scenario} overflows at ${width}`).toBeLessThanOrEqual(0);
    }
    await go(page);
    for (const h of ["Lesson plan", "Approved visual selections", "Guided practice", "Classroom materials", "Improve tomorrow's lesson"]) {
      const heading = page.getByRole("heading", { name: h });
      await heading.scrollIntoViewIfNeeded();
      await expect(heading).toBeInViewport();
    }
  });
}

test("zoom (400% / 200% equivalents) and long text reflow without page scroll or clipping", async ({ page }) => {
  for (const width of [320, 160]) { // 1280/4 and 320/2
    await page.setViewportSize({ width, height: 700 });
    await page.route(FIXTURE_URL, r => r.fulfill(json({ ...BODY, lesson: { ...BODY.lesson, daily_focus: "Supercalifragilisticexpialidocious".repeat(5), key_vocabulary: ["x".repeat(110)] } })));
    await go(page);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await overflow(page), `overflow at ${width}`).toBeLessThanOrEqual(0);
    await page.unroute(FIXTURE_URL);
  }
});

test("dark scheme at 320px: still no overflow and the banner is visible", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 320, height: 640 });
  await go(page, "disagreement");
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await expect(page.getByRole("note")).toBeVisible();
});

test("touch: targets are at least 44px and tap works", async ({ page }, info) => {
  await go(page);
  const targets = [page.getByRole("link", { name: /Live Teacher OS/ }), page.locator("details.review-controls summary"), page.getByLabel("What should change?")];
  for (const t of targets) { const box = (await t.boundingBox())!; expect(box.height, "height").toBeGreaterThanOrEqual(44); }
  await page.getByLabel("What should change?").fill("Tap test");
  const prepare = page.getByRole("button", { name: "Prepare intent preview" });
  expect((await prepare.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  if (info.project.name === "phone") await prepare.tap(); else await prepare.click();
  await expect(page.getByText("Intent preview — not sent")).toBeVisible();
  const check = page.getByRole("button", { name: "Check lesson is unchanged" });
  expect((await check.boundingBox())!.height).toBeGreaterThanOrEqual(44);
});

test("the live app links to the fixture without presenting it as live data", async ({ page }) => {
  await page.route("**/api/teacher-os/units", r => r.fulfill(json({ status: "unavailable", reason_code: "admission-required" }, 503)));
  await page.goto("/");
  const link = page.getByRole("link", { name: /sample classroom \(synthetic fixture, not Notion data\)/ });
  await expect(link).toHaveAttribute("href", "/fixture.html");
  await expect(page.getByRole("heading", { level: 1, name: "Teacher OS" })).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/fixture\.html/);
  await expect(page.getByRole("note")).toContainText("FIXTURE");
  await page.getByRole("link", { name: /Live Teacher OS/ }).click();
  await expect(page).toHaveURL(/\/$/);
});
