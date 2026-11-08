// Unit tests for the Teacher OS API runtime contract (run by `npm run test:unit`).
// Every payload here is SYNTHETIC; none of it is curriculum or Notion evidence.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  REASON_CODES, decodeLessons, decodeUnits, isStale, readAge, safeRecordUrl,
} from "../../src/apiContract.ts";

const SRC = { logical_source: "canonical-unit", display_name: "Synthetic Registry", verification_state: "verified-current", access: "read-only" };
const AT = "2026-11-04T12:00:00Z";
const A = "aaaaaaaa-0000-4000-8000-000000000001";
const B = "bbbbbbbb-0000-4000-8000-000000000002";
const unitsBody = (units: unknown, extra = {}) => ({ status: "ok", source: SRC, generated_at: AT, units, ...extra });
const lesson = (n: number, extra = {}) => ({
  day_lesson_number: `Day ${n}`, daily_learning_target: `Target ${n}`, daily_focus: `Focus ${n}`, key_vocabulary: null,
  source_evidence: `Evidence ${n}`, record_url: `https://www.notion.so/${n}`, canonical_unit: { page_id: A }, ...extra,
});
const lessonsBody = (lessons: unknown, extra = {}) => ({ status: "ok", source: SRC, generated_at: AT, unit: { unit_id: A, title: "T" }, lessons, ...extra });

test("a valid units response decodes to exactly the contract fields", () => {
  const state = decodeUnits(200, unitsBody([{ unit_id: A, title: "Alpha", extra: "dropped" }]));
  assert.equal(state.kind, "ready");
  if (state.kind !== "ready") return;
  assert.deepEqual(state.value.data, [{ unit_id: A, title: "Alpha" }]);
  assert.deepEqual(state.value.source, { display_name: "Synthetic Registry", verification_state: "verified-current", access: "read-only" });
  assert.equal(state.value.generatedAt, AT);
});

test("empty responses are empty, never ready, with or without an empty list", () => {
  assert.equal(decodeUnits(200, { status: "empty", source: SRC, generated_at: AT }).kind, "empty");
  assert.equal(decodeUnits(200, { status: "empty", source: SRC, generated_at: AT, units: [] }).kind, "empty");
  assert.equal(decodeLessons(200, { status: "empty", source: SRC, generated_at: AT, lessons: [] }, A).kind, "empty");
  // contradictory envelopes are malformed rather than guessed
  assert.deepEqual(decodeUnits(200, { status: "empty", source: SRC, generated_at: AT, units: [{ unit_id: A, title: "x" }] }), { kind: "unavailable", reason: "malformed-response" });
  assert.deepEqual(decodeUnits(200, unitsBody([])), { kind: "unavailable", reason: "malformed-response" });
});

const MALFORMED_UNITS: [string, unknown][] = [
  ["non-object body", "nope"], ["array body", []], ["null body", null],
  ["unknown status", { ...unitsBody([{ unit_id: A, title: "x" }]), status: "maybe" }],
  ["missing source", { status: "ok", generated_at: AT, units: [{ unit_id: A, title: "x" }] }],
  ["source with a non-string field", unitsBody([{ unit_id: A, title: "x" }], { source: { ...SRC, display_name: 7 } })],
  ["blank source label", unitsBody([{ unit_id: A, title: "x" }], { source: { ...SRC, access: " " } })],
  ["missing timestamp", { status: "ok", source: SRC, units: [{ unit_id: A, title: "x" }] }],
  ["non-ISO timestamp", unitsBody([{ unit_id: A, title: "x" }], { generated_at: "yesterday" })],
  ["timezone-less timestamp", unitsBody([{ unit_id: A, title: "x" }], { generated_at: "2026-11-04T12:00:00" })],
  ["units not a list", unitsBody({ unit_id: A })],
  ["uppercase uuid", unitsBody([{ unit_id: A.toUpperCase(), title: "x" }])],
  ["compact uuid", unitsBody([{ unit_id: A.replace(/-/g, ""), title: "x" }])],
  ["path-traversal id", unitsBody([{ unit_id: "../../etc", title: "x" }])],
  ["empty title", unitsBody([{ unit_id: A, title: "" }])],
  ["non-string title", unitsBody([{ unit_id: A, title: ["x"] }])],
  ["oversized title", unitsBody([{ unit_id: A, title: "x".repeat(301) }])],
  ["duplicate unit", unitsBody([{ unit_id: A, title: "x" }, { unit_id: A, title: "y" }])],
  ["too many units", unitsBody(Array.from({ length: 501 }, (_, i) => ({ unit_id: `aaaaaaaa-0000-4000-8000-${String(i).padStart(12, "0")}`, title: "x" })))],
];
for (const [name, body] of MALFORMED_UNITS) {
  test(`malformed units response is refused: ${name}`, () => {
    assert.deepEqual(decodeUnits(200, body), { kind: "unavailable", reason: "malformed-response" });
  });
}

test("a success envelope on a non-200 status, or a failure envelope on 200, is malformed", () => {
  assert.equal(decodeUnits(500, unitsBody([{ unit_id: A, title: "x" }])).kind, "unavailable");
  assert.deepEqual(decodeUnits(200, { status: "error", reason_code: "read-failed" }), { kind: "unavailable", reason: "malformed-response" });
});

test("failure envelopes map to closed reasons and the right state", () => {
  assert.deepEqual(decodeUnits(503, { status: "unavailable", reason_code: "admission-required" }), { kind: "unavailable", reason: "admission-required" });
  assert.deepEqual(decodeUnits(502, { status: "error", reason_code: "read-failed" }), { kind: "error", reason: "read-failed" });
  assert.deepEqual(decodeUnits(429, { status: "error", reason_code: "rate-limited" }), { kind: "error", reason: "rate-limited" });
  for (const reason of ["unauthenticated", "host-not-allowed", "origin-not-allowed"]) {
    assert.deepEqual(decodeUnits(reason === "unauthenticated" ? 401 : 403, { status: "error", reason_code: reason }), { kind: "unauthorized", reason });
  }
  // an unknown reason is never echoed into the UI
  assert.deepEqual(decodeUnits(502, { status: "error", reason_code: "<script>alert(1)</script>" }), { kind: "error", reason: "unknown" });
  assert.deepEqual(decodeUnits(401, { status: "error" }), { kind: "unauthorized", reason: "unauthenticated" });
  assert.ok(REASON_CODES.includes("admission-required"));
});

test("lessons decode with null for missing or blank fields and never invent text", () => {
  const state = decodeLessons(200, lessonsBody([lesson(1), lesson(2, { daily_learning_target: "   ", key_vocabulary: undefined })]), A);
  assert.equal(state.kind, "ready");
  if (state.kind !== "ready") return;
  assert.equal(state.value.data.length, 2);
  assert.equal(state.value.data[1].daily_learning_target, null);
  assert.equal(state.value.data[1].key_vocabulary, null);
  assert.deepEqual(Object.keys(state.value.data[0]).sort(), ["daily_focus", "daily_learning_target", "day_lesson_number", "key_vocabulary", "record_url", "source_evidence"]);
});

test("lessons that name a different unit than requested are refused", () => {
  assert.deepEqual(decodeLessons(200, lessonsBody([lesson(1)], { unit: { unit_id: B, title: "Other" } }), A), { kind: "unavailable", reason: "malformed-response" });
  assert.deepEqual(decodeLessons(200, lessonsBody([lesson(1)], { unit: "A" }), A), { kind: "unavailable", reason: "malformed-response" });
  assert.equal(decodeLessons(200, lessonsBody([lesson(1)], { unit: undefined }), A).kind, "ready");
});

const MALFORMED_LESSONS: [string, unknown][] = [
  ["lessons not a list", lessonsBody("Day 1")],
  ["lesson not an object", lessonsBody(["Day 1"])],
  ["numeric field", lessonsBody([lesson(1, { daily_focus: 42 })])],
  ["object field", lessonsBody([lesson(1, { daily_learning_target: { text: "x" } })])],
  ["oversized field", lessonsBody([lesson(1, { source_evidence: "x".repeat(5001) })])],
];
for (const [name, body] of MALFORMED_LESSONS) {
  test(`malformed lessons response is refused: ${name}`, () => {
    assert.deepEqual(decodeLessons(200, body, A), { kind: "unavailable", reason: "malformed-response" });
  });
}

test("only https Notion record links survive; everything else becomes null", () => {
  assert.equal(safeRecordUrl("https://www.notion.so/abc"), "https://www.notion.so/abc");
  assert.equal(safeRecordUrl("https://team.notion.site/page"), "https://team.notion.site/page");
  for (const bad of ["http://www.notion.so/abc", "javascript:alert(1)", "https://evil.example/notion.so", "https://www.notion.so.evil.example/x",
    "https://user:pw@www.notion.so/x", "https://www.notion.so:8443/x", "notion.so/x", "", 5, null]) {
    assert.equal(safeRecordUrl(bad), null, String(bad));
  }
  const state = decodeLessons(200, lessonsBody([lesson(1, { record_url: "javascript:alert(1)" })]), A);
  assert.ok(state.kind === "ready" && state.value.data[0].record_url === null);
});

test("staleness and read age are computed from the server timestamp", () => {
  const now = Date.parse(AT);
  assert.equal(isStale(AT, now + 14 * 60_000), false);
  assert.equal(isStale(AT, now + 16 * 60_000), true);
  assert.equal(isStale("garbage", now), true);
  assert.equal(readAge(AT, now + 10_000), "just now");
  assert.equal(readAge(AT, now + 5 * 60_000), "5 min ago");
  assert.equal(readAge(AT, now + 3 * 3_600_000), "3 h ago");
  assert.equal(readAge("garbage", now), "unknown time");
});

test("labels with control or bidi-override characters are refused, not rendered", () => {
  for (const bad of ["\u202eevil", "a\u0000b", "x\u2066y"]) {
    const body = { status: "ok", units: [{ unit_id: A, title: "Unit" }], source: { ...SRC, display_name: bad }, generated_at: AT };
    assert.equal(decodeUnits(200, body).kind, "unavailable", JSON.stringify(bad));
    const titled = { status: "ok", units: [{ unit_id: A, title: bad }], source: SRC, generated_at: AT };
    assert.equal(decodeUnits(200, titled).kind, "unavailable", JSON.stringify(bad));
  }
});

test("a source that is not verified-current and read-only is refused before curriculum is exposed", () => {
  for (const source of [
    { ...SRC, verification_state: "unverified" }, { ...SRC, access: "write" },
    { ...SRC, verification_state: "VERIFIED-CURRENT" }, { ...SRC, access: "read-write" },
  ]) {
    assert.deepEqual(decodeUnits(200, unitsBody([{ unit_id: A, title: "x" }], { source })), { kind: "unavailable", reason: "malformed-response" });
    assert.deepEqual(decodeLessons(200, lessonsBody([lesson(1)], { source }), A), { kind: "unavailable", reason: "malformed-response" });
  }
});

test("every lesson must name the requested unit, not just the envelope", () => {
  const bad: unknown[] = [
    lesson(2, { canonical_unit: { page_id: B } }), lesson(2, { canonical_unit: undefined }),
    lesson(2, { canonical_unit: null }), lesson(2, { canonical_unit: { page_id: 7 } }), lesson(2, { canonical_unit: "a" }),
  ];
  for (const item of bad) {
    assert.deepEqual(decodeLessons(200, lessonsBody([lesson(1), item]), A), { kind: "unavailable", reason: "malformed-response" });
  }
  assert.equal(decodeLessons(200, lessonsBody([lesson(1), lesson(2)]), A).kind, "ready");
});
