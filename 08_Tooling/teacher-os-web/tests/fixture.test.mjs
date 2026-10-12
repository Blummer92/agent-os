import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("fixture explicitly marks its content noncanonical and provides three materials", () => {
  const src = readFileSync(new URL("../src/fixtures.ts", import.meta.url), "utf8");
  assert.match(src, /NOT a Notion\/Drive projection/);
  for (const type of ['"unit"', '"worksheet"', '"slides"']) assert.ok(src.includes(type));
  assert.match(src, /grade: 9/);
  assert.match(src, /grade: 10/);
});
