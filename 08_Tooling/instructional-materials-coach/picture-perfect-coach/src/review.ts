import type { ActionIdentity } from './uiEvidence';
import type {
  ModelingStepProjection,
  ReviewDecision,
  ReviewedStepProjection,
  ReviewedTutorialProjection,
  UploadEvidenceProjection,
} from './types';

export type ReviewResult =
  | { ok: true; tutorial: ReviewedTutorialProjection }
  | { ok: false; reason: string };

export function needsAttention(step: ModelingStepProjection): boolean {
  return step.disposition === 'needs-review' || step.source.fragile === true || step.source.recovery === true;
}

function validateEvidence(evidence: UploadEvidenceProjection): string | null {
  if (!evidence.recording_id || !/^[a-f0-9]{64}$/.test(evidence.recording_sha256)) return 'Recording identity is incomplete.';
  const stepIds = new Set<string>();
  const candidateIds = new Set<string>();
  for (const candidate of evidence.modeling_candidates) {
    if (!candidate.candidate_id || candidateIds.has(candidate.candidate_id)) return 'Candidate provenance is duplicated.';
    candidateIds.add(candidate.candidate_id);
  }
  let previousSequence = 0;
  for (const step of evidence.modeling_steps) {
    if (!step.step_id || stepIds.has(step.step_id)) return 'Modeled step identity is duplicated.';
    stepIds.add(step.step_id);
    if (step.sequence <= previousSequence) return 'Modeled step order is not deterministic.';
    previousSequence = step.sequence;
    if (!step.source.candidate_id || !step.source.recording_id || !step.source.recording_sha256 ||
      step.source.source_indexes.length === 0 || step.semantic_action_ids.length === 0) return 'Required step provenance is incomplete.';
    if (step.source.recording_id !== evidence.recording_id || step.source.recording_sha256 !== evidence.recording_sha256) {
      return 'Modeled steps contain contradictory recording identity.';
    }
  }
  return null;
}

function actionIdentityFor(
  evidence: UploadEvidenceProjection,
  sourceIndexes: readonly number[],
): ActionIdentity[] {
  const scope = new Set(sourceIndexes);
  return evidence.recording_evidence.actionIdentity.filter((item) => scope.has(item.sourceIndex));
}

function retainedStep(step: ModelingStepProjection, evidence: UploadEvidenceProjection): ReviewedStepProjection {
  return {
    review_step_id: step.step_id,
    sequence: step.sequence,
    source_step_ids: [step.step_id],
    source_steps: [step],
    semantic_action_ids: [...step.semantic_action_ids],
    source_indexes: [...step.source.source_indexes],
    recording_id: step.source.recording_id,
    recording_sha256: step.source.recording_sha256,
    modeled_application: step.source.modeled_application,
    action_identity: actionIdentityFor(evidence, step.source.source_indexes),
    execution_authorized: false,
  };
}

export function deriveReviewedTutorial(evidence: UploadEvidenceProjection, decisions: ReviewDecision[]): ReviewResult {
  const evidenceError = validateEvidence(evidence);
  if (evidenceError) return { ok: false, reason: evidenceError };
  const decisionMap = new Map<string, ReviewDecision['choice']>();
  for (const decision of decisions) {
    if (decisionMap.has(decision.step_id)) return { ok: false, reason: 'A modeled step has conflicting review decisions.' };
    decisionMap.set(decision.step_id, decision.choice);
  }
  if (decisionMap.size !== evidence.modeling_steps.length || evidence.modeling_steps.some((step) => !decisionMap.has(step.step_id))) {
    return { ok: false, reason: 'Every modeled step needs an explicit review decision.' };
  }

  const retained: ReviewedStepProjection[] = [];
  const excluded: string[] = [];
  for (const step of evidence.modeling_steps) {
    const choice = decisionMap.get(step.step_id)!;
    if (choice === 'not-instructional') {
      excluded.push(step.step_id);
      continue;
    }
    if (choice === 'combine-with-previous') {
      const previous = retained.at(-1);
      if (!previous) return { ok: false, reason: 'The first retained step cannot combine with a previous step.' };
      if (previous.recording_id !== step.source.recording_id || previous.recording_sha256 !== step.source.recording_sha256) {
        return { ok: false, reason: 'Combine cannot cross recording identity.' };
      }
      if (previous.modeled_application !== step.source.modeled_application) {
        return { ok: false, reason: 'Combined steps report contradictory modeled application identity.' };
      }
      previous.source_step_ids = [...previous.source_step_ids, step.step_id];
      previous.source_steps = [...previous.source_steps, step];
      previous.semantic_action_ids = [...previous.semantic_action_ids, ...step.semantic_action_ids];
      previous.source_indexes = [...previous.source_indexes, ...step.source.source_indexes];
      // Identities concatenate; each stays bound to its own source index so combining
      // widens which states are in scope without flattening action-local evidence.
      previous.action_identity = [
        ...previous.action_identity,
        ...actionIdentityFor(evidence, step.source.source_indexes),
      ];
      continue;
    }
    retained.push(retainedStep(step, evidence));
  }
  if (retained.length === 0) return { ok: false, reason: 'Review must retain at least one instructional step.' };

  return {
    ok: true,
    tutorial: {
      recording_id: evidence.recording_id,
      recording_sha256: evidence.recording_sha256,
      retained_steps: retained.map((step, index) => ({ ...step, sequence: index + 1 })),
      excluded_step_ids: excluded,
      review_decisions: evidence.modeling_steps.map((step) => ({ step_id: step.step_id, choice: decisionMap.get(step.step_id)! })),
      recording_evidence: evidence.recording_evidence,
      execution_authorized: false,
    },
  };
}
