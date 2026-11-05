import { useEffect, useRef, useState, type ReactNode } from "react";
import { fetchLessons, fetchUnits, isStale, readAge, type Lesson, type LoadState, type Loaded, type Unit } from "./notionClient";

type Screen = "chat" | "preview" | "edit";
type MessageMap = Record<string, readonly string[]>;
type Failure = Extract<LoadState<unknown>, { reason: string }>;

const NOTICE: Record<string, string> = {
  "admission-required": "live Notion reads are not admitted for Teacher OS yet.",
  "not-configured": "the Notion connection is not configured for this server.",
  "source-unverified": "the curriculum source is not verified.",
  "unit-not-approved": "this unit is not in the approved curriculum source.",
  "malformed-response": "the reader sent a response that does not match the Teacher OS contract.",
  unauthenticated: "this browser session is not authorized to read curriculum.",
  "host-not-allowed": "the request did not come from this computer's Teacher OS app.",
  "origin-not-allowed": "the request came from another site.",
};
const READER_DEFAULT = "the curriculum reader could not be reached.";

/** What a teacher should do next for each failure; never implies content exists. */
const DEV_APP = <code>npm run dev:app</code>;
function guidance(state: Failure | { kind: "empty" }): { title: string; body: ReactNode } {
  if (state.kind === "empty") return { title: "No approved units yet", body: "The verified unit registry has no Active units cleared for classroom use. Approved units appear here automatically — no code change is needed." };
  if (state.kind === "unauthorized") return { title: "This session isn't authorized", body: <>Restart Teacher OS with {DEV_APP} so the local session is set up again. Nothing is shown until the session is authorized.</> };
  switch (state.reason) {
    case "admission-required": return { title: "Live curriculum is not connected yet", body: "Teacher OS shows only units and lessons that an owner-approved Notion read admission allows. No Teacher OS admission has been approved yet, so no curriculum is shown and no sample lessons are substituted." };
    case "reader-unreachable": case "reader-unavailable": return { title: "The curriculum reader isn't running", body: <>Start Teacher OS with {DEV_APP} in <code>08_Tooling/teacher-os-web</code>. It runs only on this computer (127.0.0.1).</> };
    case "rate-limited": return { title: "Too many reads in a short time", body: "Wait a minute, then try again." };
    case "malformed-response": return { title: "The reader sent an unexpected response", body: "The response did not match the Teacher OS contract, so nothing from it is shown. Try again; if it persists, check the local reader." };
    default: return { title: "Curriculum couldn't be read", body: "Try again in a moment. Nothing is shown in place of the missing curriculum." };
  }
}

/** Loads one keyed remote read. Superseded requests are aborted and a result is only returned for the key that requested it. */
function useRemote<T>(key: string | undefined, load: (key: string, signal: AbortSignal) => Promise<LoadState<T>>, reloadKey: number): LoadState<T> {
  const [done, setDone] = useState<{ key: string; reloadKey: number; state: LoadState<T> } | null>(null);
  useEffect(() => {
    if (key === undefined) return;
    const controller = new AbortController();
    load(key, controller.signal).then(state => { if (!controller.signal.aborted) setDone({ key, reloadKey, state }); }, () => {});
    return () => controller.abort();
  }, [key, reloadKey]); // eslint-disable-line react-hooks/exhaustive-deps
  if (key === undefined) return { kind: "idle" };
  return done && done.key === key && done.reloadKey === reloadKey ? done.state : { kind: "loading" };
}

function connection(units: LoadState<unknown>): { tone: "ok" | "wait" | "warn" | "bad"; text: string } {
  switch (units.kind) {
    case "ready": case "empty": return { tone: "ok", text: "Connected · read-only" };
    case "idle": case "loading": return { tone: "wait", text: "Checking curriculum…" };
    case "unauthorized": return { tone: "bad", text: "Session not authorized" };
    case "unavailable": return units.reason === "admission-required" ? { tone: "warn", text: "Live reads not admitted" } : { tone: "warn", text: "Reader unavailable" };
    default: return { tone: "bad", text: "Reader error" };
  }
}

function Field({ label, value }: { label: string; value: string | null }) {
  return <div className="field"><h3>{label}</h3><p className={value ? undefined : "not-recorded"}>{value ?? "Not recorded in Notion"}</p></div>;
}

function Provenance({ evidence, now }: { evidence: Loaded<unknown>; now: number }) {
  return (
    <dl className="provenance" aria-label="Where this came from">
      <div><dt>Source</dt><dd>{evidence.source.display_name}</dd></div>
      <div><dt>Verification</dt><dd>{evidence.source.verification_state}</dd></div>
      <div><dt>Access</dt><dd>{evidence.source.access}</dd></div>
      <div><dt>Read</dt><dd><time dateTime={evidence.generatedAt} title={evidence.generatedAt}>{readAge(evidence.generatedAt, now)}</time></dd></div>
    </dl>
  );
}

function Materials({ lesson, linkLabel }: { lesson: Lesson; linkLabel: string }) {
  return (
    <div className="materials">
      <h3>Approved materials</h3>
      <p>No approved Google Drive materials are linked in this lesson record. Slides, Docs and worksheets stay in approved Drive folders and are not generated here.</p>
      {lesson.record_url && <p><a href={lesson.record_url} rel="noreferrer noopener" target="_blank">{linkLabel}</a></p>}
    </div>
  );
}

export function TeacherApp() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [assignmentOpen, setAssignmentOpen] = useState(false);
  const [unitId, setUnitId] = useState("");
  const [lessonIndex, setLessonIndex] = useState(0);
  const [screen, setScreen] = useState<Screen>("chat");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  // The read generation the selection came from. A selection belongs to one
  // read only: after a refresh, a regrown list must not resurrect a preview
  // or edit the user left when the list shrank. No effect is needed — the
  // derivation below compares this stored generation with the current one.
  const [selectedReloadKey, setSelectedReloadKey] = useState<number | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<MessageMap>({});
  const [reloadKey, setReloadKey] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const units = useRemote<readonly Unit[]>("units", (_key, signal) => fetchUnits(signal), reloadKey);
  const unitList: readonly Unit[] = units.kind === "ready" ? units.value.data : [];
  const unit = unitList.find(u => u.unit_id === unitId) ?? unitList[0];
  const lessons = useRemote<readonly Lesson[]>(unit?.unit_id, fetchLessons, reloadKey);
  const lessonList: readonly Lesson[] = lessons.kind === "ready" ? lessons.value.data : [];
  // Derived, never stored back: clamp the index to the list on screen, so a
  // refresh that shrinks the list can never render "3 of 1". No effect or
  // extra state sync is needed; the stored index is only a preference.
  const lessonIndexClamped = lessonList.length === 0 ? 0 : Math.min(lessonIndex, lessonList.length - 1);
  const current = lessonList[lessonIndexClamped];
  const evidence = lessons.kind === "ready" ? lessons.value : units.kind === "ready" ? units.value : null;
  const stale = evidence ? isStale(evidence.generatedAt, clock) : false;
  // Derived from the current read, so a refresh can never leave a superseded lesson on screen.
  // An out-of-range selection, or one from an older read generation, is no
  // selection, never a stale lesson and never a resurrected preview.
  const picked = selectedIndex === null || selectedReloadKey !== reloadKey || selectedIndex >= lessonList.length ? undefined : lessonList[selectedIndex];
  // Drafts/messages are keyed by lesson identity, never by position alone.
  // A lesson's day label is a stable key only when it is present and unique
  // in the current list; otherwise the key is bound to this read generation
  // and can never resurface after a refresh/reorder for a different lesson.
  // Selection itself still belongs to one read (selectedReloadKey above), so
  // a refresh clears the preview/edit view; a stable draft is only shown
  // again when the teacher re-selects that same lesson.
  const dayLabelCounts = new Map<string, number>();
  for (const lesson of lessonList) if (lesson.day_lesson_number) dayLabelCounts.set(lesson.day_lesson_number, (dayLabelCounts.get(lesson.day_lesson_number) ?? 0) + 1);
  const lessonDraftKey = (lesson: Lesson, index: number, generation: number) =>
    lesson.day_lesson_number && dayLabelCounts.get(lesson.day_lesson_number) === 1
      ? `${unit?.unit_id}:${lesson.day_lesson_number}`
      : `${unit?.unit_id}:__ephemeral__:${generation}:${index}`;
  const selected = picked ? { key: lessonDraftKey(picked, selectedIndex!, selectedReloadKey!), lesson: picked, label: lessonLabel(picked, selectedIndex!) } : null;
  const view: Screen = selected ? screen : "chat";
  useEffect(() => { const t = setInterval(() => setClock(Date.now()), 30_000); return () => clearInterval(t); }, []);
  const conversationKey = view === "edit" && selected ? selected.key : "lesson";
  const draft = drafts[conversationKey] ?? "";
  const history = messages[conversationKey] ?? [];
  const status = connection(units);

  function lessonLabel(lesson: Lesson, index: number) { return lesson.day_lesson_number ?? `Lesson ${index + 1}`; }
  function changeUnit(next: string) { setUnitId(next); setLessonIndex(0); setScreen("chat"); setSelectedIndex(null); setSelectedReloadKey(null); }
  function closeAssignments() { setAssignmentOpen(false); triggerRef.current?.focus(); }
  function closeMenu() { setMenuOpen(false); menuButtonRef.current?.focus(); }
  function refresh() { setReloadKey(k => k + 1); }
  function enter(next: "preview" | "edit", index: number) {
    setSelectedIndex(index);
    setSelectedReloadKey(reloadKey);
    setScreen(next); setAssignmentOpen(false); setMenuOpen(false);
  }
  function backToLesson() { setScreen("chat"); setSelectedIndex(null); setSelectedReloadKey(null); }
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    setMessages(prev => ({ ...prev, [conversationKey]: [...(prev[conversationKey] ?? []), trimmed] }));
    setDrafts(prev => ({ ...prev, [conversationKey]: "" }));
  }
  const sourceNotice = (state: LoadState<unknown>, what: string) => {
    if (state.kind === "loading") return <p role="status" className="notice notice--wait">Loading {what} from Notion…</p>;
    if (state.kind === "empty") return <p role="status" className="notice">Notion returned no {what}. Nothing is shown in its place.</p>;
    if (state.kind === "unavailable") return <p role="alert" className="notice notice--warn">Notion is unavailable: {NOTICE[state.reason] ?? READER_DEFAULT} No substitute {what} are shown.</p>;
    if (state.kind === "unauthorized") return <p role="alert" className="notice notice--bad">Not authorized: {NOTICE[state.reason] ?? NOTICE.unauthenticated} No {what} are shown.</p>;
    if (state.kind === "error") return <p role="alert" className="notice notice--bad">Could not read {what} from Notion ({state.reason}). No substitute {what} are shown.</p>;
    return null;
  };
  const provenanceLine = (e: Loaded<unknown>) => `${e.source.display_name} · ${e.source.verification_state} · ${e.source.access} · read ${e.generatedAt}`;
  const stateCard = (state: LoadState<unknown>, what: string): ReactNode => {
    if (state.kind === "ready" || state.kind === "idle") return null;
    const help = state.kind === "loading" ? null : guidance(state);
    return (
      <div className="state-card">
        {help && <h2>{help.title}</h2>}
        {sourceNotice(state, what)}
        {help && <p className="muted guidance">{help.body}</p>}
        {state.kind !== "loading" && <button type="button" className="secondary" onClick={refresh}>Try again</button>}
      </div>
    );
  };

  return (
    <div className="app-shell" onKeyDown={event => { if (event.key === "Escape" && menuOpen) closeMenu(); }}>
      <header className="app-header">
        <button ref={menuButtonRef} className="icon-button" type="button" aria-label="Toggle recent conversations" aria-expanded={menuOpen} onClick={() => setMenuOpen(v => !v)}>☰</button>
        <div className="app-title"><strong>Teacher OS</strong><span>{view === "chat" ? "Lesson overview" : view === "preview" ? "Complete lesson" : "Local lesson notes"}</span></div>
        <p className={`connection connection--${status.tone}`} role="status" aria-label={`Curriculum connection: ${status.text}`}><span className="dot" aria-hidden="true" />{status.text}</p>
        <button ref={triggerRef} className="assignment-button" type="button" aria-controls="assignment-panel" aria-expanded={assignmentOpen} onClick={() => { setAssignmentOpen(v => !v); setMenuOpen(false); }}>View Assignment <span aria-hidden="true">{assignmentOpen ? "⌃" : "⌄"}</span></button>
      </header>
      <div className="demo-banner" role="note">{units.kind === "unavailable" && units.reason === "admission-required"
        ? "Read-only · live Notion reads are not admitted yet, so no lessons are shown · Slides, Docs and worksheets stay in approved Google Drive folders"
        : "Read-only · only owner-approved Notion evidence is shown, when live reads are admitted · Slides, Docs and worksheets stay in approved Google Drive folders"}</div>
      {stale && evidence && <p role="alert" className="notice notice--warn banner-notice">Stale evidence: last read {evidence.generatedAt}. <button type="button" className="text-button" onClick={refresh}>Refresh from Notion</button></p>}
      {menuOpen && <nav aria-label="Recent conversations" className="recent-menu">
        <h2>Recent conversations</h2>
        <button type="button" className="secondary" onClick={() => { backToLesson(); setMenuOpen(false); }}>{unit ? `${unit.title} — lesson overview` : "Lesson overview"}</button>
        {Object.keys(messages).filter(key => key !== "lesson").map(key => <p key={key}>{key.startsWith(`${unit?.unit_id}:`) ? "Lesson notes" : "Notes for another unit"} — local only</p>)}
        <p>Recent notes exist only during this session. No external history was loaded.</p>
      </nav>}
      {assignmentOpen && <section id="assignment-panel" aria-label="View Assignment" className="assignment-panel" onKeyDown={event => { if (event.key === "Escape") closeAssignments(); }}>
        <div className="panel-heading"><h2>View Assignment</h2><button className="text-button" type="button" onClick={closeAssignments}>Close</button></div>
        <div className="filters">
          <div><label htmlFor="unit">Unit</label><select id="unit" value={unit?.unit_id ?? ""} disabled={unitList.length === 0} onChange={event => changeUnit(event.target.value)}>
            {unitList.length === 0 && <option value="">No units available</option>}
            {unitList.map(u => <option key={u.unit_id} value={u.unit_id}>{u.title}</option>)}
          </select></div>
          <button className="text-button" type="button" onClick={refresh}>Refresh from Notion</button>
        </div>
        {sourceNotice(units, "units")}
        {unit && sourceNotice(lessons, "lessons")}
        {current && <div className="carousel" aria-label="Lesson carousel">
          <article className="material-card">
            <div className="card-meta"><span>{lessonLabel(current, lessonIndexClamped)}</span><span>{unit?.title}</span></div>
            <h3>{current.daily_focus ?? "No daily focus recorded in Notion"}</h3>
            <p>{current.daily_learning_target ?? "No learning target recorded in Notion"}</p>
            <div className="card-actions"><button type="button" onClick={() => enter("preview", lessonIndexClamped)}>View full lesson</button><button type="button" className="secondary" onClick={() => enter("edit", lessonIndexClamped)}>Edit in focused chat</button></div>
          </article>
          <div className="carousel-controls"><button type="button" className="secondary" disabled={lessonIndexClamped === 0} onClick={() => setLessonIndex(lessonIndexClamped - 1)}>← Previous</button><span aria-live="polite">{lessonList.length === 0 ? 0 : lessonIndexClamped + 1} of {lessonList.length}</span><button type="button" className="secondary" disabled={lessonIndexClamped >= lessonList.length - 1} onClick={() => setLessonIndex(lessonIndexClamped + 1)}>Next →</button></div>
        </div>}
        {lessons.kind === "ready" && <p className="fine-print">{provenanceLine(lessons.value)}</p>}
      </section>}
      <main className="main-content">
        {view === "chat" && <section aria-labelledby="chat-title" className="workspace">
          <p className="eyebrow">Verified curriculum · read-only</p>
          <h1 id="chat-title">{unit?.title ?? "Teacher OS"}</h1>
          {units.kind !== "ready" ? stateCard(units, "units") : unit && lessons.kind !== "ready" ? stateCard(lessons, "lessons") : null}
          {current && <section className="lesson-card" aria-labelledby="overview-title">
            <div className="lesson-card__top">
              <div><h2 id="overview-title">Lesson overview</h2><p className="day-badge">{lessonLabel(current, lessonIndexClamped)}</p></div>
              <div className="stepper" role="group" aria-label="Choose lesson">
                <button type="button" className="secondary" aria-label="Previous lesson" disabled={lessonIndexClamped === 0} onClick={() => setLessonIndex(lessonIndexClamped - 1)}>‹</button>
                <span className="stepper__count">Lesson {lessonIndexClamped + 1} of {lessonList.length}</span>
                <button type="button" className="secondary" aria-label="Next lesson" disabled={lessonIndexClamped >= lessonList.length - 1} onClick={() => setLessonIndex(lessonIndexClamped + 1)}>›</button>
              </div>
            </div>
            <div className="lesson-fields">
              <Field label="Learning target" value={current.daily_learning_target} />
              <Field label="Today's focus" value={current.daily_focus} />
              <Field label="Key vocabulary" value={current.key_vocabulary} />
            </div>
            <div className="card-actions"><button type="button" onClick={() => enter("preview", lessonIndexClamped)}>Open complete lesson</button><button type="button" className="secondary" onClick={() => enter("edit", lessonIndexClamped)}>Local notes for this lesson</button></div>
            {lessons.kind === "ready" && <Provenance evidence={lessons.value} now={clock} />}
            <Materials lesson={current} linkLabel="Open lesson record in Notion" />
          </section>}
        </section>}
        {view === "preview" && selected && <section aria-labelledby="preview-title" className="full-preview"><button type="button" className="back-button" onClick={backToLesson}>← Back to lesson</button>
          <p className="eyebrow">{unit?.title} · read-only Notion lesson</p><h1 id="preview-title">{selected.label}</h1>
          <dl className="sample-page">
            <dt>Daily Learning Target</dt><dd>{selected.lesson.daily_learning_target ?? "Not recorded in Notion"}</dd>
            <dt>Daily Focus</dt><dd>{selected.lesson.daily_focus ?? "Not recorded in Notion"}</dd>
            <dt>Key Vocabulary</dt><dd>{selected.lesson.key_vocabulary ?? "Not recorded in Notion"}</dd>
            <dt>Source Evidence</dt><dd>{selected.lesson.source_evidence ?? "Not recorded in Notion"}</dd>
          </dl>
          <Materials lesson={selected.lesson} linkLabel="Open the Notion record" />
          {lessons.kind === "ready" && <p className="fine-print">{provenanceLine(lessons.value)}</p>}
          <button type="button" onClick={() => enter("edit", selectedIndex!)}>Edit in focused chat</button></section>}
        {view === "edit" && selected && <section aria-labelledby="edit-title"><button type="button" className="back-button" onClick={backToLesson}>← Back to lesson</button><p className="eyebrow">Local draft · No Notion or Drive mutation</p><h1 id="edit-title">Editing: {selected.label}</h1><div className="assistant-note"><strong>Focused lesson context</strong><p>{selected.lesson.daily_focus ?? "No daily focus recorded"}. Describe a proposed revision below; the text stays in this browser session and nothing in Notion or Drive is changed.</p></div></section>}
        {view !== "preview" && <section aria-labelledby="notes-title" className="conversation">
          <div className="notes-heading"><h2 id="notes-title">{view === "edit" ? "Proposed edits" : "Local notes"}</h2><span className="unsaved-badge">Unsaved · this session only</span></div>
          <ol aria-label="Your draft messages">{history.map((message, i) => <li key={i}>{message}</li>)}</ol>
          <form onSubmit={submit} className="chat-form"><label htmlFor="chat-input">{view === "edit" ? "Describe a proposed edit" : "Write a draft message"}</label><textarea id="chat-input" rows={3} value={draft} onChange={event => setDrafts(prev => ({ ...prev, [conversationKey]: event.target.value }))} placeholder="Type a note (local draft only)" /><button type="submit" disabled={!draft.trim()}>Add local message</button></form>
          <p className="fine-print">Notes are kept only in this browser tab and do not contact an AI service. Leaving or refreshing the page loses them.</p>
        </section>}
      </main>
      <footer>Teacher OS · #2801 · Read-only · No production actions</footer>
    </div>
  );
}
