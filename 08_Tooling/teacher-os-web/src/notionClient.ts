/**
 * Browser client for the Teacher OS API. It holds no credential and no
 * curriculum content: the session secret is added by the local Vite proxy,
 * never by this code, and every response is decoded by ./apiContract before
 * the UI sees it.
 */
import { decodeLessons, decodeUnits, type LoadState } from "./apiContract";

export type { Lesson, Loaded, LoadState, Source, Unit } from "./apiContract";
export { isStale, readAge, STALE_AFTER_MS } from "./apiContract";

async function load<T>(url: string, decode: (status: number, body: unknown) => LoadState<T>, signal: AbortSignal): Promise<LoadState<T>> {
  let response: Response;
  try {
    response = await fetch(url, { signal, headers: { accept: "application/json" }, credentials: "same-origin", cache: "no-store", redirect: "error" });
  } catch (error) {
    if (signal.aborted) throw error;
    return { kind: "unavailable", reason: "reader-unreachable" };
  }
  if (!(response.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) {
    return { kind: "unavailable", reason: "reader-unavailable" };
  }
  let body: unknown;
  try { body = await response.json(); } catch { return { kind: "unavailable", reason: "reader-unavailable" }; }
  return decode(response.status, body);
}

export const fetchUnits = (signal: AbortSignal) => load("/api/teacher-os/units", decodeUnits, signal);
export const fetchLessons = (unitId: string, signal: AbortSignal) =>
  load(`/api/teacher-os/units/${encodeURIComponent(unitId)}/lessons`, (status, body) => decodeLessons(status, body, unitId), signal);
