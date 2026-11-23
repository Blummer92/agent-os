/**
 * Loads the immutable classroom fixture file, applies the selected review
 * scenario and decodes the result. Reads only a static same-origin JSON file:
 * no credential, no Notion, no Drive, no write.
 */
import { decodeProjection, type ProjectionState } from "./fixtureContract.ts";
import { applyScenario, type ScenarioId } from "./fixtureScenarios.ts";

export const FIXTURE_URL = "/fixture/classroom-fixture.v1.json";

export async function loadFixture(scenario: ScenarioId, attempt: number, signal: AbortSignal): Promise<ProjectionState> {
  let response: Response;
  try {
    response = await fetch(FIXTURE_URL, { signal, headers: { accept: "application/json" }, credentials: "same-origin", cache: "no-store", redirect: "error" });
  } catch (error) {
    if (signal.aborted) throw error;
    return { kind: "error", reason: "fixture-unreachable" };
  }
  if (!response.ok) return { kind: "error", reason: "fixture-unavailable" };
  let body: unknown;
  try { body = await response.json(); } catch { return { kind: "error", reason: "malformed-response" }; }
  try { return decodeProjection(applyScenario(body, scenario, attempt)); } catch { return { kind: "error", reason: "malformed-response" }; }
}
