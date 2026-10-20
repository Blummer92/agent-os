import { useState } from "react";

/**
 * Inert GitHub handoff preview. A React frontend has no direct GitHub MCP or
 * Notion-write connection; a proposal is NOT a provider mutation request.
 */
const categories = ["planning-note", "lesson-candidate", "working-knowledge", "handoff-note"] as const;
type Category = typeof categories[number];
const requestPattern = /^[a-z](?:[a-z0-9]|-(?=[a-z0-9])){2,39}$/;

export function NotionHandoff() {
  const [category, setCategory] = useState<Category>("planning-note");
  const [requestId, setRequestId] = useState("");
  const valid = requestPattern.test(requestId);
  const proposal = valid
    ? "/agent-os teacher-notion-propose " + category + " " + requestId
    : "";

  return (
    <section aria-labelledby="notion-handoff-title" className="notion-handoff">
      <h2 id="notion-handoff-title">Prepare a Notion planning handoff</h2>
      <p>GitHub is the proposed review and audit route. The Teacher OS demo cannot
        submit through GitHub MCP or write to Notion. No write workflow is active.</p>
      <label htmlFor="notion-request-category">Planning request type</label>
      <select
        id="notion-request-category"
        value={category}
        onChange={event => setCategory(event.target.value as Category)}
      >
        <option value="planning-note">Non-governed planning note</option>
        <option value="lesson-candidate">Lesson candidate</option>
        <option value="working-knowledge">Working knowledge</option>
        <option value="handoff-note">Handoff note</option>
      </select>
      <label htmlFor="notion-request-id">Public-safe request slug</label>
      <input
        id="notion-request-id"
        value={requestId}
        maxLength={40}
        onChange={event => setRequestId(event.target.value)}
        placeholder="photography-planning-note"
        autoComplete="off"
        aria-describedby="notion-handoff-guidance"
      />
      <p id="notion-handoff-guidance" className="fine-print">
        Lowercase letters, numbers and hyphens; 3–40 characters. Do not enter
        student names, private details, secrets, or lesson content.
      </p>
      {valid ? (
        <>
          <label htmlFor="notion-proposal-command">Review-only GitHub proposal</label>
          <textarea id="notion-proposal-command" rows={2} readOnly value={proposal} />
          <p role="status" className="fine-print">
            Proposal only. It is not an active GitHub Actions command and does
            not grant Notion access. GitHub commenter identity must be verified.
          </p>
        </>
      ) : (
        <p role="status" className="fine-print">Enter a valid public-safe slug to preview a proposal.</p>
      )}
    </section>
  );
}
