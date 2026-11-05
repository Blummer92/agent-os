/**
 * Contract for the synthetic classroom FIXTURE (#2801 first slice).
 *
 * The fixture combines a lesson/planning projection, approved visual-selection
 * evidence, guided-practice context and a classroom-artifact projection. It is
 * decoded here exactly like live data is decoded in ./apiContract: nothing is
 * trusted by type assertion, unknown values are kept as inert text and never
 * widen what the teacher is told is usable. Pure and DOM-free so
 * `npm run test:unit` can run it under Node.
 *
 * Nothing in this module grants write, readiness or publication authority:
 * the assessments below only describe what sources say; they never approve.
 */
import { decodeSource, STALE_AFTER_MS, type Source } from "./apiContract.ts";

export const FIXTURE_SCHEMA = "teacher-os-classroom-fixture/v1";
const MAX_ITEMS = 50;
const MAX_TEXT = 600;
const MAX_AGE_MINUTES = 60 * 24 * 365;

export type Section<T> = Readonly<{ source: Source; ageMinutes: number; data: T }>;
export type VisualItem = Readonly<{ id: string; title: string; altText: string; diagram: string; selectionState: string; reviewedByRole: string; rationale: string }>;
export type PracticeStep = Readonly<{ id: string; minutes: number; prompt: string; check: string }>;
export type ArtifactItem = Readonly<{
  id: string; kind: string; title: string; notionState: string; driveState: string; accessState: string;
  locationLabel: string; movedToLabel: string | null;
}>;
export type ArtifactsSection =
  | Readonly<{ status: "ok"; source: Source; ageMinutes: number; items: readonly ArtifactItem[] }>
  | Readonly<{ status: "unavailable"; reason: string }>;
export type Projection = Readonly<{
  fixtureId: string; fixtureVersion: number; course: string; grade: number; unit: string;
  lesson: Readonly<{ ref: string; revision: number; dayLabel: string; target: string; focus: string; vocabulary: readonly string[]; readiness: string }>;
  planning: Section<null>;
  visual: Section<readonly VisualItem[]>;
  practice: Section<readonly PracticeStep[]>;
  artifacts: ArtifactsSection;
}>;
export type ProjectionState =
  | { kind: "idle" } | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "error"; reason: string }
  | { kind: "ready"; value: Projection };

type Body = Record<string, unknown>;
const isObject = (value: unknown): value is Body => typeof value === "object" && value !== null && !Array.isArray(value);
// Control and bidi-override characters are removed so a value can never reorder or hide text on screen.
const CONTROL = /[\u0000-\u001f\u007f-\u009f‎‏‪-‮⁦-⁩]/g;
const cleanText = (value: unknown, max = MAX_TEXT): string | null => {
  if (typeof value !== "string" || value.length > max) return null;
  const cleaned = value.replace(CONTROL, "").trim();
  return cleaned.length > 0 ? cleaned : null;
};
const cleanAge = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= MAX_AGE_MINUTES ? value : null;
const cleanList = <T>(value: unknown, one: (item: unknown) => T | null): readonly T[] | null => {
  if (!Array.isArray(value) || value.length > MAX_ITEMS) return null;
  const out: T[] = [];
  const ids = new Set<string>();
  for (const item of value) {
    const decoded = one(item);
    if (decoded === null) return null;
    const id = (decoded as { id?: string }).id;
    if (typeof id === "string") { if (ids.has(id)) return null; ids.add(id); }
    out.push(decoded);
  }
  return out;
};
function section<T>(value: unknown, data: (b: Body) => T | null): Section<T> | null {
  if (!isObject(value)) return null;
  const source = decodeSource(value.source);
  const age = cleanAge(value.age_minutes);
  const decoded = source && age !== null ? data(value) : null;
  return source && age !== null && decoded !== null ? { source, ageMinutes: age, data: decoded } : null;
}

function visual(item: unknown): VisualItem | null {
  if (!isObject(item)) return null;
  const f = { id: cleanText(item.id, 80), title: cleanText(item.title), altText: cleanText(item.alt_text), diagram: cleanText(item.diagram, 80),
    selectionState: cleanText(item.selection_state, 80), reviewedByRole: cleanText(item.reviewed_by_role, 80), rationale: cleanText(item.rationale) };
  return Object.values(f).every(v => v !== null) ? (f as VisualItem) : null;
}
function step(item: unknown): PracticeStep | null {
  if (!isObject(item)) return null;
  const id = cleanText(item.id, 80), prompt = cleanText(item.prompt), check = cleanText(item.check_for_understanding);
  const minutes = item.minutes;
  if (!id || !prompt || !check || typeof minutes !== "number" || !Number.isInteger(minutes) || minutes < 1 || minutes > 120) return null;
  return { id, minutes, prompt, check };
}
function artifact(item: unknown): ArtifactItem | null {
  if (!isObject(item)) return null;
  const f = { id: cleanText(item.id, 80), kind: cleanText(item.kind, 80), title: cleanText(item.title), notionState: cleanText(item.notion_state, 80),
    driveState: cleanText(item.drive_state, 80), accessState: cleanText(item.access_state, 80), locationLabel: cleanText(item.location_label, 300) };
  if (Object.values(f).some(v => v === null)) return null;
  const moved = item.moved_to_label === undefined || item.moved_to_label === null ? null : cleanText(item.moved_to_label, 300);
  if (item.moved_to_label !== undefined && item.moved_to_label !== null && moved === null) return null;
  return { ...(f as Omit<ArtifactItem, "movedToLabel">), movedToLabel: moved };
}

export function decodeProjection(body: unknown): ProjectionState {
  const bad: ProjectionState = { kind: "error", reason: "malformed-response" };
  if (!isObject(body) || body.schema !== FIXTURE_SCHEMA) return bad;
  if (body.status === "empty") return Object.keys(body).every(k => ["schema", "status", "fixture"].includes(k)) ? { kind: "empty" } : bad; // an "empty" envelope may not smuggle content
  const meta = body.fixture, course = body.course, unit = body.unit, lesson = body.lesson;
  if (!isObject(meta) || meta.synthetic !== true || meta.privacy !== "synthetic-no-student-data") return bad; // never render data that does not declare itself synthetic
  const fixtureId = cleanText(meta.id, 120);
  if (!fixtureId || typeof meta.version !== "number" || !Number.isInteger(meta.version) || meta.version < 1) return bad;
  if (!isObject(course) || !isObject(unit) || !isObject(lesson)) return bad;
  const courseTitle = cleanText(course.title, 200), unitTitle = cleanText(unit.title, 200);
  const ref = cleanText(lesson.lesson_ref, 120), dayLabel = cleanText(lesson.day_label, 200);
  const target = cleanText(lesson.learning_target), focus = cleanText(lesson.daily_focus), readiness = cleanText(lesson.readiness, 80);
  const vocabulary = cleanList(lesson.key_vocabulary, v => cleanText(v, 120));
  const revision = lesson.revision, grade = course.grade;
  if (!courseTitle || !unitTitle || !ref || !dayLabel || !target || !focus || !readiness || !vocabulary) return bad;
  if (typeof revision !== "number" || !Number.isInteger(revision) || revision < 1) return bad;
  if (typeof grade !== "number" || !Number.isInteger(grade) || grade < 1 || grade > 12) return bad;

  // Planning carries no payload of its own: it is the provenance/freshness envelope of the lesson record above.
  const planningEnvelope = isObject(body.planning) ? { source: decodeSource(body.planning.source), age: cleanAge(body.planning.age_minutes) } : null;
  if (!planningEnvelope?.source || planningEnvelope.age === null) return bad;
  const visualSection = section(body.visual_selection, b => cleanList(b.items, visual));
  const practiceSection = section(body.guided_practice, b => cleanList(b.steps, step));
  if (!visualSection || !practiceSection) return bad;

  let artifacts: ArtifactsSection;
  const art = body.artifacts;
  if (!isObject(art)) return bad;
  if (art.status === "unavailable") {
    artifacts = { status: "unavailable", reason: cleanText(art.reason_code, 80) ?? "unknown" };
  } else if (art.status === "ok") {
    const decoded = section(art, b => cleanList(b.items, artifact));
    if (!decoded) return bad;
    artifacts = { status: "ok", source: decoded.source, ageMinutes: decoded.ageMinutes, items: decoded.data };
  } else return bad;

  return { kind: "ready", value: {
    fixtureId, fixtureVersion: meta.version as number, course: courseTitle, grade, unit: unitTitle,
    lesson: { ref, revision, dayLabel, target, focus, vocabulary, readiness },
    planning: { source: planningEnvelope.source, ageMinutes: planningEnvelope.age, data: null },
    visual: visualSection, practice: practiceSection, artifacts,
  } };
}

/* ---------- Derived descriptions (never authority) ---------- */

export type Freshness = "current" | "stale";
export const freshness = (ageMinutes: number): Freshness => (ageMinutes * 60_000 <= STALE_AFTER_MS ? "current" : "stale");
export const ageText = (m: number) => (m < 1 ? "just now" : m < 60 ? `${Math.floor(m)} min old` : m < 2880 ? `${Math.floor(m / 60)} h old` : `${Math.floor(m / 1440)} days old`);

export type ArtifactAssessment = Readonly<{ status: "agree" | "moved" | "removed" | "permission" | "unlisted" | "unknown"; usable: boolean; headline: string; detail: string }>;
const KNOWN = {
  notion: ["listed-ready", "listed-draft", "not-listed"], drive: ["present", "moved", "removed"], access: ["teacher-can-open", "restricted"],
} as const;
const has = (list: readonly string[], value: string) => list.includes(value);

/**
 * Compare what Notion lists with what Drive reports. Only full agreement on
 * recognised values is "usable"; every other combination is described honestly
 * and withheld. Artifact existence is NOT readiness (that comes from the lesson
 * record) and nothing here authorises publication.
 */
export function assessArtifact(item: ArtifactItem): ArtifactAssessment {
  if (!has(KNOWN.notion, item.notionState) || !has(KNOWN.drive, item.driveState) || !has(KNOWN.access, item.accessState)) {
    return { status: "unknown", usable: false, headline: "Unrecognized source value", detail: "A source reported a value Teacher OS does not recognize. It is shown as text only and the material is not treated as available." };
  }
  if (item.driveState === "removed") return { status: "removed", usable: false, headline: "Removed from Drive", detail: item.notionState === "not-listed" ? "Drive reports it removed." : "Notion still lists it, but Drive reports it removed. Do not rely on it for tomorrow." };
  if (item.driveState === "moved") return { status: "moved", usable: false, headline: "Moved in Drive", detail: item.movedToLabel ? `Drive reports a new location: ${item.movedToLabel}. Confirm it before using it.` : "Drive reports it moved but gave no new location. Locate it before using it." };
  if (item.accessState === "restricted") return { status: "permission", usable: false, headline: "Permission mismatch", detail: "Drive restricts this file for the current teacher account. It is not opened or described further." };
  if (item.notionState === "not-listed") return { status: "unlisted", usable: false, headline: "In Drive, not listed in Notion", detail: "Notion does not list this file for the lesson, so it is not treated as part of tomorrow's plan." };
  if (item.notionState === "listed-draft") return { status: "unknown", usable: false, headline: "Listed as draft", detail: "Notion lists this as a draft, so it is not treated as ready." };
  return { status: "agree", usable: true, headline: "Notion and Drive agree", detail: "Present in Drive and listed in Notion. This does not mean the lesson is ready; readiness comes from the lesson record." };
}

export type Concern = Readonly<{ id: string; text: string }>;
/** Everything that needs the teacher's attention before relying on this lesson context. */
export function concerns(p: Projection): readonly Concern[] {
  const list: Concern[] = [];
  const stale = (label: string, age: number) => { if (freshness(age) === "stale") list.push({ id: `stale-${label}`, text: `${label} was read ${ageText(age)}; refresh before relying on it.` }); };
  stale("Lesson plan", p.planning.ageMinutes);
  stale("Visual selections", p.visual.ageMinutes);
  stale("Guided practice", p.practice.ageMinutes);
  if (p.artifacts.status === "unavailable") list.push({ id: "artifacts-unavailable", text: "Classroom materials are unavailable, so nothing about Drive is claimed." });
  else {
    stale("Classroom materials", p.artifacts.ageMinutes);
    for (const item of p.artifacts.items) { const a = assessArtifact(item); if (!a.usable) list.push({ id: `artifact-${item.id}`, text: `${item.title}: ${a.headline}.` }); }
  }
  if (p.lesson.readiness !== "teacher-reviewed") list.push({ id: "readiness", text: `Lesson readiness is "${p.lesson.readiness}", not teacher-reviewed.` });
  if (!p.visual.data.some(v => v.selectionState === "approved")) list.push({ id: "no-approved-visuals", text: "No approved visual selection is recorded." });
  return list;
}
