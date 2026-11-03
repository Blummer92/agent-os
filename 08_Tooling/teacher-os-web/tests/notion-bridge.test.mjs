import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createBridge, runReader } from "../server/notionBridge.mjs";

const UNIT = "3907ac78-3131-8132-8f84-f9fd633acba5";
const NOW = () => new Date("2026-11-03T12:00:00Z");

async function call(url, run, method = "GET") {
  const res = { headers: {}, setHeader(k, v) { this.headers[k] = v; }, end(body) { this.body = JSON.parse(body); } };
  let passed = false;
  await createBridge({ run, now: NOW })({ url, method }, res, () => { passed = true; });
  return { res, passed };
}

test("units route spawns the governed reader with a bounded argv and returns its JSON", async () => {
  let args;
  const payload = { result_kind: "agent-os-teacher-os-read-result", status: "ok", units: [{ unit_id: UNIT, title: "X" }] };
  const { res } = await call("/api/teacher-os/units", async a => { args = a; return JSON.stringify(payload); });
  assert.deepEqual(args, ["--generated-at", "2026-11-03T12:00:00.000Z", "units"]);
  assert.equal(res.statusCode, 200);
  assert.equal(res.headers["cache-control"], "no-store");
  assert.deepEqual(res.body, payload);
});

test("lesson route passes only a validated unit id", async () => {
  let args;
  await call(`/api/teacher-os/units/${UNIT}/lessons`, async a => { args = a; return JSON.stringify({ result_kind: "agent-os-teacher-os-read-result", status: "empty" }); });
  assert.deepEqual(args.slice(-3), ["lessons", "--unit-id", UNIT]);
});

for (const bad of ["not-a-uuid", "..%2F..%2Fetc", `${UNIT}%3Brm`, "%20"]) {
  test(`malformed unit id ${bad} is rejected without running the reader`, async () => {
    let ran = false;
    const { res } = await call(`/api/teacher-os/units/${bad}/lessons`, async () => { ran = true; return "{}"; });
    assert.equal(res.statusCode, 400);
    assert.equal(ran, false);
  });
}

test("non-GET and unrelated paths are not served", async () => {
  assert.equal((await call("/api/teacher-os/units", async () => "{}", "POST")).res.statusCode, 405);
  assert.equal((await call("/other", async () => "{}")).passed, true);
});

test("negative control: unavailable, unparseable or foreign reader output is unavailable, never content", async () => {
  for (const out of ["", "not json", JSON.stringify({ status: "ok", lessons: [{ daily_focus: "x" }] })]) {
    const { res } = await call("/api/teacher-os/units", async () => out);
    assert.equal(res.statusCode, 503);
    assert.deepEqual(res.body, { status: "unavailable", reason_code: "reader-unavailable" });
  }
  const unavailable = { result_kind: "agent-os-teacher-os-read-result", status: "unavailable", reason_code: "not-configured" };
  assert.equal((await call("/api/teacher-os/units", async () => JSON.stringify(unavailable))).res.statusCode, 503);
  assert.equal((await call("/api/teacher-os/units", async () => JSON.stringify({ ...unavailable, status: "error" }))).res.statusCode, 502);
});

test("no production source embeds curriculum content or reads a Notion credential in the browser", () => {
  const dir = new URL("../src/", import.meta.url);
  for (const name of readdirSync(dir)) {
    const text = readFileSync(new URL(name, dir), "utf8");
    assert.doesNotMatch(text, /Photography Foundations|Graphic Design|Rule of Thirds|NOTION_TOKEN|VITE_NOTION|api\.notion\.com/i, name);
  }
  assert.throws(() => readFileSync(new URL("fixtures.ts", dir)), { code: "ENOENT" });
});

test("the real reader process is importable and, with no credential, reports not-configured", async () => {
  const saved = process.env.NOTION_TOKEN;
  delete process.env.NOTION_TOKEN;
  try {
    const body = JSON.parse(await runReader(["--generated-at", "2026-11-03T12:00:00Z", "units"]));
    assert.deepEqual(body, { reason_code: "not-configured", result_kind: "agent-os-teacher-os-read-result", schema_version: "1.0", status: "unavailable" });
  } finally { if (saved !== undefined) process.env.NOTION_TOKEN = saved; }
});
