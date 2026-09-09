import { FormEvent, useRef, useState } from "react";
import { TaskState, validateTaskTitle } from "../shared/task";
import "./task-panel.css";

export function TaskPanel({ state }: { state: TaskState }) {
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const openButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    const nextError = validateTaskTitle(title);
    setError(nextError);
    if (!nextError) setTitle("");
  }

  function openHelp() {
    setDialogOpen(true);
    requestAnimationFrame(() => closeButton.current?.focus());
  }

  function closeHelp() {
    setDialogOpen(false);
    requestAnimationFrame(() => openButton.current?.focus());
  }

  return (
    <div className="task-shell">
      <section aria-labelledby="tasks-heading">
        <h2 id="tasks-heading">Tasks</h2>
        {state.kind === "loading" && <p role="status">Loading tasks…</p>}
        {state.kind === "empty" && <p>No tasks yet.</p>}
        {state.kind === "error" && <p role="alert">{state.message}</p>}
        {state.kind === "success" && <ul>{state.tasks.map(task => <li key={task.id}>{task.title}</li>)}</ul>}
      </section>
      <form onSubmit={submit} noValidate>
        <label htmlFor="task-title">New task</label>
        <input id="task-title" value={title} onChange={e => setTitle(e.target.value)} aria-describedby={error ? "task-error" : undefined} aria-invalid={Boolean(error)} />
        {error && <p id="task-error" role="alert">{error}</p>}
        <button type="submit">Add task</button>
      </form>
      <button ref={openButton} type="button" onClick={openHelp}>Open help</button>
      {dialogOpen && <div role="dialog" aria-modal="true" aria-labelledby="help-title" onKeyDown={e => { if (e.key === "Escape") closeHelp(); }}>
        <h2 id="help-title">Task help</h2><p>Use a short, descriptive task title.</p><button ref={closeButton} type="button" onClick={closeHelp}>Close help</button>
      </div>}
    </div>
  );
}
