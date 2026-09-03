export const SEQUENCE_FIDELITY_REASONS = {
  frameCountMismatch: 'sequence-frame-count-mismatch',
  frameIdentityMismatch: 'sequence-frame-identity-mismatch',
  objectInventoryDrift: 'sequence-object-inventory-drift',
  targetIdentityDrift: 'sequence-target-identity-drift',
  cameraDrift: 'sequence-camera-drift',
  workplaneDrift: 'sequence-workplane-drift',
  uiDrift: 'sequence-ui-drift',
  tutorialPanelDrift: 'sequence-tutorial-panel-drift',
  themeDrift: 'sequence-theme-drift',
  controlDrift: 'sequence-control-drift',
  unrelatedObjectDrift: 'sequence-unrelated-object-drift',
  sessionIdentityDrift: 'sequence-session-identity-drift',
  ambiguousContinuity: 'sequence-ambiguous-continuity',
  missingTransitionEvidence: 'sequence-missing-transition-evidence',
  singleFrameFinding: 'sequence-single-frame-finding',
} as const;

export type SequenceFidelityReason =
  (typeof SEQUENCE_FIDELITY_REASONS)[keyof typeof SEQUENCE_FIDELITY_REASONS];

export type SequenceFrameSnapshot = Readonly<{
  frameId: string;
  objectIds: readonly string[];
  selectedObjectId?: string;
  cameraState: string;
  workplaneState: string;
  uiState: string;
  tutorialPanelState: string;
  themeState: string;
  controlState: string;
  controlGrammarState: string;
  unrelatedObjectState: string;
  sessionId?: string;
  continuityConfidence: 'resolved' | 'ambiguous';
  singleFrameFindings?: readonly string[];
}>;

export type AuthorizedFrameDelta = Readonly<{
  fromFrameId: string;
  toFrameId: string;
  allowedFields: readonly (keyof Omit<SequenceFrameSnapshot, 'frameId' | 'continuityConfidence' | 'singleFrameFindings'>)[];
}>;

export type SequenceFidelityResult = Readonly<{
  status: 'pass' | 'fail' | 'manual-review';
  reasons: readonly SequenceFidelityReason[];
  singleFrameFindings: readonly string[];
}>;

const trackedFields = [
  'objectIds',
  'selectedObjectId',
  'cameraState',
  'workplaneState',
  'uiState',
  'tutorialPanelState',
  'themeState',
  'controlState',
  'controlGrammarState',
  'unrelatedObjectState',
  'sessionId',
] as const;

type TrackedField = (typeof trackedFields)[number];

function equalValue(a: SequenceFrameSnapshot[TrackedField], b: SequenceFrameSnapshot[TrackedField]): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    const left = [...a].sort();
    const right = [...b].sort();
    return left.every((value, index) => value === right[index]);
  }
  return a === b;
}

function reasonFor(field: TrackedField): SequenceFidelityReason {
  switch (field) {
    case 'objectIds': return SEQUENCE_FIDELITY_REASONS.objectInventoryDrift;
    case 'selectedObjectId': return SEQUENCE_FIDELITY_REASONS.targetIdentityDrift;
    case 'cameraState': return SEQUENCE_FIDELITY_REASONS.cameraDrift;
    case 'workplaneState': return SEQUENCE_FIDELITY_REASONS.workplaneDrift;
    case 'uiState': return SEQUENCE_FIDELITY_REASONS.uiDrift;
    case 'tutorialPanelState': return SEQUENCE_FIDELITY_REASONS.tutorialPanelDrift;
    case 'themeState': return SEQUENCE_FIDELITY_REASONS.themeDrift;
    case 'controlState':
    case 'controlGrammarState':
      return SEQUENCE_FIDELITY_REASONS.controlDrift;
    case 'unrelatedObjectState': return SEQUENCE_FIDELITY_REASONS.unrelatedObjectDrift;
    case 'sessionId': return SEQUENCE_FIDELITY_REASONS.sessionIdentityDrift;
  }
}

function addReason(reasons: SequenceFidelityReason[], reason: SequenceFidelityReason): void {
  if (!reasons.includes(reason)) reasons.push(reason);
}

/**
 * Evaluates only cross-frame continuity. Single-frame visual correctness remains
 * owned by #1542; its findings may be supplied here so sequence reporting composes
 * with, rather than replaces, the single-frame evaluator.
 */
export function evaluateSequenceFidelity(
  expectedFrameIds: readonly string[],
  frames: readonly SequenceFrameSnapshot[],
  deltas: readonly AuthorizedFrameDelta[],
): SequenceFidelityResult {
  const reasons: SequenceFidelityReason[] = [];
  const singleFrameFindings = Object.freeze([
    ...new Set(frames.flatMap((frame) => frame.singleFrameFindings ?? [])),
  ]);

  if (frames.length !== expectedFrameIds.length) {
    addReason(reasons, SEQUENCE_FIDELITY_REASONS.frameCountMismatch);
  }
  if (
    frames.length !== expectedFrameIds.length ||
    frames.some((frame, index) => frame.frameId !== expectedFrameIds[index])
  ) {
    addReason(reasons, SEQUENCE_FIDELITY_REASONS.frameIdentityMismatch);
  }

  if (frames.some((frame) => frame.continuityConfidence === 'ambiguous')) {
    addReason(reasons, SEQUENCE_FIDELITY_REASONS.ambiguousContinuity);
  }

  for (let index = 0; index < frames.length - 1; index += 1) {
    const current = frames[index]!;
    const next = frames[index + 1]!;
    const delta = deltas.find(
      (candidate) => candidate.fromFrameId === current.frameId && candidate.toFrameId === next.frameId,
    );

    if (!delta) {
      addReason(reasons, SEQUENCE_FIDELITY_REASONS.missingTransitionEvidence);
      addReason(reasons, SEQUENCE_FIDELITY_REASONS.ambiguousContinuity);
    }

    const allowed = new Set<TrackedField>(
      delta?.allowedFields as readonly TrackedField[] | undefined,
    );
    for (const field of trackedFields) {
      if (!allowed.has(field) && !equalValue(current[field], next[field])) {
        addReason(reasons, reasonFor(field));
      }
    }
  }

  if (singleFrameFindings.length > 0) {
    addReason(reasons, SEQUENCE_FIDELITY_REASONS.singleFrameFinding);
  }

  const unique = Object.freeze([...reasons]);
  const hasHardFailure = unique.some((reason) => reason !== SEQUENCE_FIDELITY_REASONS.ambiguousContinuity && reason !== SEQUENCE_FIDELITY_REASONS.missingTransitionEvidence);
  if (hasHardFailure) {
    return Object.freeze({ status: 'fail', reasons: unique, singleFrameFindings });
  }
  if (unique.includes(SEQUENCE_FIDELITY_REASONS.ambiguousContinuity)) {
    return Object.freeze({ status: 'manual-review', reasons: unique, singleFrameFindings });
  }
  return Object.freeze({ status: 'pass', reasons: unique, singleFrameFindings });
}
