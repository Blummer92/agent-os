import { useRef, useState } from 'react';
import { useMachine } from '@xstate/react';
import { evidenceStatusLabel, validateUploadText } from './evidence';
import { deriveReviewedTutorial, needsAttention } from './review';
import { PromptCards } from './PromptCards';
import { ReadyPanel } from './ReadyPanel';
import { runReadyPreflight, type ReadyContext, type ReadyPreflightResult } from './preflight';
import { tutorial0CapturedPromptCards, tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import type { ReviewChoice, ReviewDecision, ReviewedTutorialProjection, SafeTechnicalDetails, UploadEvidenceProjection, UploadSummary } from './types';
import { picturePerfectMachine } from './workflowMachine';

const STAGES = ['Model', 'Upload', 'Review', 'Prompts', 'Ready'] as const;
const TUTORIAL0_READY_CONTEXT: ReadyContext = {
  fixtureId: 'tutorial0-privacy-safe-v1',
  requiredTests: ['typecheck', 'lint', 'unit/component tests', 'build', 'guard', 'Playwright', 'repository structural validation'],
  nonGoals: ['no live GitHub mutation', 'no image-provider execution', 'no live Adobe/browser replay', 'no Notion/Drive/classroom write'],
  definitionOfDone: ['all deterministic preflight rows pass', 'handoff packet is generated locally', 'execution_authorized remains false'],
  unresolvedArchitectureDecision: false,
};
type UploadEvidence = { summary: UploadSummary; technical: SafeTechnicalDetails; evidence: UploadEvidenceProjection };

function StageIndicator({ state }: { state: string }) {
  const activeStage = state === 'model_guidance'
    ? 0
    : state.includes('upload') || state === 'awaiting_upload'
      ? 1
      : state === 'ready_for_review' || state === 'reviewing_steps' || state === 'review_attention_required'
        ? 2
        : state === 'tutorial_approved' || state === 'generating_prompts' || state === 'reviewing_prompts'
          ? 3
          : 4;
  return <nav className="stage-nav" aria-label="Picture Perfect stages"><ol>{STAGES.map((label, index) => {
    const current = index === activeStage;
    return <li key={label} className={current ? 'stage current' : 'stage'} aria-current={current ? 'step' : undefined}>
      <span className="stage-number">{index + 1}</span><span>{label}</span>
    </li>;
  })}</ol></nav>;
}

function TechnicalDetails({ technical }: { technical: SafeTechnicalDetails }) {
  return <details className="technical-details"><summary>View technical details</summary><dl className="technical-grid">
    <div><dt>Recording ID</dt><dd>{technical.recordingId}</dd></div><div><dt>Fingerprint</dt><dd className="mono">{technical.recordingSha256}</dd></div>
    <div><dt>RJ3 conformance</dt><dd>{evidenceStatusLabel(technical.rj3State)}</dd></div><div><dt>RJ4 replay equivalence</dt><dd>{evidenceStatusLabel(technical.rj4State)}</dd></div>
  </dl></details>;
}

function ReviewWorkspace({ evidence, decisions, decide, approve }: { evidence: UploadEvidenceProjection; decisions: ReviewDecision[]; decide: (id: string, choice: ReviewChoice) => void; approve: () => void; }) {
  const decisionMap = new Map(decisions.map((decision) => [decision.step_id, decision.choice]));
  const attention = evidence.modeling_steps.filter(needsAttention).length;
  const clear = evidence.modeling_steps.length - attention;
  const result = deriveReviewedTutorial(evidence, decisions);
  return <div className="panel"><p className="step-kicker">Stage 3 · Review</p><h2>Review the instructional steps.</h2>
    <p><strong>{clear} steps look clear</strong> · <strong>{attention} things need your attention</strong></p>
    <p className="boundary-note">Technical evidence can explain a suggestion, but only your explicit review decision approves instructional meaning.</p>
    <div aria-label="Review steps">{evidence.modeling_steps.map((step, index) => <article className="review-card" key={step.step_id}>
      <p className="step-kicker">Step {step.sequence}{needsAttention(step) ? ' · Needs attention' : ''}</p><h3>{step.title ?? `Modeled step ${step.sequence}`}</h3>
      <p><strong>What you did:</strong> {step.student_action ?? 'No student action supplied.'}</p><p><strong>Students need to notice:</strong> {step.notice ?? 'No noticing statement supplied.'}</p><p><strong>Review status:</strong> {decisionMap.get(step.step_id) ?? 'Undecided'}</p>
      <div className="review-actions"><button className="primary" onClick={() => decide(step.step_id, 'keep')}>Keep &amp; Continue</button><button className="secondary" disabled={index === 0} onClick={() => decide(step.step_id, 'combine-with-previous')}>Combine with Previous</button><button className="secondary" onClick={() => decide(step.step_id, 'not-instructional')}>Not Instructional</button></div>
      <details><summary>View source details</summary><p className="mono">{step.step_id}</p><p>Semantic actions: {step.semantic_action_ids.join(', ')}</p><p>Source steps: {step.source.source_indexes.join(', ')}</p><p>RJ3: {evidenceStatusLabel(step.source.rj3_state)} · RJ4: {evidenceStatusLabel(step.source.rj4_state)}</p></details>
    </article>)}</div>
    {!result.ok && <p role="status">Approval blocked: {result.reason}</p>}<button className="primary" disabled={!result.ok} onClick={approve}>Approve Tutorial</button>
  </div>;
}

export function App() {
  const [state, send] = useMachine(picturePerfectMachine);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadEvidence, setUploadEvidence] = useState<UploadEvidence | null>(null);
  const [decisions, setDecisions] = useState<ReviewDecision[]>([]);
  const [approvedCount, setApprovedCount] = useState(0);
  const [reviewedTutorial, setReviewedTutorial] = useState<ReviewedTutorialProjection | null>(null);
  const [preflight, setPreflight] = useState<ReadyPreflightResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const processFile = async (file: File | undefined) => {
    if (!file) return; send({ type: 'UPLOAD_SELECTED' }); setErrorMessage(null); setUploadEvidence(null); setDecisions([]); setPreflight(null);
    const result = validateUploadText(await file.text());
    if (result.ok) { setUploadEvidence({ summary: result.summary, technical: result.technical, evidence: result.evidence }); send({ type: 'UPLOAD_VALID' }); }
    else { setErrorMessage(result.message); send({ type: 'UPLOAD_REJECTED' }); }
  };
  const decide = (stepId: string, choice: ReviewChoice) => setDecisions((current) => [...current.filter((item) => item.step_id !== stepId), { step_id: stepId, choice }]);
  const approve = () => { if (!uploadEvidence) return; const result = deriveReviewedTutorial(uploadEvidence.evidence, decisions); if (!result.ok) return; setApprovedCount(result.tutorial.retained_steps.length); setReviewedTutorial(result.tutorial); send({ type: 'APPROVE_TUTORIAL' }); };
  const generatePrompts = () => {
    if (!reviewedTutorial) return;
    send({ type: 'GENERATE_PROMPTS' });
    if (reviewedTutorial.recording_id === tutorial0ReviewedTutorial.recording_id && reviewedTutorial.recording_sha256 === tutorial0ReviewedTutorial.recording_sha256) send({ type: 'PROMPTS_VALID' });
  };
  const openReady = () => {
    if (!reviewedTutorial || reviewedTutorial.recording_id !== tutorial0ReviewedTutorial.recording_id || reviewedTutorial.recording_sha256 !== tutorial0ReviewedTutorial.recording_sha256) return;
    send({ type: 'OPEN_READY' });
    const result = runReadyPreflight(reviewedTutorial, tutorial0CapturedPromptCards, TUTORIAL0_READY_CONTEXT);
    setPreflight(result); send({ type: result.ready ? 'PREFLIGHT_PASS' : 'PREFLIGHT_FAIL' });
  };
  const stateValue = String(state.value);
  return <main className="app-shell"><header className="hero"><p className="eyebrow">Picture Perfect Coach</p><h1>Turn teacher modeling into clear tutorial visuals.</h1></header>
    <StageIndicator state={stateValue}/><section className="workspace" aria-live="polite">
      {state.matches('model_guidance') && <div className="panel"><p className="step-kicker">Stage 1 · Model</p><h2>Teach the software like you normally would.</h2><p>Model one meaningful action at a time. Recorder evidence stays source evidence; Picture Perfect does not invent missing actions.</p><button className="primary" onClick={() => send({ type: 'CONTINUE_TO_UPLOAD' })}>Continue to Upload</button></div>}
      {state.matches('awaiting_upload') && <div className="panel"><p className="step-kicker">Stage 2 · Upload</p><h2>Upload your Recorder JSON.</h2><input ref={fileInputRef} className="visually-hidden" type="file" accept="application/json,.json" aria-label="Choose Recorder JSON" onChange={(event) => void processFile(event.target.files?.[0])}/><button className="primary" onClick={() => fileInputRef.current?.click()}>Choose recording.json</button></div>}
      {state.matches('validating_upload') && <div className="panel" role="status"><h2>Checking the recording…</h2></div>}
      {state.matches('upload_invalid') && <div className="panel" role="alert"><h2>Picture Perfect stopped safely.</h2><p>{errorMessage}</p><button className="primary" onClick={() => send({ type: 'RETRY_UPLOAD' })}>Choose another file</button></div>}
      {state.matches('upload_valid') && uploadEvidence && <div className="panel"><p className="step-kicker">Stage 2 · Upload</p><h2>Recording loaded</h2><div className="summary-grid" aria-label="Recording summary"><article><strong>{uploadEvidence.summary.actionsFound}</strong><span>actions found</span></article><article><strong>{uploadEvidence.summary.instructionalCandidates}</strong><span>instructional candidates</span></article><article><strong>{uploadEvidence.summary.likelyNoiseRecovery}</strong><span>likely noise/recovery</span></article><article><strong>{uploadEvidence.summary.needsReview}</strong><span>needs your review</span></article></div><TechnicalDetails technical={uploadEvidence.technical}/><button className="primary" onClick={() => send({ type: 'CONTINUE_TO_REVIEW' })}>Continue to Review</button></div>}
      {state.matches('ready_for_review') && uploadEvidence && <div className="panel"><p className="step-kicker">Stage 3 · Review</p><h2>Ready to review the tutorial.</h2><button className="primary" onClick={() => send({ type: 'START_REVIEW' })}>Start Review</button></div>}
      {(state.matches('reviewing_steps') || state.matches('review_attention_required')) && uploadEvidence && <ReviewWorkspace evidence={uploadEvidence.evidence} decisions={decisions} decide={decide} approve={approve}/>} 
      {state.matches('tutorial_approved') && reviewedTutorial && <div className="panel"><p className="step-kicker">Stage 4 · Prompts</p><h2>Tutorial review approved.</h2><p>{approvedCount} reviewed instructional steps are ready for prompt authoring.</p><button className="primary" type="button" onClick={generatePrompts}>Generate Prompts</button></div>}
      {state.matches('generating_prompts') && <div className="panel" role="status"><h2>Preparing provider-neutral prompts…</h2></div>}
      {state.matches('reviewing_prompts') && reviewedTutorial && <section><PromptCards cards={tutorial0CapturedPromptCards}/><div className="panel"><button className="primary" type="button" onClick={openReady}>Open Ready</button></div></section>}
      {state.matches('running_preflight') && <div className="panel" role="status"><h2>Running deterministic preflight…</h2></div>}
      {(state.matches('ready_for_handoff') || state.matches('preflight_failed')) && reviewedTutorial && preflight && <ReadyPanel tutorial={reviewedTutorial} cards={tutorial0CapturedPromptCards} context={TUTORIAL0_READY_CONTEXT} preflight={preflight}/>} 
    </section></main>;
}
