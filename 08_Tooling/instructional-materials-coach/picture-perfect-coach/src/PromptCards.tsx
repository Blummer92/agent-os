import type { BoundScreenState } from './captureEvidence';
import type { PromptCardModel } from './promptIntent';

function CaptureState({ state }: { state: BoundScreenState }) {
  return <li>
    <strong>{state.role === 'action' ? 'Action / before-state' : 'Result / after-state'}</strong>
    {' · '}{state.asset_reference.stable_ref}
    {' · '}source {state.source_index}
  </li>;
}

export function PromptCards({ cards }: { cards: readonly PromptCardModel[] }) {
  return (
    <section aria-labelledby="prompt-cards-title">
      <p className="step-kicker">Stage 4 · Prompts</p>
      <h2 id="prompt-cards-title">Picture Perfect prompts</h2>
      <p>These prompts are derived presentation guidance. They never become instructional source evidence.</p>
      <div className="prompt-card-list">
        {cards.map((card) => {
          const capture = card.capturedScreenEvidence ?? null;
          return <article className="prompt-card" key={card.stepNumber}>
            <div className="prompt-card-heading">
              <strong>Image {card.stepNumber}</strong>
              <span>{card.imageState}</span>
              <span>Application: {card.application || 'Needs review'}</span>
              <span>{card.requiresScreenFidelity
                ? capture ? 'Software interface — approved screen capture bound' : 'Software interface — needs screen capture'
                : 'Non-interface visual'}</span>
            </div>
            <p>{card.imagePurpose}</p>
            {card.status === 'blocked' ? (
              <div role="status" className="boundary-note">
                <strong>Prompt blocked</strong>
                <p>{card.blocker}</p>
                <p>
                  No prompt is offered for a blocked frame. Picture Perfect will not generate a
                  stand-in for the real software interface.
                </p>
                <ul aria-label={`Blocker reasons for image ${card.stepNumber}`}>
                  {card.blockerReasons.map((reason) => <li key={reason}><code>{reason}</code></li>)}
                </ul>
                {card.uncertainty && <p>{card.uncertainty}</p>}
              </div>
            ) : (
              <>
                {capture && <p className="boundary-note">Approved captured screen evidence is the base visual. The prompt may not redraw or invent interface content.</p>}
                <label htmlFor={`prompt-${card.stepNumber}`}>Portable prompt</label>
                <textarea id={`prompt-${card.stepNumber}`} readOnly rows={8} value={card.portablePrompt} />
                <button
                  className="secondary"
                  type="button"
                  onClick={() => void navigator.clipboard?.writeText(card.portablePrompt)}
                >
                  Copy Prompt
                </button>
              </>
            )}
            <details className="technical-details">
              <summary>View prompt evidence</summary>
              <dl className="technical-grid">
                <div><dt>Application context</dt><dd>{card.applicationContext}</dd></div>
                <div><dt>Target state</dt><dd>{card.targetState}</dd></div>
                <div><dt>Annotation space</dt><dd>{card.annotationSpace}</dd></div>
              </dl>
              {capture && <>
                <h3>Captured screen evidence</h3>
                <ul>
                  {capture.action && <CaptureState state={capture.action} />}
                  {capture.result && <CaptureState state={capture.result} />}
                </ul>
              </>}
              <h3>Must show</h3>
              <ul>{card.mustShow.map((item) => <li key={item}>{item}</li>)}</ul>
              <h3>Must not show</h3>
              <ul>{card.mustNotShow.map((item) => <li key={item}>{item}</li>)}</ul>
              <h3>Provenance</h3>
              <ul>{card.provenance.map((item) => <li key={item}>{item}</li>)}</ul>
            </details>
          </article>;
        })}
      </div>
    </section>
  );
}
