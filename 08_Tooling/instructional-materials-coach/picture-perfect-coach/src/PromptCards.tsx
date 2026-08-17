import type { PromptCardModel } from './promptIntent';

export function PromptCards({ cards }: { cards: readonly PromptCardModel[] }) {
  return (
    <section aria-labelledby="prompt-cards-title">
      <p className="step-kicker">Stage 4 · Prompts</p>
      <h2 id="prompt-cards-title">Picture Perfect prompts</h2>
      <p>These prompts are derived presentation guidance. They never become instructional source evidence.</p>
      <div className="prompt-card-list">
        {cards.map((card) => (
          <article className="prompt-card" key={card.stepNumber}>
            <div className="prompt-card-heading">
              <strong>Image {card.stepNumber}</strong>
              <span>{card.imageState}</span>
              <span>Application: {card.application || 'Needs review'}</span>
            </div>
            <p>{card.imagePurpose}</p>
            {card.status === 'blocked' ? (
              <div role="status" className="boundary-note">
                <strong>Prompt blocked</strong>
                <p>{card.blocker}</p>
                {card.uncertainty && <p>{card.uncertainty}</p>}
              </div>
            ) : (
              <>
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
              <h3>Must show</h3>
              <ul>{card.mustShow.map((item) => <li key={item}>{item}</li>)}</ul>
              <h3>Must not show</h3>
              <ul>{card.mustNotShow.map((item) => <li key={item}>{item}</li>)}</ul>
              <h3>Provenance</h3>
              <ul>{card.provenance.map((item) => <li key={item}>{item}</li>)}</ul>
            </details>
          </article>
        ))}
      </div>
    </section>
  );
}
