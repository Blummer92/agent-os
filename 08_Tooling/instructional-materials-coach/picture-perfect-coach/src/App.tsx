import { useRef, useState } from 'react';
import { useMachine } from '@xstate/react';
import { evidenceStatusLabel, validateUploadText } from './evidence';
import type { SafeTechnicalDetails, UploadSummary } from './types';
import { picturePerfectMachine } from './workflowMachine';

const STAGES = ['Model', 'Upload', 'Review', 'Prompts', 'Ready'] as const;

type UploadEvidence = {
  summary: UploadSummary;
  technical: SafeTechnicalDetails;
};

function StageIndicator({ state }: { state: string }) {
  const activeStage = state === 'model_guidance' ? 0 : 1;
  return (
    <nav className="stage-nav" aria-label="Picture Perfect stages">
      <ol>
        {STAGES.map((label, index) => {
          const isImplemented = index < 2;
          const isCurrent = index === activeStage;
          return (
            <li
              key={label}
              className={isCurrent ? 'stage current' : 'stage'}
              aria-current={isCurrent ? 'step' : undefined}
              aria-disabled={!isImplemented ? 'true' : undefined}
            >
              <span className="stage-number">{index + 1}</span>
              <span>{label}</span>
              {!isImplemented && <span className="stage-note">Later slice</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function TechnicalDetails({ technical }: { technical: SafeTechnicalDetails }) {
  return (
    <details className="technical-details">
      <summary>View technical details</summary>
      <dl className="technical-grid">
        <div>
          <dt>Recording ID</dt>
          <dd>{technical.recordingId}</dd>
        </div>
        <div>
          <dt>Fingerprint</dt>
          <dd className="mono">{technical.recordingSha256}</dd>
        </div>
        <div>
          <dt>RJ3 conformance</dt>
          <dd>{evidenceStatusLabel(technical.rj3State)}</dd>
        </div>
        <div>
          <dt>RJ4 replay equivalence</dt>
          <dd>{evidenceStatusLabel(technical.rj4State)}</dd>
        </div>
      </dl>
      <div className="action-evidence">
        <h3>Bounded action provenance</h3>
        <ul>
          {technical.actions.map((action) => (
            <li key={action.semanticActionId}>
              <span className="mono">{action.semanticActionId}</span>
              {' · '}
              {action.actionKind}
              {' · source steps '}
              {action.sourceIndexes.join(', ')}
              {action.fragile ? ' · fragile evidence' : ''}
              {action.recovery ? ' · recovery evidence' : ''}
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

export function App() {
  const [state, send] = useMachine(picturePerfectMachine);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadEvidence, setUploadEvidence] = useState<UploadEvidence | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const processFile = async (file: File | undefined) => {
    if (!file) return;
    send({ type: 'UPLOAD_SELECTED' });
    setErrorMessage(null);
    setUploadEvidence(null);
    const result = validateUploadText(await file.text());
    if (result.ok) {
      setUploadEvidence({ summary: result.summary, technical: result.technical });
      send({ type: 'UPLOAD_VALID' });
    } else {
      setErrorMessage(result.message);
      send({ type: 'UPLOAD_REJECTED' });
    }
  };

  const stateValue = String(state.value);

  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">Picture Perfect Coach</p>
        <h1>Turn teacher modeling into clear tutorial visuals.</h1>
        <p className="hero-copy">
          This first slice helps you model a workflow, upload Recorder JSON, and review a safe summary before the tutorial-review stage.
        </p>
      </header>

      <StageIndicator state={stateValue} />

      <section className="workspace" aria-live="polite">
        {state.matches('model_guidance') && (
          <div className="panel">
            <p className="step-kicker">Stage 1 · Model</p>
            <h2>Teach the software like you normally would.</h2>
            <div className="guidance-grid">
              <article>
                <strong>1. Do one meaningful action at a time.</strong>
                <p>Keep each modeled move easy to understand later.</p>
              </article>
              <article>
                <strong>2. Pause for the interface.</strong>
                <p>Give the software time to show the result of the action.</p>
              </article>
              <article>
                <strong>3. Finish one small objective.</strong>
                <p>Stop the recording when this tutorial objective is complete.</p>
              </article>
            </div>
            <details className="recorder-tips">
              <summary>Recorder tips</summary>
              <ul>
                <li>Use a stable desktop viewport and normal zoom.</li>
                <li>Keep incidental support or browser actions out of the modeled objective.</li>
                <li>Recorder evidence is source evidence; Picture Perfect does not invent missing actions.</li>
              </ul>
            </details>
            <button className="primary" onClick={() => send({ type: 'CONTINUE_TO_UPLOAD' })}>
              Continue to Upload
            </button>
          </div>
        )}

        {state.matches('awaiting_upload') && (
          <div className="panel">
            <p className="step-kicker">Stage 2 · Upload</p>
            <h2>Upload your Recorder JSON.</h2>
            <p>Picture Perfect will show only bounded, teacher-friendly evidence in this offline slice.</p>
            <input
              ref={fileInputRef}
              className="visually-hidden"
              type="file"
              accept="application/json,.json"
              aria-label="Choose Recorder JSON"
              onChange={(event) => void processFile(event.target.files?.[0])}
            />
            <div
              className="drop-zone"
              role="button"
              tabIndex={0}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                void processFile(event.dataTransfer.files?.[0]);
              }}
            >
              <strong>Drop your Recorder JSON here</strong>
              <span>or choose recording.json</span>
            </div>
            <button className="secondary" onClick={() => fileInputRef.current?.click()}>
              Choose recording.json
            </button>
          </div>
        )}

        {state.matches('validating_upload') && (
          <div className="panel status-panel" role="status">
            <p className="step-kicker">Stage 2 · Upload</p>
            <h2>Checking the recording…</h2>
            <p>No external service is contacted.</p>
          </div>
        )}

        {state.matches('upload_invalid') && (
          <div className="panel status-panel" role="alert">
            <p className="step-kicker">Stage 2 · Upload</p>
            <h2>Picture Perfect stopped safely.</h2>
            <p>{errorMessage}</p>
            <button className="primary" onClick={() => send({ type: 'RETRY_UPLOAD' })}>
              Choose another file
            </button>
          </div>
        )}

        {state.matches('upload_valid') && uploadEvidence && (
          <div className="panel">
            <p className="step-kicker">Stage 2 · Upload</p>
            <h2>Recording loaded</h2>
            <div className="summary-grid" aria-label="Recording summary">
              <article><strong>{uploadEvidence.summary.actionsFound}</strong><span>actions found</span></article>
              <article><strong>{uploadEvidence.summary.instructionalCandidates}</strong><span>instructional candidates</span></article>
              <article><strong>{uploadEvidence.summary.likelyNoiseRecovery}</strong><span>likely noise/recovery</span></article>
              <article><strong>{uploadEvidence.summary.needsReview}</strong><span>needs your review</span></article>
            </div>
            <p className="boundary-note">
              RJ3 conformance and RJ4 replay equivalence remain separate evidence. Pending does not mean proven.
            </p>
            <TechnicalDetails technical={uploadEvidence.technical} />
            <button className="primary" onClick={() => send({ type: 'CONTINUE_TO_REVIEW' })}>
              Continue to Review boundary
            </button>
          </div>
        )}

        {state.matches('ready_for_review') && (
          <div className="panel status-panel">
            <p className="step-kicker">Review boundary</p>
            <h2>Ready for the Review slice.</h2>
            <p>
              The upload evidence is ready to hand to PPUX-B. Keep, Combine, and Not Instructional decisions are intentionally not implemented here.
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
