import { useEffect, useRef, useState } from "react";
import { fetchLessons, fetchUnits, isStale, type Lesson, type LoadState, type Loaded, type Unit } from "./notionClient";

type Screen = "chat" | "preview" | "edit";
type MessageMap = Record<string, readonly string[]>;

const NOTICE: Record<string, string> = {
  "not-configured": "The Notion connection is not configured for this server.",
  "source-unverified": "The curriculum source is not verified.",
  "unit-not-approved": "This unit is not in the approved curriculum source.",
};
const safeUrl = (url: string | null) => (url && /^https:\/\//.test(url) ? url : null);

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
  const selected = picked ? { key: `${unit?.unit_id}:${selectedIndex}`, lesson: picked, label: lessonLabel(picked, selectedIndex!) } : null;
  const view: Screen = selected ? screen : "chat";
  useEffect(() => { const t = setInterval(() => setClock(Date.now()), 30_000); return () => clearInterval(t); }, []);
  const conversationKey = view === "edit" && selected ? selected.key : "lesson";
  const draft = drafts[conversationKey] ?? "";
  const history = messages[conversationKey] ?? [];

  function lessonLabel(lesson: Lesson, index: number) { return lesson.day_lesson_number ?? `Lesson ${index + 1}`; }
  function changeUnit(next: string) { setUnitId(next); setLessonIndex(0); setScreen("chat"); setSelectedIndex(null); setSelectedReloadKey(null); }
  function closeAssignments() { setAssignmentOpen(false); triggerRef.current?.focus(); }
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
    if (state.kind === "loading") return <p role="status" className="notice">Loading {what} from Notion…</p>;
    if (state.kind === "empty") return <p role="status" className="notice">Notion returned no {what}. Nothing is shown in its place.</p>;
    if (state.kind === "unavailable") return <p role="alert" className="notice">Notion is unavailable: {NOTICE[state.reason] ?? "the curriculum reader could not be reached."} No substitute {what} are shown.</p>;
    if (state.kind === "error") return <p role="alert" className="notice">Could not read {what} from Notion ({state.reason}). No substitute {what} are shown.</p>;
    return null;
  };
  const provenance = (e: Loaded<unknown>) => `${e.source.display_name} · ${e.source.verification_state} · ${e.source.access} · read ${e.generatedAt}`;

  return (
    <div className="app-shell">
      <header className="app-header">
        <button className="icon-button" type="button" aria-label="Toggle recent conversations" aria-expanded={menuOpen} onClick={() => setMenuOpen(v => !v)}>☰</button>
        <div className="app-title"><strong>Agent OS Teacher</strong><span>{view === "chat" ? "Lesson chat" : view === "preview" ? "Lesson preview" : "Focused lesson chat"}</span></div>
        <button ref={triggerRef} className="assignment-button" type="button" aria-controls="assignment-panel" aria-expanded={assignmentOpen} onClick={() => { setAssignmentOpen(v => !v); setMenuOpen(false); }}>View Assignment <span aria-hidden="true">{assignmentOpen ? "⌃" : "⌄"}</span></button>
      </header>
      <div className="demo-banner" role="status">Read-only · lessons come from verified Notion evidence · Slides, Docs and worksheets stay in approved Google Drive folders</div>
      {stale && evidence && <p role="alert" className="notice">Stale evidence: last read {evidence.generatedAt}. <button type="button" className="text-button" onClick={() => setReloadKey(k => k + 1)}>Refresh from Notion</button></p>}
      {menuOpen && <nav aria-label="Recent conversations" className="recent-menu">
        <h2>Recent conversations</h2>
        <button type="button" onClick={() => { backToLesson(); setMenuOpen(false); }}>{unit ? `${unit.title} — lesson chat` : "Lesson chat"}</button>
        {Object.keys(messages).filter(key => key !== "lesson").map(key => <p key={key}>{key.startsWith(`${unit?.unit_id}:`) ? "Lesson draft chat" : "Draft chat for another unit"} — local only</p>)}
        <p>Recent chats exist only during this session. No external history was loaded.</p>
      </nav>}
      {assignmentOpen && <section id="assignment-panel" aria-label="View Assignment" className="assignment-panel" onKeyDown={event => { if (event.key === "Escape") closeAssignments(); }}>
        <div className="panel-heading"><h2>View Assignment</h2><button className="text-button" type="button" onClick={closeAssignments}>Close</button></div>
        <div className="filters">
          <div><label htmlFor="unit">Unit</label><select id="unit" value={unit?.unit_id ?? ""} disabled={unitList.length === 0} onChange={event => changeUnit(event.target.value)}>
            {unitList.length === 0 && <option value="">No units available</option>}
            {unitList.map(u => <option key={u.unit_id} value={u.unit_id}>{u.title}</option>)}
          </select></div>
          <button className="text-button" type="button" onClick={() => setReloadKey(k => k + 1)}>Refresh from Notion</button>
        </div>
        {sourceNotice(units, "units")}
        {unit && sourceNotice(lessons, "lessons")}
        {current && <div className="carousel" aria-label="Lesson carousel">
          <article className="material-card">
            <div className="card-meta"><span>{lessonLabel(current, lessonIndexClamped)}</span><span>{unit?.title}</span></div>
            <h3>{current.daily_focus ?? "No daily focus recorded in Notion"}</h3>
            <p>{current.daily_learning_target ?? "No learning target recorded in Notion"}</p>
            <div className="card-actions"><button type="button" onClick={() => enter("preview", lessonIndexClamped)}>View full lesson</button><button type="button" onClick={() => enter("edit", lessonIndexClamped)}>Edit in focused chat</button></div>
          </article>
          <div className="carousel-controls"><button type="button" disabled={lessonIndexClamped === 0} onClick={() => setLessonIndex(lessonIndexClamped - 1)}>← Previous</button><span aria-live="polite">{lessonList.length === 0 ? 0 : lessonIndexClamped + 1} of {lessonList.length}</span><button type="button" disabled={lessonIndexClamped >= lessonList.length - 1} onClick={() => setLessonIndex(lessonIndexClamped + 1)}>Next →</button></div>
        </div>}
        {lessons.kind === "ready" && <p className="fine-print">{provenance(lessons.value)}</p>}
      </section>}
      <main className="main-content">
        {view === "chat" && <section aria-labelledby="chat-title"><h1 id="chat-title">{unit?.title ?? "Teacher OS"}</h1>
          {units.kind === "ready" || units.kind === "idle" ? <p className="muted">Discuss your lesson here, or open View Assignment in the top-right corner to inspect lessons read from Notion.</p> : sourceNotice(units, "units")}
        </section>}
        {view === "preview" && selected && <section aria-labelledby="preview-title" className="full-preview"><button type="button" className="back-button" onClick={backToLesson}>← Back to lesson</button>
          <p className="eyebrow">{unit?.title} · read-only Notion lesson</p><h1 id="preview-title">{selected.label}</h1>
          <dl className="sample-page">
            <dt>Daily Learning Target</dt><dd>{selected.lesson.daily_learning_target ?? "Not recorded in Notion"}</dd>
            <dt>Daily Focus</dt><dd>{selected.lesson.daily_focus ?? "Not recorded in Notion"}</dd>
            <dt>Key Vocabulary</dt><dd>{selected.lesson.key_vocabulary ?? "Not recorded in Notion"}</dd>
            <dt>Source Evidence</dt><dd>{selected.lesson.source_evidence ?? "Not recorded in Notion"}</dd>
          </dl>
          {safeUrl(selected.lesson.record_url) && <p><a href={safeUrl(selected.lesson.record_url)!} rel="noreferrer noopener" target="_blank">Open the Notion record</a></p>}
          <p className="fine-print">Slides, worksheets and other student-facing materials are not generated here; they come from approved Google Drive sources.</p>
          {lessons.kind === "ready" && <p className="fine-print">{provenance(lessons.value)}</p>}
          <button type="button" onClick={() => enter("edit", selectedIndex!)}>Edit in focused chat</button></section>}
        {view === "edit" && selected && <section aria-labelledby="edit-title"><button type="button" className="back-button" onClick={backToLesson}>← Back to lesson</button><p className="eyebrow">Local draft · No Notion or Drive mutation</p><h1 id="edit-title">Editing: {selected.label}</h1><div className="assistant-note"><strong>Focused chat context</strong><p>{selected.lesson.daily_focus ?? "No daily focus recorded"}. Describe a proposed revision below; the text stays local and nothing in Notion or Drive is changed.</p></div></section>}
        {view !== "preview" && <section aria-label="Local conversation" className="conversation">
          <ol aria-label="Your draft messages">{history.map((message, i) => <li key={i}>{message}</li>)}</ol>
          <form onSubmit={submit} className="chat-form"><label htmlFor="chat-input">{view === "edit" ? "Describe a proposed edit" : "Write a draft message"}</label><textarea id="chat-input" rows={3} value={draft} onChange={event => setDrafts(prev => ({ ...prev, [conversationKey]: event.target.value }))} placeholder="Type a message (local draft only)" /><button type="submit" disabled={!draft.trim()}>Add local message</button></form>
          <p className="fine-print">Messages are session-only and do not contact an AI service. Leaving this page or refreshing may lose them.</p>
        </section>}
      </main>
      <footer>Teacher OS · #2801 · Read-only · No production actions</footer>
    </div>
  );
}
