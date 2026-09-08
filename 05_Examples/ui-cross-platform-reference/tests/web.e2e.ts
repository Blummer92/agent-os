import { expect, test } from "@playwright/test";

test("semantic form and keyboard dialog work in a browser", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Tasks" })).toBeVisible();
  await page.getByRole("button", { name: "Add task" }).click();
  await expect(page.getByRole("alert")).toContainText("Enter a task title.");
  const open = page.getByRole("button", { name: "Open help" });
  await open.focus();
  await open.press("Enter");
  await expect(page.getByRole("dialog", { name: "Task help" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(open).toBeFocused();
});
