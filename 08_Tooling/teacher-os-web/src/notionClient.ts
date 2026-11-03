/** Browser client for the Teacher OS Notion bridge. Holds no credential and no curriculum content. */
export type Source = Readonly<{ display_name: string; verification_state: string; access: string }>;
export type Unit = Readonly<{ unit_id: string; title: string }>;
export type Lesson = Readonly<{
  day_lesson_number: string | null; daily_learning_target: string | null; daily_focus: string | null;
  key_vocabulary: string | null; source_evidence: string | null; record_url: string | null;
}>;
export type Loaded<T> = Readonly<{ data: T; source: Source; generatedAt: string }>;
export type LoadState<T> =
  | { kind: "idle" } | { kind: "loading" } | { kind: "empty"; generatedAt: string }
  | { kind: "unavailable" | "error"; reason: string }
  | { kind: "ready"; value: Loaded<T> };

/** Evidence older than this is shown as stale rather than current. */
export const STALE_AFTER_MS = 15 * 60_000;

async function load<T>(url: string, pick: (body: Record<string, unknown>) => T, signal: AbortSignal): Promise<LoadState<T>> {
  let response: Response;
  try { response = await fetch(url, { signal, headers: { accept: "application/json" } }); }
  catch (error) { if (signal.aborted) throw error; return { kind: "unavailable", reason: "reader-unreachable" }; }
  let body: Record<string, unknown>;
  try { body = await response.json(); } catch { return { kind: "unavailable", reason: "reader-unavailable" }; }
  const reason = typeof body.reason_code === "string" ? body.reason_code : "unknown";
  if (body.status === "unavailable") return { kind: "unavailable", reason };
  if (!response.ok || (body.status !== "ok" && body.status !== "empty")) return { kind: "error", reason };
  const generatedAt = String(body.generated_at ?? "");
  if (body.status === "empty") return { kind: "empty", generatedAt };
  return { kind: "ready", value: { data: pick(body), source: body.source as Source, generatedAt } };
}

export const fetchUnits = (signal: AbortSignal) =>
  load("/api/teacher-os/units", body => body.units as readonly Unit[], signal);
export const fetchLessons = (unitId: string, signal: AbortSignal) =>
  load(`/api/teacher-os/units/${encodeURIComponent(unitId)}/lessons`, body => body.lessons as readonly Lesson[], signal);
export const isStale = (generatedAt: string, now = Date.now()) => !(now - Date.parse(generatedAt) <= STALE_AFTER_MS);
