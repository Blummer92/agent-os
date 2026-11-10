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
    <div role="group" aria-label={`Where ${source.display_name} came from`}><dl className="provenance">
      <div><dt>Source</dt><dd>{source.display_name}</dd></div>
      <div><dt>Verification</dt><dd>{source.verification_state}</dd></div>
      <div><dt>Access</dt><dd>{source.access}</dd></div>
      <div><dt>Read</dt><dd>{ageText(ageMinutes)} · {fresh ? <Chip tone="ok">Current</Chip> : <Chip tone="warn">Stale</Chip>}</dd></div>
    </dl></div>
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
      <h3>{item.title}</h3>
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
      <div className="artifact-card__top"><h3>{item.title}</h3>{a.usable ? <Chip tone="ok">{a.headline}</Chip> : <Chip tone={a.status === "unknown" ? "warn" : "bad"}>{a.headline}</Chip>}</div>
      <p className="muted">{a.status === "permission" ? `Type: ${item.kind}` : `Type: ${item.kind} · Notion: ${item.notionState} · Drive: ${item.driveState}`}</p>
      <p>{a.detail}</p>
      {a.status !== "permission" && <p className="fine-print">{item.locationLabel}</p>}
    </li>
  );
}

type Intent = { id: number; text: string; ref: string; revision: number };
type Revalidation = { kind: "unchanged" | "changed" | "failed" | "checking"; detail: string };
type FocusTarget = "intent" | "draft" | "title";

export function FixtureApp() {
  const [scenario, setScenario] = useState<ScenarioId>(initialScenario);
  const [state, setState] = useState<ProjectionState>({ kind: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [draft, setDraft] = useState("");
  // An unsent improvement intent is bound to the exact lesson revision it was written against.
  const [intent, setIntentState] = useState<Intent | null>(null);
  const [revalidation, setRevalidation] = useState<Revalidation | null>(null);
  // Exactly one read owns the page at a time: starting another aborts the previous one, so a
  // superseded read can never apply (or write a message) after the teacher moved on.
  const controllerRef = useRef<AbortController | null>(null);
  const attempts = useRef(0); // advances only when a read is actually applied (StrictMode- and abort-safe)
  const intentRef = useRef<Intent | null>(null);
  const intentSeq = useRef(0);
  const pendingFocus = useRef<FocusTarget | null>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);
  const intentHeadingRef = useRef<HTMLHeadingElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);

  const setIntent = (next: Intent | null) => { intentRef.current = next; setIntentState(next); };
  const startRead = () => { controllerRef.current?.abort(); const controller = new AbortController(); controllerRef.current = controller; return controller.signal; };
  /** Return the teacher's words to the editor without overwriting what they have typed since. */
  const restoreWords = (text: string) => setDraft(d => (d.trim() ? `${d}\n\n${text}` : text));
  /** Every applied read passes through here, so an intent can never outlive the lesson it was written against. */
  function applyRead(next: ProjectionState) {
    setState(next);
    const held = intentRef.current;
    if (next.kind !== "ready" || !held) return;
    if (next.value.lesson.ref !== held.ref || next.value.lesson.revision !== held.revision) {
      restoreWords(held.text); setIntent(null); pendingFocus.current = "draft";
      setRevalidation({ kind: "changed", detail: `The lesson changed since you wrote this (revision ${held.revision} → ${next.value.lesson.revision}). The intent was withdrawn and nothing was sent. Your words are back in the box; review the updated lesson, then prepare it again.` });
    }
  }

  useEffect(() => {
    const signal = startRead();
    setState({ kind: "loading" });
    setRevalidation(r => (r?.kind === "checking" ? null : r)); // a check this read superseded must not stay "checking"
    const attempt = attempts.current;
    loadFixture(scenario, attempt, signal).then(next => { if (!signal.aborted) { attempts.current = attempt + 1; applyRead(next); } }, () => {});
    return () => controllerRef.current?.abort();
  }, [scenario, reloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Focus follows the teacher's task: it is never left on a control that just disappeared or became disabled.
  useEffect(() => {
    const target = pendingFocus.current;
    if (!target) return;
    const el = target === "intent" ? intentHeadingRef.current : target === "draft" ? draftRef.current : titleRef.current;
    if (el) { el.focus(); pendingFocus.current = null; }
  });

  function chooseScenario(next: ScenarioId) {
    attempts.current = 0;
    const held = intentRef.current;
    if (held) restoreWords(held.text);
    setIntent(null); setRevalidation(null);
    try { const url = new URL(window.location.href); url.searchParams.set("scenario", next); window.history.replaceState(null, "", url); } catch { /* the URL is a convenience only */ }
    setScenario(next);
  }
  function tryAgain() { pendingFocus.current = "title"; setReloadKey(k => k + 1); }
  const current: Projection | null = state.kind === "ready" ? state.value : null;

  async function revalidate() {
    const checked = intentRef.current;
    if (!checked) return;
    setRevalidation({ kind: "checking", detail: "Checking the lesson again before this intent could be used…" });
    const signal = startRead();
    const attempt = attempts.current;
    let next: ProjectionState;
    try { next = await loadFixture(scenario, attempt, signal); } catch { return; } // aborted: a newer read owns the page
    if (signal.aborted) return;
    attempts.current = attempt + 1;
    const stillChecked = () => intentRef.current?.id === checked.id; // the intent may have been replaced or discarded meanwhile
    if (next.kind !== "ready") { if (stillChecked()) setRevalidation({ kind: "failed", detail: "The lesson could not be re-read, so this intent is not trusted and was not sent." }); return; }
    applyRead(next);
    if (stillChecked()) setRevalidation({ kind: "unchanged", detail: `The lesson is unchanged (revision ${next.value.lesson.revision}). The intent is still only a preview; nothing was sent.` });
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
          <button type="button" className="secondary" onClick={tryAgain}>Try again</button></div>}
        {state.kind === "empty" && <div className="state-card"><h2>No lesson is planned for tomorrow</h2>
          <p role="status" className="notice">The sample has no lesson to show. Nothing is shown in its place. Choose another sample state under Fixture review controls.</p></div>}
        {current && (<>
          <p className="eyebrow">{current.course} · Grade {current.grade} · {current.lesson.dayLabel}</p>
          <h1 id="unit-title" ref={titleRef} tabIndex={-1}>{current.unit}</h1>

          <section className={`summary ${issues.length ? "summary--attention" : "summary--clear"}`} aria-labelledby="summary-title">
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
            <h2 id="visual-title">Visual selections</h2>
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
            <form onSubmit={event => { event.preventDefault(); const text = draft.trim(); if (!text) return; setIntent({ id: ++intentSeq.current, text, ref: current.lesson.ref, revision: current.lesson.revision }); setRevalidation(null); setDraft(""); pendingFocus.current = "intent"; }}>
              <label htmlFor="intent-input">What should change?</label>
              <textarea id="intent-input" ref={draftRef} rows={3} value={draft} onChange={e => setDraft(e.target.value)} placeholder="e.g. add a quick exit question about balance" />
              <div className="card-actions"><button type="submit" disabled={!draft.trim()}>Prepare intent preview</button><span className="unsaved-badge">Unsaved · this session only</span></div>
            </form>
            {intent && (
              <div className="intent-card" role="group" aria-labelledby="intent-title">
                <h3 id="intent-title" ref={intentHeadingRef} tabIndex={-1}>Intent preview — not sent</h3>
                <p className="intent-text">{intent.text}</p>
                <p className="muted">Bound to {current.unit}, {current.lesson.dayLabel}, lesson revision {intent.revision}. It would be routed through an existing teacher/material capability only after an owner admits that route. Being on this page grants no write, readiness or publication authority.</p>
                <div className="card-actions"><button type="button" className="secondary" disabled={revalidation?.kind === "checking"} onClick={revalidate}>Check lesson is unchanged</button><button type="button" className="text-button" onClick={() => { setIntent(null); setRevalidation(null); pendingFocus.current = "draft"; }}>Discard preview</button></div>
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
