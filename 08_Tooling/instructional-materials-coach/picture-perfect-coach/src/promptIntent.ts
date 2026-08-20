import { coVisibleIndexes, frameUiEvidence, type FrameUiEvidence } from './uiEvidence';
import type { ReviewedStepProjection, ReviewedTutorialProjection } from './types';

export type ImageState = 'action' | 'result' | 'action+result';

/**
 * Machine-readable blocker reasons. Card runtime state stays binary
 * (`ready | blocked`); nuance is expressed here rather than as new states.
 */
export const BLOCKER_REASONS = {
  applicationIdentityMissing: 'application-identity-missing',
  visualEvidenceMissing: 'visual-evidence-missing',
  uiClaimUnsupported: 'ui-claim-unsupported',
  uiClaimNotStateLocal: 'ui-claim-not-state-local',
  uiClaimNotCoVisible: 'ui-claim-not-co-visible',
  uiClaimIdentityMismatch: 'ui-claim-identity-mismatch',
  specificationIncomplete: 'specification-incomplete',
} as const;

export type BlockerReason = (typeof BLOCKER_REASONS)[keyof typeof BLOCKER_REASONS];

export type VisualSpecification = {
  stepNumber: number;
  imagePurpose: string;
  imageState: ImageState;
  application: string;
  applicationContext: string;
  targetState: string;
  mustShow: readonly string[];
  mustNotShow: readonly string[];
  annotationSpace: string;
  provenance: readonly string[];
  requestedUiDetails: readonly string[];
  /**
   * Derived, never authored: true when the frame asks for any interface text,
   * control, location, or application context. Authors may raise this and can
   * never lower it, so a frame cannot be relabelled out of the gate.
   */
  requiresScreenFidelity: boolean;
  /**
   * Approved captured screen evidence backing this frame. Always `null` in
   * PPUX-F1 — binding real capture evidence is PPUX-F2 (#1294).
   */
  capturedScreenRef: string | null;
  evidence: FrameUiEvidence;
  uncertainty?: string;
};

export type PromptCardModel = VisualSpecification & {
  portablePrompt: string;
  status: 'ready' | 'blocked';
  blocker?: string;
  blockerReasons: readonly BlockerReason[];
};

const KNOWN_WRONG_APPS = ['Canva', 'Figma', 'Photoshop'];
const PROVIDER_SPECIFIC_MARKERS = ['Midjourney', 'Gemini', 'Adobe Firefly', 'ChatGPT image generation', '--ar ', '--stylize '];

const NON_RECONSTRUCTION_DIRECTIVE =
  'Do not depict, imitate, or reconstruct the real software interface; this is a non-interface instructional visual.';

/** Teacher-facing explanation for each machine-readable blocker reason. */
export function explainBlocker(reason: BlockerReason): string {
  switch (reason) {
    case BLOCKER_REASONS.visualEvidenceMissing:
      return 'This frame shows the real software interface, so it needs an approved screen capture of that exact step. No capture evidence is bound yet, so Picture Perfect will not generate a stand-in interface.';
    case BLOCKER_REASONS.uiClaimUnsupported:
      return 'This frame asks for interface text that the approved recording never shows.';
    case BLOCKER_REASONS.uiClaimNotStateLocal:
      return 'This frame asks for interface text that was recorded during a different step, which does not prove it was on screen here.';
    case BLOCKER_REASONS.uiClaimNotCoVisible:
      return 'The approved recording never observed these details together on one screen, so they cannot be shown as if they were.';
    case BLOCKER_REASONS.uiClaimIdentityMismatch:
      return 'Evidence for this frame does not match the recorded action it claims to come from.';
    case BLOCKER_REASONS.applicationIdentityMissing:
      return 'Approved evidence did not establish which application this step belongs to.';
    case BLOCKER_REASONS.specificationIncomplete:
      return 'Required authoring content for this frame is missing.';
    default:
      return 'This frame is blocked.';
  }
}

/**
 * UI texts this frame effectively claims.
 *
 * Requested details are explicit claims. A `mustShow` entry that exactly matches
 * observed recording text is also a claim — otherwise an author could move an
 * interface label from `requestedUiDetails` into `mustShow` to slip past the gate.
 */
export function effectiveUiRequests(spec: VisualSpecification): string[] {
  const observed = new Set(spec.evidence.recordingClaimTexts);
  const fromMustShow = spec.mustShow.filter((item) => observed.has(item));
  return [...new Set([...spec.requestedUiDetails, ...fromMustShow])];
}

/** Derived software-interface determination. Authors may only raise it. */
export function derivesScreenFidelity(
  spec: Pick<VisualSpecification, 'mustShow' | 'requestedUiDetails' | 'applicationContext' | 'evidence'>,
  authorRaised = false,
): boolean {
  const observed = new Set(spec.evidence.recordingClaimTexts);
  const claimsInterfaceText =
    spec.requestedUiDetails.length > 0 || spec.mustShow.some((item) => observed.has(item));
  return authorRaised || claimsInterfaceText || spec.applicationContext.trim().length > 0;
}

export function validateVisualSpecification(spec: VisualSpecification): BlockerReason[] {
  const reasons: BlockerReason[] = [];
  const push = (reason: BlockerReason) => {
    if (!reasons.includes(reason)) reasons.push(reason);
  };

  if (!spec.application.trim()) push(BLOCKER_REASONS.applicationIdentityMissing);
  if (!spec.targetState.trim() || spec.mustShow.length === 0 || spec.provenance.length === 0) {
    push(BLOCKER_REASONS.specificationIncomplete);
  }
  // Application context describes surrounding interface, so an interface frame must
  // state it; a non-interface frame must not smuggle it in.
  if (spec.requiresScreenFidelity && !spec.applicationContext.trim()) {
    push(BLOCKER_REASONS.specificationIncomplete);
  }

  // Action identity: a claim must match the fingerprint recorded for its own index.
  const fingerprintByIndex = new Map(
    spec.evidence.actionIdentity.map((item) => [item.sourceIndex, item.sourceFingerprint]),
  );
  for (const claim of spec.evidence.stateLocalClaims) {
    if (fingerprintByIndex.get(claim.sourceIndex) !== claim.sourceFingerprint) {
      push(BLOCKER_REASONS.uiClaimIdentityMismatch);
    }
  }

  const requests = effectiveUiRequests(spec);
  const observedAnywhere = new Set(spec.evidence.recordingClaimTexts);
  const observedHere = new Set(spec.evidence.stateLocalClaims.map((claim) => claim.text));
  for (const request of requests) {
    if (!observedAnywhere.has(request)) push(BLOCKER_REASONS.uiClaimUnsupported);
    else if (!observedHere.has(request)) push(BLOCKER_REASONS.uiClaimNotStateLocal);
  }

  // Two texts observed at different states are not proven to share one screen.
  const allLocal = requests.length > 0 && requests.every((request) => observedHere.has(request));
  if (requests.length > 1 && allLocal && coVisibleIndexes(spec.evidence.stateLocalClaims, requests).length === 0) {
    push(BLOCKER_REASONS.uiClaimNotCoVisible);
  }

  if (spec.requiresScreenFidelity && spec.capturedScreenRef === null) {
    push(BLOCKER_REASONS.visualEvidenceMissing);
  }
  return reasons;
}

export function buildPortablePrompt(spec: VisualSpecification): PromptCardModel {
  const reasons = validateVisualSpecification(spec);
  if (reasons.length > 0) {
    return {
      ...spec,
      portablePrompt: '',
      status: 'blocked',
      blocker: reasons.map(explainBlocker).join(' '),
      blockerReasons: reasons,
    };
  }

  // Only non-interface frames can reach this point: an interface frame without
  // approved capture evidence is always blocked above, so no prompt produced here
  // can ever be a stand-in for a real software screen.
  const prompt = [
    `Create an instructional visual for the ${spec.application} workflow.`,
    NON_RECONSTRUCTION_DIRECTIVE,
    `Purpose: ${spec.imagePurpose}`,
    `Image state: ${spec.imageState}.`,
    `Target state: ${spec.targetState}`,
    `Must show: ${spec.mustShow.join('; ')}.`,
    spec.mustNotShow.length ? `Must not show: ${spec.mustNotShow.join('; ')}.` : '',
    `Leave annotation space: ${spec.annotationSpace}.`,
    'Do not invent controls, labels, locations, states, or workflow steps.',
  ].filter(Boolean).join(' ');

  return { ...spec, portablePrompt: prompt, status: 'ready', blockerReasons: [] };
}

export function validateApplicationFidelity(card: PromptCardModel): string[] {
  if (card.status === 'blocked') return [...card.blockerReasons];
  const errors: string[] = [];
  if (card.requiresScreenFidelity) {
    errors.push('a software-interface frame cannot be ready without approved capture evidence');
  }
  if (!card.portablePrompt.includes(card.application)) errors.push('portable prompt lost modeled application identity');
  if (!card.portablePrompt.includes(NON_RECONSTRUCTION_DIRECTIVE)) {
    errors.push('portable prompt lost the non-reconstruction directive');
  }
  if (/\b(?:screenshot|user interface|the interface of)\b/i.test(card.portablePrompt)) {
    errors.push('portable prompt requests software-interface depiction without capture evidence');
  }
  for (const wrongApp of KNOWN_WRONG_APPS) {
    if (wrongApp !== card.application && card.portablePrompt.includes(`depict ${wrongApp}`)) {
      errors.push(`portable prompt substituted wrong application: ${wrongApp}`);
    }
  }
  if (!card.portablePrompt.includes(card.targetState)) errors.push('portable prompt lost target state');
  for (const item of card.mustShow) {
    if (!card.portablePrompt.includes(item)) errors.push(`portable prompt lost must-show evidence: ${item}`);
  }
  for (const marker of PROVIDER_SPECIFIC_MARKERS) {
    if (card.portablePrompt.includes(marker)) errors.push(`canonical prompt contains provider-specific syntax: ${marker}`);
  }
  return errors;
}

/**
 * Teacher/approved image-framing content for one reviewed step.
 *
 * This is authoring content only — what to show, why, and where. It can no longer
 * declare which UI details evidence supports; that is derived from the recording.
 * `screenFidelityRequired` may only raise the software-interface determination.
 */
export type PromptAuthoringInput = {
  imagePurpose: string;
  imageState: ImageState;
  applicationContext: string;
  targetState: string;
  mustShow: readonly string[];
  mustNotShow: readonly string[];
  annotationSpace: string;
  requestedUiDetails: readonly string[];
  screenFidelityRequired?: true;
  uncertainty?: string;
};

/**
 * Projects one Stage-3 reviewed step plus its approved authoring content into a
 * bounded Stage-4 VisualSpecification. Application identity comes only from
 * `step.modeled_application`. UI evidence comes only from the recording, narrowed
 * to this step's own source indexes.
 */
export function projectReviewedStepToVisualSpecification(
  step: ReviewedStepProjection,
  authoring: PromptAuthoringInput,
  tutorial: ReviewedTutorialProjection,
): VisualSpecification {
  const provenance = [
    `recording:${step.recording_id}`,
    `recording_sha256:${step.recording_sha256}`,
    ...step.source_step_ids.map((id) => `source_step:${id}`),
    ...step.semantic_action_ids.map((id) => `semantic_action:${id}`),
  ];
  const evidence = frameUiEvidence(tutorial.recording_evidence, step.source_indexes);
  const base = {
    applicationContext: authoring.applicationContext,
    mustShow: authoring.mustShow,
    requestedUiDetails: authoring.requestedUiDetails,
    evidence,
  };
  return {
    stepNumber: step.sequence,
    imagePurpose: authoring.imagePurpose,
    imageState: authoring.imageState,
    application: step.modeled_application ?? '',
    applicationContext: authoring.applicationContext,
    targetState: authoring.targetState,
    mustShow: authoring.mustShow,
    mustNotShow: authoring.mustNotShow,
    annotationSpace: authoring.annotationSpace,
    provenance,
    requestedUiDetails: authoring.requestedUiDetails,
    requiresScreenFidelity: derivesScreenFidelity(base, authoring.screenFidelityRequired === true),
    capturedScreenRef: null,
    evidence,
    uncertainty: authoring.uncertainty,
  };
}

/**
 * Projects an approved ReviewedTutorialProjection into Stage-4 prompt cards.
 * A reviewed step with no matching authoring entry is skipped (not invented).
 * `execution_authorized` is never read or propagated.
 */
export function projectReviewedTutorialToPromptCards(
  tutorial: ReviewedTutorialProjection,
  authoringByStepId: ReadonlyMap<string, PromptAuthoringInput>,
): PromptCardModel[] {
  const cards: PromptCardModel[] = [];
  for (const step of tutorial.retained_steps) {
    const authoring = authoringByStepId.get(step.review_step_id);
    if (!authoring) continue;
    cards.push(buildPortablePrompt(projectReviewedStepToVisualSpecification(step, authoring, tutorial)));
  }
  return cards;
}

export function assertProviderAdapterPreservesIntent(source: PromptCardModel, adaptedPrompt: string): string[] {
  if (source.status === 'blocked') return ['blocked intent cannot be adapted'];
  const errors: string[] = [];
  if (!adaptedPrompt.includes(source.application)) errors.push('provider adapter removed application identity');
  if (!adaptedPrompt.includes(source.targetState)) errors.push('provider adapter removed target state');
  for (const item of source.mustShow) {
    if (!adaptedPrompt.includes(item)) errors.push(`provider adapter removed must-show evidence: ${item}`);
  }
  return errors;
}
