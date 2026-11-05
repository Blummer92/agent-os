import { useEffect, useRef, useState, type ReactNode } from "react";
import { ageText, assessArtifact, concerns, freshness, type ArtifactItem, type Projection, type ProjectionState, type VisualItem } from "./fixtureContract";
import { SCENARIOS, isScenario, type ScenarioId } from "./fixtureScenarios";
import { loadFixture } from "./fixtureSource";

/** Synthetic classroom (fixture) for #2801. Read-only, no Notion/Drive/AI connection, nothing saved or sent. */

const REASON_TEXT: Record<string, string> = {
  "fixture-unreachable": "The sample classroom could not be reached (network interrupted).",
  "fixture-unavailable": "The sample classroom file is not available.",
  "malformed-response": "The sample classroom did not match its contract, so nothing from it is shown.",
};

function initialScenario(): ScenarioId {
  try { const value = new URLSearchParams(window.location.search).get("scenario"); return isScenario(value) ? value : "current"; } catch { return "current"; }
}

/** A status is always words first; colour only reinforces. */
function Chip({ tone, children }: { tone: "ok" | "warn" | "bad" | "neutral"; children: ReactNode }) {
  return <span className={`chip chip--${tone}`}>{children}</span>;
}

function Provenance({ source, ageMinutes }: { source: { display_name: string; verification_state: string; access: string }; ageMinutes: number }) {
  const fresh = freshness(ageMinutes) === "current";
  return (
    <dl className="provenance" aria-label={`Where ${source.display_name} came from`}>
      <div><dt>Source</dt><dd>{source.display_name}</dd></div>
      <div><dt>Verification</dt><dd>{source.verification_state}</dd></div>
      <div><dt>Access</dt><dd>{source.access}</dd></div>
      <div><dt>Read</dt><dd>{ageText(ageMinutes)} · {fresh ? <Chip tone="ok">Current</Chip> : <Chip tone="warn">Stale</Chip>}</dd></div>
    </dl>
  );
}

const SELECTION: Record<string, { tone: "ok" | "warn" | "neutral"; label: string; note: string }> = {
  approved: { tone: "ok", label: "Approved", note: "Teacher-approved for tomorrow." },
  "pending-review": { tone: "warn", label: "Pending review", note: "Not approved — not part of tomorrow's selection." },
  rejected: { tone: "neutral", label: "Not selected", note: "Not part of tomorrow's selection." },
};
const DIAGRAMS = new Set(["centered", "thirds", "tilted"]);

function VisualCard({ item }: { item: VisualItem }) {
  const known = SELECTION[item.selectionState];
  return (
    <li className="visual-card">
      <div className={`diagram diagram--${DIAGRAMS.has(item.diagram) ? item.diagram : "unknown"}`} role="img" aria-label={item.altText} />
      <h4>{item.title}</h4>
      <p>{known ? <Chip tone={known.tone}>{known.label}</Chip> : <Chip tone="warn">Unrecognized status</Chip>}</p>
      <p className="muted">{known ? known.note : <>The source reported “{item.selectionState}”, which Teacher OS does not recognize. It is shown as text and treated as not approved.</>}</p>
      <p className="muted">Reviewed by: {item.reviewedByRole} · {item.rationale}</p>
    </li>
  );
}

function ArtifactCard({ item }: { item: ArtifactItem }) {
  const a = assessArtifact(item);
  return (
    <li className={`artifact-card artifact-card--${a.status}`}>
      <div className="artifact-card__top"><h4>{item.title}</h4>{a.usable ? <Chip tone="ok">{a.headline}</Chip> : <Chip tone={a.status === "unknown" ? "warn" : "bad"}>{a.headline}</Chip>}</div>
      <p className="muted">Type: {item.kind} · Notion: {item.notionState} · Drive: {item.driveState}</p>
      <p>{a.detail}</p>
      {a.status !== "permission" && <p className="fine-print">{item.locationLabel}</p>}
    </li>
  );
}

export function FixtureApp() {
  const [scenario, setScenario] = useState<ScenarioId>(initialScenario);
  const [state, setState] = useState<ProjectionState>({ kind: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const attempts = useRef(0);
  const [draft, setDraft] = useState("");
  // An unsent improvement intent is bound to the exact lesson revision it was written against.
  const [intent, setIntent] = useState<{ text: string; ref: string; revision: number } | null>(null);
  const [revalidation, setRevalidation] = useState<{ kind: "unchanged" | "changed" | "failed" | "checking"; detail: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    // The read counter advances only when a read is actually applied, so an aborted
    // (superseded or StrictMode-doubled) effect can never consume a read.
    const attempt = attempts.current;
    loadFixture(scenario, attempt, controller.signal).then(next => { if (!controller.signal.aborted) { attempts.current = attempt + 1; setState(next); } }, () => {});
    return () => controller.abort();
  }, [scenario, reloadKey]);

  function chooseScenario(next: ScenarioId) {
    attempts.current = 0;
    setIntent(null); setRevalidation(null);
    try { const url = new URL(window.location.href); url.searchParams.set("scenario", next); window.history.replaceState(null, "", url); } catch { /* the URL is a convenience only */ }
    setScenario(next);
  }
  const current: Projection | null = state.kind === "ready" ? state.value : null;

  async function revalidate() {
    if (!intent) return;
    setRevalidation({ kind: "checking", detail: "Checking the lesson again before this intent could be used…" });
    const attempt = attempts.current;
    const next = await loadFixture(scenario, attempt, new AbortController().signal);
    if (next.kind !== "ready") { setRevalidation({ kind: "failed", detail: "The lesson could not be re-read, so this intent is not trusted and was not sent." }); return; }
    attempts.current = attempt + 1;
    setState(next);
    if (next.value.lesson.ref !== intent.ref || next.value.lesson.revision !== intent.revision) {
      setRevalidation({ kind: "changed", detail: `The lesson changed since you wrote this (revision ${intent.revision} → ${next.value.lesson.revision}). The intent was withdrawn and nothing was sent. Review the updated lesson, then prepare it again.` });
      setDraft(intent.text);
      setIntent(null);
    } else setRevalidation({ kind: "unchanged", detail: `The lesson is unchanged (revision ${next.value.lesson.revision}). The intent is still only a preview; nothing was sent.` });
  }

  const issues = current ? concerns(current) : [];
  return (
    <div className="app-shell fixture-shell">
      <header className="app-header">
        <div className="app-title"><strong>Teacher OS</strong><span>Sample classroom</span></div>
        <p className="connection connection--wait" role="status" aria-label="Data source: synthetic fixture"><span className="dot" aria-hidden="true" />Fixture · synthetic</p>
        <a className="header-link" href="/">← Live Teacher OS</a>
      </header>
      <div className="fixture-banner" role="note"><strong>FIXTURE</strong> · Synthetic sample classroom. It is <em>not</em> Notion or Drive evidence. Nothing here is live, saved, sent or shared.</div>
      <main className="main-content" aria-busy={state.kind === "loading"}>
        <div className="fixture-column">
        {state.kind === "loading" && <p role="status" className="notice notice--wait">Loading the sample classroom…</p>}
        {state.kind === "error" && <div className="state-card"><h2>The sample classroom couldn't be loaded</h2>
          <p role="alert" className="notice notice--bad">{REASON_TEXT[state.reason] ?? "The sample classroom could not be read."} Nothing is shown in its place.</p>
          <button type="button" className="secondary" onClick={() => setReloadKey(k => k + 1)}>Try again</button></div>}
        {state.kind === "empty" && <div className="state-card"><h2>No lesson is planned for tomorrow</h2>
          <p role="status" className="notice">The sample has no lesson to show. Nothing is shown in its place.</p>
          <button type="button" className="secondary" onClick={() => setReloadKey(k => k + 1)}>Try again</button></div>}
        {current && (<>
          <p className="eyebrow">{current.course} · Grade {current.grade} · {current.lesson.dayLabel}</p>
          <h1 id="unit-title">{current.unit}</h1>

          <section className={`summary ${issues.length ? "summary--attention" : "summary--clear"}`} aria-labelledby="summary-title" role="status">
            <h2 id="summary-title">{issues.length ? `Needs your attention (${issues.length})` : "Context is current"}</h2>
            {issues.length
              ? <ul>{issues.map(i => <li key={i.id}>{i.text}</li>)}</ul>
              : <p>Every source was read recently and Notion and Drive agree. This describes the sources only — it does not make the lesson ready or publish anything.</p>}
          </section>

          <section className="panel" aria-labelledby="plan-title">
            <h2 id="plan-title">Lesson plan</h2>
            <p><Chip tone={current.lesson.readiness === "teacher-reviewed" ? "ok" : "warn"}>{current.lesson.readiness === "teacher-reviewed" ? "Teacher-reviewed" : `Readiness: ${current.lesson.readiness}`}</Chip> <span className="muted">revision {current.lesson.revision}</span></p>
            <div className="lesson-fields">
              <div className="field"><h3>Learning target</h3><p>{current.lesson.target}</p></div>
              <div className="field"><h3>Today's focus</h3><p>{current.lesson.focus}</p></div>
              <div className="field"><h3>Key vocabulary</h3><p>{current.lesson.vocabulary.join(" · ") || "None recorded"}</p></div>
            </div>
            <Provenance source={current.planning.source} ageMinutes={current.planning.ageMinutes} />
          </section>

          <section className="panel" aria-labelledby="visual-title">
            <h2 id="visual-title">Approved visual selections</h2>
            {current.visual.data.length === 0 ? <p className="muted">No visual selections are recorded.</p>
              : <ul className="visual-grid" aria-label="Visual selections">{current.visual.data.map(v => <VisualCard key={v.id} item={v} />)}</ul>}
            <Provenance source={current.visual.source} ageMinutes={current.visual.ageMinutes} />
          </section>

          <section className="panel" aria-labelledby="practice-title">
            <h2 id="practice-title">Guided practice</h2>
            <ol className="practice" aria-label="Guided practice steps">{current.practice.data.map(s => (
              <li key={s.id}><p><strong>{s.minutes} min</strong> · {s.prompt}</p><p className="muted">Check for understanding: {s.check}</p></li>))}</ol>
            <p className="muted">{current.practice.data.reduce((n, s) => n + s.minutes, 0)} minutes in total.</p>
            <Provenance source={current.practice.source} ageMinutes={current.practice.ageMinutes} />
          </section>

          <section className="panel" aria-labelledby="materials-title">
            <h2 id="materials-title">Classroom materials</h2>
            {current.artifacts.status === "unavailable"
              ? <p role="alert" className="notice notice--warn">Classroom materials are unavailable ({current.artifacts.reason}). Nothing is claimed about Drive, and no material is shown in its place.</p>
              : (<>
                <ul className="artifact-list" aria-label="Classroom materials">{current.artifacts.items.map(a => <ArtifactCard key={a.id} item={a} />)}</ul>
                <Provenance source={current.artifacts.source} ageMinutes={current.artifacts.ageMinutes} />
              </>)}
            <p className="fine-print">A file existing in Drive is not instructional readiness and not permission to publish.</p>
          </section>

          <section className="panel" aria-labelledby="improve-title">
            <h2 id="improve-title">Improve tomorrow's lesson</h2>
            <p className="muted">Describe the change you want. This prepares a preview only: the live teacher/material route is not admitted yet (#1892), so nothing is dispatched and no plan, file or readiness is changed.</p>
            <form onSubmit={event => { event.preventDefault(); const text = draft.trim(); if (!text) return; setIntent({ text, ref: current.lesson.ref, revision: current.lesson.revision }); setRevalidation(null); setDraft(""); }}>
              <label htmlFor="intent-input">What should change?</label>
              <textarea id="intent-input" rows={3} value={draft} onChange={e => setDraft(e.target.value)} placeholder="e.g. add a quick exit question about balance" />
              <div className="card-actions"><button type="submit" disabled={!draft.trim()}>Prepare intent preview</button><span className="unsaved-badge">Unsaved · this session only</span></div>
            </form>
            {intent && (
              <div className="intent-card" aria-labelledby="intent-title">
                <h3 id="intent-title">Intent preview — not sent</h3>
                <p className="intent-text">{intent.text}</p>
                <p className="muted">Bound to {current.unit}, {current.lesson.dayLabel}, lesson revision {intent.revision}. It would be routed through an existing teacher/material capability only after an owner admits that route. Being on this page grants no write, readiness or publication authority.</p>
                <div className="card-actions"><button type="button" className="secondary" onClick={revalidate}>Check lesson is unchanged</button><button type="button" className="text-button" onClick={() => { setIntent(null); setRevalidation(null); }}>Discard preview</button></div>
              </div>)}
            {revalidation && <p role={revalidation.kind === "changed" || revalidation.kind === "failed" ? "alert" : "status"} className={`notice ${revalidation.kind === "unchanged" ? "" : revalidation.kind === "checking" ? "notice--wait" : "notice--warn"}`}>{revalidation.detail}</p>}
          </section>
        </>)}

        <details className="review-controls">
          <summary>Fixture review controls</summary>
          <p className="muted">These switch the sample between the states a teacher can meet. They exist only on this fixture page.</p>
          <label htmlFor="scenario">Sample state</label>
          <select id="scenario" value={scenario} onChange={e => { if (isScenario(e.target.value)) chooseScenario(e.target.value); }}>
            {SCENARIOS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <button type="button" className="secondary" onClick={() => setReloadKey(k => k + 1)}>Read the sample again</button>
        </details>
        </div>
      </main>
      <footer>Teacher OS · #2801 · Synthetic fixture · Read-only · No production actions</footer>
    </div>
  );
}
