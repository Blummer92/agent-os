import tutorialRecording from './fixtures/tutorial0-recording.json';
import tutorialEvidence from './fixtures/tutorial0-evidence.json';
import type {
  EvidenceState,
  ModelingCandidateProjection,
  ModelingStepProjection,
  SafeTechnicalDetails,
  UploadEvidenceProjection,
  UploadSummary,
  UploadValidationResult,
} from './types';

const EVIDENCE_STATES = new Set<EvidenceState>([
  'pending',
  'passed',
  'failed',
  'indeterminate',
  'unavailable',
]);
const MODELING_DISPOSITIONS = new Set(['keep', 'combine', 'not-instructional', 'needs-review']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function canonicalize(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(',')}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function hasRecorderShape(value: unknown): value is { steps: unknown[] } {
  return isRecord(value) && Array.isArray(value.steps) && value.steps.length > 0 &&
    value.steps.every((step) => isRecord(step) && typeof step.type === 'string');
}

function isEvidenceState(value: unknown): value is EvidenceState {
  return typeof value === 'string' && EVIDENCE_STATES.has(value as EvidenceState);
}

function isSourceIndexes(value: unknown): value is number[] {
  return Array.isArray(value) && value.every((item) => Number.isInteger(item) && item >= 0);
}

function isCandidate(value: unknown): value is ModelingCandidateProjection {
  if (!isRecord(value)) return false;
  const rewrite = value.rewrite;
  const rewriteValid = rewrite === null || (isRecord(rewrite) && typeof rewrite.kind === 'string' &&
    typeof rewrite.confidence === 'string' && isSourceIndexes(rewrite.source_indexes));
  return typeof value.candidate_id === 'string' && typeof value.semantic_action_id === 'string' &&
    typeof value.action_kind === 'string' && isSourceIndexes(value.source_indexes) &&
    typeof value.fragile === 'boolean' && typeof value.recovery === 'boolean' && rewriteValid &&
    isEvidenceState(value.rj3_state) && isEvidenceState(value.rj4_state) &&
    value.instructional_disposition === 'undecided' && value.execution_authorized === false;
}

function isModelingStep(value: unknown): value is ModelingStepProjection {
  if (!isRecord(value) || !isRecord(value.source)) return false;
  return typeof value.step_id === 'string' && Number.isInteger(value.sequence) &&
    typeof value.disposition === 'string' && MODELING_DISPOSITIONS.has(value.disposition) &&
    (value.title === undefined || typeof value.title === 'string') &&
    (value.student_action === undefined || value.student_action === null || typeof value.student_action === 'string') &&
    (value.notice === undefined || value.notice === null || typeof value.notice === 'string') &&
    (value.check === undefined || value.check === null || typeof value.check === 'string') &&
    Array.isArray(value.semantic_action_ids) && value.semantic_action_ids.every((item) => typeof item === 'string') &&
    typeof value.source.candidate_id === 'string' && typeof value.source.recording_id === 'string' &&
    typeof value.source.recording_sha256 === 'string' && isSourceIndexes(value.source.source_indexes) &&
    isEvidenceState(value.source.rj3_state) && isEvidenceState(value.source.rj4_state) &&
    (value.source.fragile === undefined || typeof value.source.fragile === 'boolean') &&
    (value.source.recovery === undefined || typeof value.source.recovery === 'boolean') &&
    value.execution_authorized === false;
}

function evidenceProjection(value: unknown): UploadEvidenceProjection | null {
  if (!isRecord(value)) return null;
  if (typeof value.recording_id !== 'string' || typeof value.recording_sha256 !== 'string' ||
    !/^[a-f0-9]{64}$/.test(value.recording_sha256) || !Number.isInteger(value.recorder_step_count) ||
    !isEvidenceState(value.rj3_state) || !isEvidenceState(value.rj4_state) ||
    !Array.isArray(value.modeling_candidates) || !value.modeling_candidates.every(isCandidate) ||
    !Array.isArray(value.modeling_steps) || !value.modeling_steps.every(isModelingStep)) return null;
  return value as unknown as UploadEvidenceProjection;
}

export function summarizeEvidence(evidence: UploadEvidenceProjection): UploadSummary {
  return {
    actionsFound: evidence.modeling_candidates.length,
    instructionalCandidates: evidence.modeling_steps.filter((step) => ['keep', 'combine', 'needs-review'].includes(step.disposition)).length,
    likelyNoiseRecovery: evidence.modeling_candidates.filter((candidate) => candidate.recovery || candidate.rewrite?.kind === 'remove-noise').length,
    needsReview: evidence.modeling_steps.filter((step) => step.disposition === 'needs-review').length,
  };
}

export function safeTechnicalDetails(evidence: UploadEvidenceProjection): SafeTechnicalDetails {
  return {
    recordingId: evidence.recording_id,
    recordingSha256: evidence.recording_sha256,
    rj3State: evidence.rj3_state,
    rj4State: evidence.rj4_state,
    actions: evidence.modeling_candidates.map((candidate) => ({
      semanticActionId: candidate.semantic_action_id,
      actionKind: candidate.action_kind,
      sourceIndexes: [...candidate.source_indexes],
      fragile: candidate.fragile,
      recovery: candidate.recovery,
    })),
  };
}

export function validateUploadText(text: string): UploadValidationResult {
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch {
    return { ok: false, message: 'This file is not valid Recorder JSON. Export the recording again and choose the JSON file.' };
  }
  if (!hasRecorderShape(parsed)) {
    return { ok: false, message: 'This JSON does not contain the bounded Recorder step structure required by this upload screen.' };
  }
  if (canonicalize(parsed) !== canonicalize(tutorialRecording)) {
    return { ok: false, message: 'The recording parsed, but this offline slice has no Teacher Modeling evidence for it yet. No instructional counts were guessed.' };
  }
  const evidence = evidenceProjection(tutorialEvidence);
  if (evidence === null || evidence.recorder_step_count !== parsed.steps.length) {
    return { ok: false, message: 'The synthetic recording evidence is incomplete or mismatched, so Picture Perfect stopped safely.' };
  }
  return { ok: true, summary: summarizeEvidence(evidence), technical: safeTechnicalDetails(evidence), evidence };
}

export function evidenceStatusLabel(state: EvidenceState): string {
  const labels: Record<EvidenceState, string> = {
    pending: 'Pending — not proven', passed: 'Passed evidence supplied', failed: 'Failed evidence supplied',
    indeterminate: 'Indeterminate — not proven', unavailable: 'Unavailable — not proven',
  };
  return labels[state];
}
