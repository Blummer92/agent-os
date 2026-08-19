import { useState } from 'react';
import { createGitHubHandoffPacket, type GitHubHandoffPacket, type ReadyContext, type ReadyPreflightResult } from './preflight';
import type { PromptCardModel } from './promptIntent';
import type { ReviewedTutorialProjection } from './types';

export function ReadyPanel({ tutorial, cards, context, preflight }: {
  tutorial: ReviewedTutorialProjection;
  cards: readonly PromptCardModel[];
  context: ReadyContext;
  preflight: ReadyPreflightResult;
}) {
  const [packet, setPacket] = useState<GitHubHandoffPacket | null>(null);
  return <section className="panel" aria-labelledby="ready-title">
    <p className="step-kicker">Stage 5 · Ready</p>
    <h2 id="ready-title">Implementation handoff preflight</h2>
    <p>Ready means the authoring evidence is complete enough to prepare a bounded implementation packet. It does not authorize GitHub or external execution.</p>
    <div className="preflight-list" aria-label="Ready preflight">
      {preflight.rows.map((row) => <article className="preflight-row" key={row.id}>
        <strong>{row.state === 'pass' ? 'Pass' : row.state === 'not-applicable' ? 'N/A' : 'Blocked'} · {row.label}</strong>
        <p>{row.detail}</p>
      </article>)}
    </div>
    {!preflight.ready && <p role="status" className="boundary-note">Create GitHub Handoff stays disabled until every required preflight row passes.</p>}
    <button className="primary" type="button" disabled={!preflight.ready} onClick={() => setPacket(createGitHubHandoffPacket(tutorial, cards, context))}>Create GitHub Handoff</button>
    {packet && <details className="technical-details" open>
      <summary>Generated implementation acceptance packet</summary>
      <p className="boundary-note">Local packet only. execution_authorized: false. No GitHub write occurred.</p>
      <textarea aria-label="GitHub handoff packet" readOnly rows={18} value={JSON.stringify(packet, null, 2)} />
    </details>}
  </section>;
}
