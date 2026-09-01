export const SEQUENCE_FIDELITY_REASONS = {
  frameCountMismatch: 'sequence-frame-count-mismatch',
  frameIdentityMismatch: 'sequence-frame-identity-mismatch',
  objectInventoryDrift: 'sequence-object-inventory-drift',
  targetIdentityDrift: 'sequence-target-identity-drift',
  cameraDrift: 'sequence-camera-drift',
  workplaneDrift: 'sequence-workplane-drift',
  uiDrift: 'sequence-ui-drift',
  controlDrift: 'sequence-control-drift',
  unrelatedObjectDrift: 'sequence-unrelated-object-drift',
  ambiguousContinuity: 'sequence-ambiguous-continuity',
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
  controlState: string;
  unrelatedObjectState: string;
  continuityConfidence: 'resolved' | 'ambiguous';
}>;

export type AuthorizedFrameDelta = Readonly<{
  fromFrameId: string;
  toFrameId: string;
  allowedFields: readonly (keyof Omit<SequenceFrameSnapshot, 'frameId' | 'continuityConfidence'>)[];
}>;

export type SequenceFidelityResult = Readonly<{
  status: 'pass' | 'fail' | 'manual-review';
  reasons: readonly SequenceFidelityReason[];
}>;

const trackedFields = [
  'objectIds',
  'selectedObjectId',
  'cameraState',
  'workplaneState',
  'uiState',
  'controlState',
  'unrelatedObjectState',
] as const;

type TrackedField = (typeof trackedFields)[number];

function equalValue(a: SequenceFrameSnapshot[TrackedField], b: SequenceFrameSnapshot[TrackedField]): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((value, index) => value === b[index]);
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
    case 'controlState': return SEQUENCE_FIDELITY_REASONS.controlDrift;
    case 'unrelatedObjectState': return SEQUENCE_FIDELITY_REASONS.unrelatedObjectDrift;
  }
}

/**
 * Evaluates only sequence continuity. Single-frame visual correctness remains
 * owned by the single-frame fidelity contract. The evaluator consumes explicit
 * frame IDs and authorized deltas and never guesses continuity from provider
 * identity or visual plausibility.
 */
export function evaluateSequenceFidelity(
  expectedFrameIds: readonly string[],
  frames: readonly SequenceFrameSnapshot[],
  deltas: readonly AuthorizedFrameDelta[],
): SequenceFidelityResult {
  const reasons: SequenceFidelityReason[] = [];

  if (frames.length !== expectedFrameIds.length) {
    reasons.push(SEQUENCE_FIDELITY_REASONS.frameCountMismatch);
  }
  if (
    frames.length !== expectedFrameIds.length ||
    frames.some((frame, index) => frame.frameId !== expectedFrameIds[index])
  ) {
    reasons.push(SEQUENCE_FIDELITY_REASONS.frameIdentityMismatch);
  }

  if (frames.some((frame) => frame.continuityConfidence === 'ambiguous')) {
    reasons.push(SEQUENCE_FIDELITY_REASONS.ambiguousContinuity);
  }

  for (let index = 0; index < frames.length - 1; index += 1) {
    const current = frames[index]!;
    const next = frames[index + 1]!;
    const delta = deltas.find(
      (candidate) => candidate.fromFrameId === current.frameId && candidate.toFrameId === next.frameId,
    );

    if (!delta) {
      reasons.push(SEQUENCE_FIDELITY_REASONS.ambiguousContinuity);
      continue;
    }

    const allowed = new Set<TrackedField>(delta.allowedFields as readonly TrackedField[]);
    for (const field of trackedFields) {
      if (!allowed.has(field) && !equalValue(current[field], next[field])) {
        reasons.push(reasonFor(field));
      }
    }
  }

  const unique = Object.freeze([...new Set(reasons)]);
  if (unique.includes(SEQUENCE_FIDELITY_REASONS.ambiguousContinuity)) {
    return Object.freeze({ status: 'manual-review', reasons: unique });
  }
  return Object.freeze({ status: unique.length === 0 ? 'pass' : 'fail', reasons: unique });
}
