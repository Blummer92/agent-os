// Unit tests for the synthetic classroom fixture contract, scenarios and the
// Notion/Drive assessment. Run by `npm run test:unit`. All data is SYNTHETIC.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { ageText, agoText, assessArtifact, concerns, decodeFixtureSource, decodeProjection, freshness, type ArtifactItem } from "../../src/fixtureContract.ts";
import { SCENARIOS, applyScenario, isScenario } from "../../src/fixtureScenarios.ts";

const PATH = new URL("../../public/fixture/classroom-fixture.v1.json", import.meta.url);
const RAW = readFileSync(PATH);
const BODY = JSON.parse(RAW.toString("utf8"));
// Immutability pin: changing the fixture must be a deliberate, reviewed change to this hash (and a new version).
const FIXTURE_SHA256 = "be3a951cebc08876680268043537eebeb48617878c98d6bdcd2c00fa696fdc5a";
const ready = (body: unknown) => { const s = decodeProjection(body); assert.equal(s.kind, "ready", JSON.stringify(s)); return s.kind === "ready" ? s.value : (undefined as never); };
const mutate = (fn: (b: any) => void) => { const b = structuredClone(BODY); fn(b); return b; }; // eslint-disable-line @typescript-eslint/no-explicit-any
const art = (over: Partial<ArtifactItem> = {}): ArtifactItem => ({ id: "a", kind: "worksheet", title: "T", notionState: "listed-ready", driveState: "present", accessState: "teacher-can-open", locationLabel: "L", movedToLabel: null, ...over });

test("fixture file is pinned (immutable) and declares itself synthetic", () => {
  assert.equal(createHash("sha256").update(RAW).digest("hex"), FIXTURE_SHA256);
  assert.equal(BODY.fixture.synthetic, true);
  assert.equal(BODY.fixture.privacy, "synthetic-no-student-data");
});

test("fixture is privacy-safe: no emails, links, phone numbers, ids or student-like fields", () => {
  const text = RAW.toString("utf8");
  assert.doesNotMatch(text, /@|https?:|www\.|\b\d{3}[-. ]\d{3,4}[-. ]\d{4}\b/);
  assert.doesNotMatch(text, /"(student|email|phone|address|token|secret|password|url|link)[a-z_]*"\s*:/i);
});

test("fixture decodes and combines lesson plan, approved visual evidence, guided practice and artifacts", () => {
  const p = ready(BODY);
  assert.equal(p.lesson.revision, 3);
  assert.equal(p.visual.data.filter(v => v.selectionState === "approved").length, 2);
  assert.equal(p.practice.data.length, 3);
  assert.equal(p.artifacts.status, "ok");
});

test("the canonical fixture has no concerns; every source is current", () => {
  const p = ready(BODY);
  assert.equal(concerns(p).length, 0);
  for (const age of [p.planning.ageMinutes, p.visual.ageMinutes, p.practice.ageMinutes]) assert.equal(freshness(age), "current");
});

test("scenarios are deterministic, never mutate the source, and every variant passes the same decoder", () => {
  const before = JSON.stringify(BODY);
  for (const s of SCENARIOS) {
    const a = JSON.stringify(applyScenario(BODY, s.id, 0));
    assert.equal(a, JSON.stringify(applyScenario(BODY, s.id, 0)), s.id);
    const state = decodeProjection(applyScenario(BODY, s.id, 0));
    assert.equal(state.kind, s.id === "empty" ? "empty" : "ready", s.id);
  }
  assert.equal(JSON.stringify(BODY), before);
});

test("scenario ids are validated", () => {
  assert.ok(isScenario("stale"));
  for (const bad of ["", "STALE", "__proto__", null, undefined, 3, "stale ", "../x"]) assert.equal(isScenario(bad), false);
});

test("stale scenario reports each source as stale and says so", () => {
  const p = ready(applyScenario(BODY, "stale"));
  const ids = concerns(p).map(c => c.id);
  assert.deepEqual(ids, ["stale-Lesson plan", "stale-Visual selections", "stale-Guided practice", "stale-Classroom materials"]);
  assert.equal(freshness(15), "current"); assert.equal(freshness(15.01), "stale");
});

test("degraded scenario withholds Drive claims instead of guessing", () => {
  const p = ready(applyScenario(BODY, "degraded"));
  assert.equal(p.artifacts.status, "unavailable");
  assert.deepEqual(concerns(p).map(c => c.id), ["artifacts-unavailable"]);
});

test("Notion lists it but Drive removed it: disagreement is surfaced and the file is not usable", () => {
  const a = assessArtifact(art({ driveState: "removed" }));
  assert.equal(a.status, "removed"); assert.equal(a.usable, false); assert.match(a.detail, /Notion still lists it/);
  const p = ready(applyScenario(BODY, "disagreement"));
  assert.deepEqual(concerns(p).map(c => c.id), ["artifact-art-1"]);
});

test("moved artifact reports the new location but is still withheld until confirmed", () => {
  const a = assessArtifact(art({ driveState: "moved", movedToLabel: "Archive" }));
  assert.equal(a.status, "moved"); assert.equal(a.usable, false); assert.match(a.detail, /Archive/);
  assert.match(assessArtifact(art({ driveState: "moved" })).detail, /no new location/);
});

test("permission mismatch is withheld and reveals nothing more", () => {
  const a = assessArtifact(art({ accessState: "restricted" }));
  assert.equal(a.status, "permission"); assert.equal(a.usable, false);
});

test("restricted outranks moved and removed (recognized access): no location, no Drive state leaks", () => {
  for (const driveState of ["moved", "removed", "present"]) {
    const a = assessArtifact(art({ accessState: "restricted", driveState, movedToLabel: "Drive > SECRET NEW HOME" }));
    assert.equal(a.status, "permission", driveState);
    assert.doesNotMatch(a.detail + a.headline, /SECRET|moved|removed|new location/i, driveState);
  }
});

test("provenance must declare itself fixture-verified, read-only and Fixture-named; hidden characters are refused", () => {
  const ok = { display_name: "Fixture x", verification_state: "fixture-verified", access: "read-only" };
  assert.deepEqual(decodeFixtureSource(ok), ok);
  for (const bad of [{ ...ok, verification_state: "notion-verified" }, { ...ok, access: "read-write" }, { ...ok, display_name: "Notion x" },
    { ...ok, display_name: "\u202eFixture x" }, { ...ok, access: "read-only\u0000" }, { ...ok, display_name: "" }, null, [], "x"]) assert.equal(decodeFixtureSource(bad), null, JSON.stringify(bad));
  assert.equal(decodeProjection(mutate(b => { b.visual_selection.source.verification_state = "notion-verified"; })).kind, "error");
  assert.equal(decodeProjection(mutate(b => { b.artifacts.source.access = "read-write"; })).kind, "error");
});

test("empty materials or empty practice is a concern, so 'Context is current' is never vacuous", () => {
  const p = ready(mutate(b => { b.artifacts.items = []; b.guided_practice.steps = []; }));
  assert.deepEqual(concerns(p).map(c => c.id), ["no-materials", "no-practice"]);
});

test("only full agreement on recognized values is usable; unknown values are never usable", () => {
  assert.equal(assessArtifact(art()).usable, true);
  for (const over of [{ notionState: "quantum-ready" }, { driveState: "teleported" }, { accessState: "root" }, { notionState: "listed-draft" }, { notionState: "not-listed" }])
    assert.equal(assessArtifact(art(over)).usable, false, JSON.stringify(over));
  // removal outranks an unrecognized Notion value only when every value is recognized
  assert.equal(assessArtifact(art({ notionState: "quantum-ready", driveState: "removed" })).status, "unknown");
});

test("unknown projection values are kept as inert text, not trusted or dropped silently", () => {
  const p = ready(applyScenario(BODY, "unknown"));
  assert.equal(p.visual.data[2].selectionState, "<b>approved!</b>");
  assert.equal(concerns(p).some(c => c.id === "artifact-art-1"), true);
});

test("control and bidi characters are stripped from text", () => {
  const p = ready(mutate(b => { b.lesson.daily_focus = "A‮B\u0000C"; }));
  assert.equal(p.lesson.focus, "ABC");
});

test("stale lesson context: a later read with a new revision is detectable", () => {
  const first = ready(applyScenario(BODY, "context-changed", 0));
  const second = ready(applyScenario(BODY, "context-changed", 1));
  assert.equal(first.lesson.revision, 3); assert.equal(second.lesson.revision, 4);
  assert.notEqual(first.lesson.focus, second.lesson.focus);
});

test("empty envelope cannot smuggle content", () => {
  assert.equal(decodeProjection({ schema: BODY.schema, status: "empty", fixture: BODY.fixture }).kind, "empty");
  assert.equal(decodeProjection({ ...BODY, status: "empty" }).kind, "error");
});

test("malformed, non-synthetic, wrong-schema and oversized payloads are refused", () => {
  const refused: unknown[] = [null, [], "x", {}, 7,
    mutate(b => { b.schema = "other/v1"; }),
    mutate(b => { b.fixture.synthetic = false; }),
    mutate(b => { b.fixture.privacy = "contains-student-data"; }),
    mutate(b => { delete b.lesson; }),
    mutate(b => { b.lesson.revision = 0; }),
    mutate(b => { b.lesson.revision = 1.5; }),
    mutate(b => { b.lesson.key_vocabulary = "not a list"; }),
    mutate(b => { b.planning.age_minutes = -1; }),
    mutate(b => { b.planning.age_minutes = "4"; }),
    mutate(b => { b.planning.source = { display_name: "x" }; }),
    mutate(b => { b.visual_selection.items[0].selection_state = ""; }),
    mutate(b => { b.visual_selection.items[1].id = b.visual_selection.items[0].id; }),
    mutate(b => { b.guided_practice.steps[0].minutes = 0; }),
    mutate(b => { b.artifacts.status = "weird"; }),
    mutate(b => { b.artifacts.items[0].moved_to_label = 5; }),
    mutate(b => { b.lesson.daily_focus = "x".repeat(601); }),
    mutate(b => { b.visual_selection.items = Array.from({ length: 51 }, (_, i) => ({ ...b.visual_selection.items[0], id: `v${i}` })); }),
  ];
  for (const body of refused) assert.equal(decodeProjection(body).kind, "error", JSON.stringify(body)?.slice(0, 80));
});

test("age text is honest at boundaries", () => {
  assert.equal(ageText(0), "just now"); assert.equal(ageText(4), "4 min old"); assert.equal(ageText(60), "1 h old"); assert.equal(ageText(2880), "2 days old");
  assert.equal(agoText(47), "47 min ago"); assert.equal(agoText(0), "just now"); assert.equal(agoText(120), "2 h ago"); assert.equal(agoText(2880), "2 days ago");
});

test("an unreviewed lesson and a missing approved visual are concerns, never silently fine", () => {
  assert.ok(concerns(ready(mutate(b => { b.lesson.readiness = "draft"; }))).some(c => c.id === "readiness"));
  assert.ok(concerns(ready(mutate(b => { for (const v of b.visual_selection.items) v.selection_state = "pending-review"; }))).some(c => c.id === "no-approved-visuals"));
});
