// D07 hosted negative control: disposable verification PR only, NEVER MERGE.
// The default Playwright config discovers *.spec.ts under tests/.
// Failure must propagate through the independent frontend lane and canonical gate.
import { test, expect } from "@playwright/test";

test("D07 deliberate Playwright browser failure must make CI red", async () => {
  expect(1).toBe(2);
});
