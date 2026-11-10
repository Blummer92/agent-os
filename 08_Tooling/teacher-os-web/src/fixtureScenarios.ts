/**
 * Pure, deterministic variants of the immutable classroom fixture, used to show
 * (and test) every state a teacher can meet: current, stale, degraded,
 * disagreeing, moved/removed, permission-restricted, unrecognized, empty and a
 * lesson that changed under an unsent improvement intent. The fixture file on
 * disk is never edited; a variant is a copy that must still pass the same
 * decoder as the original.
 */
export const SCENARIOS = [
  { id: "current", label: "Current — everything agrees" },
  { id: "stale", label: "Stale — sources read long ago" },
  { id: "degraded", label: "Degraded — classroom materials unavailable" },
  { id: "disagreement", label: "Notion and Drive disagree — file removed" },
  { id: "moved", label: "Moved — file has a new Drive location" },
  { id: "permission", label: "Permission mismatch — Drive restricts a file" },
  { id: "unknown", label: "Unrecognized values from a source" },
  { id: "context-changed", label: "Lesson changes after the first read" },
  { id: "empty", label: "Empty — no lesson planned" },
] as const;
export type ScenarioId = (typeof SCENARIOS)[number]["id"];
export const isScenario = (value: unknown): value is ScenarioId => SCENARIOS.some(s => s.id === value);

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** `attempt` is the zero-based read count in this page session. */
export function applyScenario(source: unknown, scenario: ScenarioId, attempt = 0): unknown {
  const body = structuredClone(source) as Json;
  const art = (id: string): Json | undefined => body.artifacts?.items?.find((i: Json) => i.id === id);
  switch (scenario) {
    case "current": return body;
    case "stale":
      body.planning.age_minutes = 47; body.visual_selection.age_minutes = 52; body.guided_practice.age_minutes = 47; body.artifacts.age_minutes = 61;
      return body;
    case "degraded":
      body.artifacts = { status: "unavailable", reason_code: "reader-unreachable" };
      return body;
    case "disagreement": Object.assign(art("art-1")!, { drive_state: "removed" }); return body;
    case "moved": Object.assign(art("art-2")!, { drive_state: "moved", moved_to_label: "Drive > Digital Media 1 > Archive > Photography Foundations" }); return body;
    case "permission": Object.assign(art("art-2")!, { access_state: "restricted" }); return body;
    case "unknown":
      Object.assign(art("art-1")!, { notion_state: "quantum-ready", kind: "hologram" });
      Object.assign(body.visual_selection.items[2], { selection_state: "<b>approved!</b>", diagram: "hologram" });
      return body;
    case "context-changed":
      if (attempt >= 1) {
        body.lesson.revision += 1;
        body.lesson.daily_focus = "Compare three compositions of the same scene, including a tilted horizon.";
      }
      return body;
    case "empty": return { schema: body.schema, status: "empty", fixture: body.fixture };
  }
}
