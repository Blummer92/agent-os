import { test, expect } from "@playwright/test";

test("chat-first screen, top-right assignment and fixture labels", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Photography Foundations" })).toBeVisible();
  await expect(page.getByText("Fixture data", { exact: false })).toBeVisible();
  const trigger = page.getByRole("button", { name: /View Assignment/ });
  await trigger.click();
  await expect(page.getByRole("region", { name: "View Assignment" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Unit Overview" })).toBeVisible();
  await expect(page.getByText("Grade 9", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: "Next →" }).click();
  await expect(page.getByRole("heading", { name: "Composition Worksheet" })).toBeVisible();
  await page.getByRole("button", { name: "View full preview" }).click();
  await expect(page.getByRole("heading", { name: "Composition Worksheet" })).toBeVisible();
  await expect(page.getByText("Sentence starter:", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "← Back to lesson" }).click();
  await expect(page.getByRole("heading", { name: "Photography Foundations" })).toBeVisible();
});

test("course/unit selector and focused edit preserve separate local chat", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /View Assignment/ }).click();
  await page.getByLabel("Course", { exact: true }).selectOption("media2");
  await expect(page.getByText("Grade 10", { exact: false }).first()).toBeVisible();
  await page.getByLabel("Unit", { exact: true }).selectOption("storytelling");
  await expect(page.getByRole("heading", { name: "Unit Overview" })).toBeVisible();
  await page.getByRole("button", { name: "Edit in focused chat" }).click();
  await expect(page.getByRole("heading", { name: "Editing: Unit Overview" })).toBeVisible();
  await page.getByLabel("Describe a proposed edit").fill("Please simplify the instructions");
  await page.getByRole("button", { name: "Add local message" }).click();
  await expect(page.getByText("Please simplify the instructions")).toBeVisible();
  await page.getByRole("button", { name: "← Back to lesson" }).click();
  await expect(page.getByText("Please simplify the instructions")).toHaveCount(0);
});

test("source failure never masquerades as real curriculum data", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /View Assignment/ }).click();
  await page.getByLabel("Demo source scenario").selectOption("unavailable");
  await expect(page.getByRole("alert")).toContainText("not connected");
  await expect(page.getByRole("button", { name: "View full preview" })).toHaveCount(0);
  await page.getByLabel("Demo source scenario").selectOption("stale");
  await expect(page.getByRole("alert")).toContainText("Stale sample evidence");
  await page.getByLabel("Demo source scenario").selectOption("loading");
  await expect(page.getByRole("status").last()).toContainText("Simulated loading");
});

test("keyboard Escape closes carousel and restores trigger focus", async ({ page }) => {
  await page.goto("/");
  const trigger = page.getByRole("button", { name: /View Assignment/ });
  await trigger.focus();
  await trigger.press("Enter");
  await expect(page.getByRole("region", { name: "View Assignment" })).toBeVisible();
  await page.getByLabel("Course", { exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("region", { name: "View Assignment" })).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("narrow viewport has no horizontal page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto("/");
  await page.getByRole("button", { name: /View Assignment/ }).click();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});
