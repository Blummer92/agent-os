import type { ImageState } from './promptIntent';

export type PresentationModality = 'still-frame' | 'frame-sequence' | 'motion-required';
export type ModalityDecisionStatus = 'ready' | 'needs-review';

export const MODALITY_BLOCKER_REASONS = {
  ambiguousEvidence: 'presentation-modality-ambiguous-evidence',
  missingEvidence: 'presentation-modality-missing-evidence',
  missingFrameEvidence: 'presentation-modality-missing-frame-evidence',
  duplicateFrameOrder: 'presentation-modality-duplicate-frame-order',
} as const;

export type ModalityBlockerReason =
  (typeof MODALITY_BLOCKER_REASONS)[keyof typeof MODALITY_BLOCKER_REASONS];

export type ModalityFrameEvidence = Readonly<{
  sequence: number;
  evidenceId: string;
  imageState: ImageState;
  provenance: readonly string[];
}>;

export type PresentationEvidence = Readonly<{
  instructionalIntentId: string;
  stableVisualStateSufficient: boolean;
  distinctVisualStatesRequired: boolean;
  continuousTemporalBehaviorRequired: boolean;
  frameEvidence: readonly ModalityFrameEvidence[];
}>;

export type PresentationModalityDecision = Readonly<{
  status: ModalityDecisionStatus;
  modality: PresentationModality | null;
  evidenceId: string;
  frameEvidence: readonly ModalityFrameEvidence[];
  blockerReasons: readonly ModalityBlockerReason[];
}>;

/**
 * Select presentation modality from approved instructional evidence only.
 * Provider/model identity, price, and available generation features are
 * intentionally absent from the input contract so they cannot become authority.
 */
export function selectPresentationModality(
  evidence: PresentationEvidence,
): PresentationModalityDecision {
  const blockers: ModalityBlockerReason[] = [];

  if (!evidence.instructionalIntentId.trim()) {
    blockers.push(MODALITY_BLOCKER_REASONS.missingEvidence);
  }

  const assertedModes = [
    evidence.stableVisualStateSufficient,
    evidence.distinctVisualStatesRequired,
    evidence.continuousTemporalBehaviorRequired,
  ].filter(Boolean).length;

  if (assertedModes !== 1) {
    blockers.push(MODALITY_BLOCKER_REASONS.ambiguousEvidence);
  }

  const ordered = [...evidence.frameEvidence].sort((a, b) => a.sequence - b.sequence);
  if (new Set(ordered.map((frame) => frame.sequence)).size !== ordered.length) {
    blockers.push(MODALITY_BLOCKER_REASONS.duplicateFrameOrder);
  }

  if (evidence.distinctVisualStatesRequired && ordered.length < 2) {
    blockers.push(MODALITY_BLOCKER_REASONS.missingFrameEvidence);
  }

  const modality: PresentationModality | null = blockers.length > 0
    ? null
    : evidence.continuousTemporalBehaviorRequired
      ? 'motion-required'
      : evidence.distinctVisualStatesRequired
        ? 'frame-sequence'
        : 'still-frame';

  return Object.freeze({
    status: blockers.length > 0 ? 'needs-review' : 'ready',
    modality,
    evidenceId: evidence.instructionalIntentId,
    frameEvidence: Object.freeze(ordered),
    blockerReasons: Object.freeze([...new Set(blockers)]),
  });
}

export type StillImageRoute = Readonly<{
  allowed: boolean;
  canonical: boolean;
  reason: 'still-compatible' | 'motion-required' | 'modality-unresolved' | 'non-canonical-preview';
}>;

/** Gate all still-image planning behind an admitted modality decision. */
export function admitStillImageRoute(
  decision: PresentationModalityDecision,
  request: Readonly<{ previewRequested?: boolean }> = {},
): StillImageRoute {
  if (decision.status !== 'ready' || decision.modality === null) {
    return Object.freeze({ allowed: false, canonical: false, reason: 'modality-unresolved' });
  }
  if (decision.modality === 'motion-required') {
    if (request.previewRequested === true) {
      return Object.freeze({ allowed: true, canonical: false, reason: 'non-canonical-preview' });
    }
    return Object.freeze({ allowed: false, canonical: false, reason: 'motion-required' });
  }
  return Object.freeze({ allowed: true, canonical: true, reason: 'still-compatible' });
}
