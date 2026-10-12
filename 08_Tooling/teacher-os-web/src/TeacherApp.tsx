import { useRef, useState } from "react";
import { courses, schoolYears, selectCourse, selectUnit, type Material } from "./fixtures";

type Screen = "chat" | "preview" | "edit";
type Scenario = "fixture" | "loading" | "empty" | "unavailable" | "stale" | "error";
type MessageMap = Record<string, readonly string[]>;

export function TeacherApp() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [assignmentOpen, setAssignmentOpen] = useState(false);
  const [schoolYear, setSchoolYear] = useState<string>(schoolYears[0]);
  const [courseId, setCourseId] = useState("media1");
  const [unitId, setUnitId] = useState("photography");
  const [materialIndex, setMaterialIndex] = useState(0);
  const [screen, setScreen] = useState<Screen>("chat");
  const [selectedMaterial, setSelectedMaterial] = useState<Material | null>(null);
  const [scenario, setScenario] = useState<Scenario>("fixture");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<MessageMap>({});
  const triggerRef = useRef<HTMLButtonElement>(null);
  const course = selectCourse(courseId) ?? courses[0];
  const unit = selectUnit(course, unitId) ?? course.units[0];
  const materials = unit.materials;
  const current = materials[materialIndex] ?? materials[0];
  const conversationKey = screen === "edit" && selectedMaterial ? selectedMaterial.id : "lesson";
  const draft = drafts[conversationKey] ?? "";
  const history = messages[conversationKey] ?? [];
  const hasMaterials = scenario === "fixture" || scenario === "stale";

  function changeCourse(next: string) {
    const selected = selectCourse(next);
    if (!selected) return;
    setCourseId(next);
    setUnitId(selected.units[0].id);
    setMaterialIndex(0);
  }
  function changeUnit(next: string) {
    if (!selectUnit(course, next)) return;
    setUnitId(next);
    setMaterialIndex(0);
  }
  function closeAssignments() {
    setAssignmentOpen(false);
    triggerRef.current?.focus();
  }
  function enter(next: "preview" | "edit", material: Material) {
    setSelectedMaterial(material);
    setScreen(next);
    setAssignmentOpen(false);
    setMenuOpen(false);
  }
  function backToLesson() {
    setScreen("chat");
    setSelectedMaterial(null);
  }
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    setMessages(prev => ({ ...prev, [conversationKey]: [...(prev[conversationKey] ?? []), trimmed] }));
    setDrafts(prev => ({ ...prev, [conversationKey]: "" }));
  }
  return (
    <div className="app-shell">
      <header className="app-header">
        <button className="icon-button" type="button" aria-label="Toggle recent conversations" aria-expanded={menuOpen} onClick={() => setMenuOpen(v => !v)}>☰</button>
        <div className="app-title"><strong>Agent OS Teacher</strong><span>{screen === "chat" ? "Lesson chat" : screen === "preview" ? "Material preview" : "Focused material chat"}</span></div>
        <button ref={triggerRef} className="assignment-button" type="button" aria-controls="assignment-panel" aria-expanded={assignmentOpen} onClick={() => { setAssignmentOpen(v => !v); setMenuOpen(false); }}>View Assignment <span aria-hidden="true">{assignmentOpen ? "⌃" : "⌄"}</span></button>
      </header>
      <div className="demo-banner" role="status">Interactive sample · Fixture data · No Notion, Drive or AI connection</div>
      {menuOpen && <nav aria-label="Recent conversations" className="recent-menu">
        <h2>Recent conversations</h2>
        <button type="button" onClick={() => { backToLesson(); setMenuOpen(false); }}>Photography Foundations — lesson chat</button>
        {Object.keys(messages).filter(key => key !== "lesson").map(key => (
          <button type="button" key={key} onClick={() => {
            const material = courses.flatMap(c => c.units).flatMap(u => u.materials).find(m => m.id === key);
            if (material) enter("edit", material);
          }}>{key.replaceAll("-", " ")} — local draft chat</button>
        ))}
        <p>Recent chats exist only during this session. No external history was loaded.</p>
      </nav>}
      {assignmentOpen && <section id="assignment-panel" aria-label="View Assignment" className="assignment-panel" onKeyDown={event => { if (event.key === "Escape") closeAssignments(); }}>
        <div className="panel-heading"><h2>View Assignment</h2><button className="text-button" type="button" onClick={closeAssignments}>Close</button></div>
        <label htmlFor="year">School year</label>
        <select id="year" value={schoolYear} onChange={event => setSchoolYear(event.target.value)}>{schoolYears.map(y => <option key={y}>{y}</option>)}</select>
        <div className="filters">
          <div><label htmlFor="course">Course</label><select id="course" value={courseId} onChange={event => changeCourse(event.target.value)}>{courses.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}</select></div>
          <div><label htmlFor="unit">Unit</label><select id="unit" value={unitId} onChange={event => changeUnit(event.target.value)}>{course.units.map(u => <option key={u.id} value={u.id}>{u.title}</option>)}</select></div>
        </div>
        <div className="source-controls"><label htmlFor="source-scenario">Demo source scenario</label><select id="source-scenario" value={scenario} onChange={event => setScenario(event.target.value as Scenario)}>
          <option value="fixture">Available fixture</option><option value="loading">Loading (simulated)</option><option value="empty">Empty (simulated)</option><option value="unavailable">Unavailable (simulated)</option><option value="stale">Stale (simulated)</option><option value="error">Error (simulated)</option>
        </select></div>
        <div className="panel-meta"><span>{unit.title}</span><span>Grade {course.grade} · {schoolYear}</span></div>
        {scenario === "stale" && <p role="alert" className="notice">Stale sample evidence. Preview is illustrative only; no live action is authorized.</p>}
        {scenario === "loading" && <p role="status" className="notice">Simulated loading. No network request is running.</p>}
        {scenario === "empty" && <p role="status" className="notice">No materials in this simulated scenario.</p>}
        {scenario === "unavailable" && <p role="alert" className="notice">Current curriculum source is not connected. Sample selectors do not represent live Notion data.</p>}
        {scenario === "error" && <p role="alert" className="notice">Simulated source error. No source data was modified.</p>}
        {hasMaterials && <div className="carousel" aria-label="Material carousel">
          <article className="material-card">
            <div className="card-meta"><span>{current.kind === "unit" ? "Unit overview" : current.kind === "slides" ? "Slide deck" : "Worksheet"}</span><span>Grade {course.grade}</span></div>
            <h3>{current.title}</h3><p>{current.summary}</p>
            <div className="sample-paper" aria-label="Sample material excerpt">{current.preview.slice(0,2).map(line => <p key={line}>{line}</p>)}</div>
            <div className="card-actions"><button type="button" onClick={() => enter("preview", current)}>View full preview</button><button type="button" onClick={() => enter("edit", current)}>Edit in focused chat</button></div>
          </article>
          <div className="carousel-controls"><button type="button" disabled={materialIndex === 0} onClick={() => setMaterialIndex(v => v - 1)}>← Previous</button><span aria-live="polite">{materialIndex + 1} of {materials.length}</span><button type="button" disabled={materialIndex === materials.length - 1} onClick={() => setMaterialIndex(v => v + 1)}>Next →</button></div>
        </div>}
      </section>}
      <main className="main-content">
        {screen === "chat" && <section aria-labelledby="chat-title"><h1 id="chat-title">Photography Foundations</h1><p className="muted">Discuss your lesson here, or open View Assignment in the top-right corner to inspect sample materials.</p><div className="assistant-note"><strong>Sample assistant</strong><p>We can explore the Rule of Thirds. The material previews are fixtures; no lesson has been generated or saved.</p></div></section>}
        {screen === "preview" && selectedMaterial && <section aria-labelledby="preview-title" className="full-preview"><button type="button" className="back-button" onClick={backToLesson}>← Back to lesson</button><p className="eyebrow">Full sample preview · Grade {course.grade}</p><h1 id="preview-title">{selectedMaterial.title}</h1><p>{selectedMaterial.summary}</p><div className="sample-page">{selectedMaterial.preview.map((line, i) => <div key={i} className="preview-question"><strong>{i + 1}.</strong><p>{line}</p><div className="response-lines" aria-hidden="true" /></div>)}</div><button type="button" onClick={() => enter("edit", selectedMaterial)}>Edit in focused chat</button></section>}
        {screen === "edit" && selectedMaterial && <section aria-labelledby="edit-title"><button type="button" className="back-button" onClick={backToLesson}>← Back to lesson</button><p className="eyebrow">Local demonstration · No material mutation</p><h1 id="edit-title">Editing: {selectedMaterial.title}</h1><div className="assistant-note"><strong>Focused chat context</strong><p>{selectedMaterial.summary}. Describe a proposed revision below; the text remains local and no worksheet or slide deck is changed.</p></div></section>}
        {screen !== "preview" && <section aria-label="Local conversation" className="conversation">
          <ol aria-label="Your sample messages">{history.map((message, i) => <li key={i}>{message}</li>)}</ol>
          <form onSubmit={submit} className="chat-form"><label htmlFor="chat-input">{screen === "edit" ? "Describe a proposed edit" : "Write a sample chat message"}</label><textarea id="chat-input" rows={3} value={draft} onChange={event => setDrafts(prev => ({ ...prev, [conversationKey]: event.target.value }))} placeholder="Type a message (local demo only)" /><button type="submit" disabled={!draft.trim()}>Add local message</button></form>
          <p className="fine-print">Messages are session-only and do not contact an AI service. Leaving this page or refreshing may lose them.</p>
        </section>}
      </main>
      <footer>Teacher OS first slice · #2801 · No production actions</footer>
    </div>
  );
}
