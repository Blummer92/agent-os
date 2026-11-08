/**
 * Runtime contract for the Teacher OS API (/api/teacher-os/*).
 *
 * Every response is decoded here before the UI sees it; nothing is trusted by
 * type assertion. A payload that does not match the contract is reported as
 * unavailable ("malformed-response") and renders no curriculum, so a broken or
 * spoofed backend can never put content on screen. This module is pure and
 * import-free so `npm run test:unit` can exercise it directly with Node's test
 * runner.
 */
export type Source = Readonly<{ display_name: string; verification_state: string; access: string }>;
export type Unit = Readonly<{ unit_id: string; title: string }>;
export type Lesson = Readonly<{
  day_lesson_number: string | null; daily_learning_target: string | null; daily_focus: string | null;
  key_vocabulary: string | null; source_evidence: string | null; record_url: string | null;
}>;
export type Loaded<T> = Readonly<{ data: T; source: Source; generatedAt: string }>;
export type LoadState<T> =
  | { kind: "idle" } | { kind: "loading" }
  | { kind: "empty"; generatedAt: string; source: Source }
  | { kind: "unavailable" | "error" | "unauthorized"; reason: string }
  | { kind: "ready"; value: Loaded<T> };

/** Reason codes the API may publish; anything else is shown as "unknown". */
export const REASON_CODES: readonly string[] = [
  "admission-required", "not-configured", "source-unverified", "unit-not-approved", "read-failed",
  "invalid-request", "not-found", "method-not-allowed", "rate-limited",
  "unauthenticated", "host-not-allowed", "origin-not-allowed",
];
const UNAUTHORIZED = ["unauthenticated", "host-not-allowed", "origin-not-allowed"];

/** Evidence older than this is shown as stale rather than current. */
export const STALE_AFTER_MS = 15 * 60_000;
export const MAX_ITEMS = 500;
const MAX_TEXT = 5000;
const MAX_LABEL = 300;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/;
const LESSON_TEXT_FIELDS = ["day_lesson_number", "daily_learning_target", "daily_focus", "key_vocabulary", "source_evidence"] as const;

type Body = Record<string, unknown>;
const malformed = { kind: "unavailable", reason: "malformed-response" } as const;

const isObject = (value: unknown): value is Body => typeof value === "object" && value !== null && !Array.isArray(value);
// Control and bidi-override characters in a label are refused outright: they can reorder or hide text on screen.
const HIDDEN_CHARS = /[\u0000-\u001f\u007f-\u009f\u200e\u200f\u202a-\u202e\u2066-\u2069]/;
const isLabel = (value: unknown, max = MAX_LABEL): value is string => typeof value === "string" && value.trim().length > 0 && value.length <= max && !HIDDEN_CHARS.test(value);

/** Only links to Notion records are rendered; anything else is dropped (never followed). */
export function safeRecordUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2048) return null;
  let url: URL;
  try { url = new URL(value); } catch { return null; }
  if (url.protocol !== "https:" || url.username || url.password || url.port) return null;
  const host = url.hostname.toLowerCase();
  return host === "www.notion.so" || host === "notion.so" || host.endsWith(".notion.site") ? url.href : null;
}

export function decodeSource(value: unknown): Source | null {
  if (!isObject(value)) return null;
  const { display_name, verification_state, access } = value;
  if (!isLabel(display_name)) return null;
  // The trust contract is exact: anything but what the server emits is not verified, read-only curriculum.
  if (verification_state !== "verified-current" || access !== "read-only") return null;
  return { display_name, verification_state, access };
}

export function decodeUnitList(value: unknown): readonly Unit[] | null {
  if (!Array.isArray(value) || value.length > MAX_ITEMS) return null;
  const seen = new Set<string>();
  const units: Unit[] = [];
  for (const item of value) {
    if (!isObject(item) || typeof item.unit_id !== "string" || !UUID.test(item.unit_id) || !isLabel(item.title)) return null;
    if (seen.has(item.unit_id)) return null;
    seen.add(item.unit_id);
    units.push({ unit_id: item.unit_id, title: item.title });
  }
  return units;
}

export function decodeLessonList(value: unknown, unitId: string): readonly Lesson[] | null {
  if (!Array.isArray(value) || value.length > MAX_ITEMS) return null;
  const lessons: Lesson[] = [];
  for (const item of value) {
    if (!isObject(item)) return null;
    // Every lesson must itself name the requested unit; the envelope alone is not enough.
    const relation = item.canonical_unit;
    if (!isObject(relation) || typeof relation.page_id !== "string" || relation.page_id.toLowerCase() !== unitId.toLowerCase()) return null;
    const fields: Record<string, string | null> = {};
    for (const name of LESSON_TEXT_FIELDS) {
      const field = item[name];
      if (field === null || field === undefined) fields[name] = null;
      else if (typeof field === "string" && field.length <= MAX_TEXT) fields[name] = field.trim() ? field : null;
      else return null;
    }
    lessons.push({
      day_lesson_number: fields.day_lesson_number, daily_learning_target: fields.daily_learning_target,
      daily_focus: fields.daily_focus, key_vocabulary: fields.key_vocabulary, source_evidence: fields.source_evidence,
      record_url: safeRecordUrl(item.record_url),
    });
  }
  return lessons;
}

/**
 * Decode one HTTP response. `pick` extracts the list for an ok/empty body and
 * returns null when it does not match the contract.
 */
export function decodeResponse<T extends readonly unknown[]>(httpStatus: number, body: unknown, pick: (body: Body) => T | null): LoadState<T> {
  if (!isObject(body)) return malformed;
  const status = body.status;
  if (status === "error" || status === "unavailable") {
    const reason = typeof body.reason_code === "string" && REASON_CODES.includes(body.reason_code) ? body.reason_code : "unknown";
    if (httpStatus === 200) return malformed; // a failure envelope must not arrive as a success
    if (UNAUTHORIZED.includes(reason) || httpStatus === 401) return { kind: "unauthorized", reason: reason === "unknown" ? "unauthenticated" : reason };
    return { kind: status, reason };
  }
  if (status !== "ok" && status !== "empty") return malformed;
  if (httpStatus !== 200) return malformed;
  const source = decodeSource(body.source);
  const generatedAt = body.generated_at;
  if (!source || typeof generatedAt !== "string" || !TIMESTAMP.test(generatedAt) || Number.isNaN(Date.parse(generatedAt))) return malformed;
  const data = pick(body);
  if (data === null) return malformed;
  if (status === "empty") return data.length === 0 ? { kind: "empty", generatedAt, source } : malformed;
  return data.length > 0 ? { kind: "ready", value: { data, source, generatedAt } } : malformed;
}

export const decodeUnits = (httpStatus: number, body: unknown) =>
  decodeResponse(httpStatus, body, b => (b.units === undefined && b.status === "empty" ? [] : decodeUnitList(b.units)));

/** Lessons must belong to the unit that was requested; a response naming another unit is refused. */
export const decodeLessons = (httpStatus: number, body: unknown, unitId: string) =>
  decodeResponse(httpStatus, body, b => {
    if (b.unit !== undefined && b.unit !== null && (!isObject(b.unit) || b.unit.unit_id !== unitId)) return null;
    return b.lessons === undefined && b.status === "empty" ? [] : decodeLessonList(b.lessons, unitId);
  });

export const isStale = (generatedAt: string, now = Date.now()) => !(now - Date.parse(generatedAt) <= STALE_AFTER_MS);

/** Short relative age for a provenance line, e.g. "just now", "4 min ago". */
export function readAge(generatedAt: string, now = Date.now()): string {
  const ms = now - Date.parse(generatedAt);
  if (!Number.isFinite(ms)) return "unknown time";
  if (ms < 60_000) return "just now";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.floor(hours / 24)} days ago`;
}
