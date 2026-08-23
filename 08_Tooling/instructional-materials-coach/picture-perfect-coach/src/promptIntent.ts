import {
  CAPTURE_BLOCKER_REASONS,
  bindCaptureEvidence,
  boundEvidenceSupportsClaims,
  type BoundScreenEvidence,
  type CaptureBlockerReason,
  type CaptureEvidenceBundle,
} from './captureEvidence';
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
  ...CAPTURE_BLOCKER_REASONS,
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
   * Role-preserving screen evidence bound by PPUX-F2. `action` is before-state
   * evidence and `result` is after-state evidence. A combined frame may require
   * both; the roles are never flattened into one opaque reference.
   */
  capturedScreenEvidence: BoundScreenEvidence | null;
  captureBlockerReasons: readonly CaptureBlockerReason[];
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
const CAPTURE_BASE_DIRECTIVE =
  'Use only the approved captured screen evidence as the base visual. Do not redraw, imitate, reconstruct, or invent any software interface content.';

/** Teacher-facing explanation for each machine-readable blocker reason. */
export function explainBlocker(reason: BlockerReason): string {
  switch (reason) {
    case BLOCKER_REASONS.visualEvidenceMissing:
      return 'This frame shows the real software interface, so it needs approved screen evidence for the required state. Picture Perfect will not generate a stand-in interface.';
    case BLOCKER_REASONS.uiClaimUnsupported:
      return 'This frame asks for interface text that the approved evidence does not support.';
    case BLOCKER_REASONS.uiClaimNotStateLocal:
      return 'This frame asks for interface text that was recorded during a different step, which does not prove it was on screen here.';
    case BLOCKER_REASONS.uiClaimNotCoVisible:
      return 'The approved recording never observed these details together on one screen, and no bound screenshot proves co-visibility.';
    case BLOCKER_REASONS.uiClaimIdentityMismatch:
      return 'Evidence for this frame does not match the recorded action it claims to come from.';
    case BLOCKER_REASONS.applicationIdentityMissing:
      return 'Approved evidence did not establish which application this step belongs to.';
    case BLOCKER_REASONS.specificationIncomplete:
      return 'Required authoring content for this frame is missing.';
    case BLOCKER_REASONS.captureStatusInvalid:
      return 'Capture evidence is not in the valid preflight state, so it cannot authorize a screen-backed frame.';
    case BLOCKER_REASONS.captureRecordingMismatch:
      return 'The captured screen evidence belongs to a different recording and is stale for this reviewed tutorial.';
    case BLOCKER_REASONS.captureActionIdentityMismatch:
      return 'The capture action fingerprint does not match the reviewed action identity.';
    case BLOCKER_REASONS.captureScreenStateMissing:
      return 'The required before-state or after-state screenshot is not available as approved evidence.';
    case BLOCKER_REASONS.captureAssetIneligible:
      return 'The stored screenshot is not eligible under the existing ArtifactManifest and visual-asset compatibility evidence.';
    case BLOCKER_REASONS.capturePrivacyUnresolved:
      return 'The stored screenshot still has unresolved privacy evidence and cannot become Ready.';
    case BLOCKER_REASONS.captureStale:
      return 'The stored screenshot compatibility evidence is stale and must be reverified before use.';
    case BLOCKER_REASONS.captureClaimsNotCoVisible:
      return 'No single approved screenshot for the required state supports all interface claims in this frame.';
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
export function effectiveUiRequests(spec: Pick<VisualSpecification, 'requestedUiDetails' | 'mustShow' | 'evidence'>): string[] {
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

  const requiresScreenFidelity = derivesScreenFidelity(spec, spec.requiresScreenFidelity);
  for (const reason of spec.captureBlockerReasons) push(reason);

  if (!spec.application.trim()) push(BLOCKER_REASONS.applicationIdentityMissing);
  if (!spec.targetState.trim() || spec.mustShow.length === 0 || spec.provenance.length === 0) {
    push(BLOCKER_REASONS.specificationIncomplete);
  }
  if (requiresScreenFidelity && !spec.applicationContext.trim()) {
    push(BLOCKER_REASONS.specificationIncomplete);
  }

  const fingerprintByIndex = new Map(
    spec.evidence.actionIdentity.map((item) => [item.sourceIndex, item.sourceFingerprint]),
  );
  for (const claim of spec.evidence.stateLocalClaims) {
    if (fingerprintByIndex.get(claim.sourceIndex) !== claim.sourceFingerprint) {
      push(BLOCKER_REASONS.uiClaimIdentityMismatch);
    }
  }

  const requests = effectiveUiRequests(spec);
  const captureSupports = requiresScreenFidelity &&
    boundEvidenceSupportsClaims(spec.capturedScreenEvidence, spec.imageState, requests);

  if (!captureSupports) {
    const observedAnywhere = new Set(spec.evidence.recordingClaimTexts);
    const observedHere = new Set(spec.evidence.stateLocalClaims.map((claim) => claim.text));
    for (const request of requests) {
      if (!observedAnywhere.has(request)) push(BLOCKER_REASONS.uiClaimUnsupported);
      else if (!observedHere.has(request)) push(BLOCKER_REASONS.uiClaimNotStateLocal);
    }

    const allLocal = requests.length > 0 && requests.every((request) => observedHere.has(request));
    if (requests.length > 1 && allLocal && coVisibleIndexes(spec.evidence.stateLocalClaims, requests).length === 0) {
      push(BLOCKER_REASONS.uiClaimNotCoVisible);
    }
  }

  if (requiresScreenFidelity && spec.capturedScreenEvidence === null) {
    push(BLOCKER_REASONS.visualEvidenceMissing);
  }
  return reasons;
}

function captureReferences(evidence: BoundScreenEvidence): string[] {
  return [evidence.action, evidence.result]
    .filter((state): state is NonNullable<typeof state> => state !== null)
    .map((state) => `${state.role}:${state.asset_reference.stable_reference}`);
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

  const prompt = spec.requiresScreenFidelity && spec.capturedScreenEvidence
    ? [
        `Prepare an instructional presentation visual for the ${spec.application} workflow from approved captured screen evidence.`,
        CAPTURE_BASE_DIRECTIVE,
        `Capture references: ${captureReferences(spec.capturedScreenEvidence).join('; ')}.`,
        `Purpose: ${spec.imagePurpose}`,
        `Image state: ${spec.imageState}.`,
        `Target state: ${spec.targetState}`,
        `Must show: ${spec.mustShow.join('; ')}.`,
        spec.mustNotShow.length ? `Must not show: ${spec.mustNotShow.join('; ')}.` : '',
        `Leave annotation space: ${spec.annotationSpace}.`,
        'Do not add controls, labels, locations, states, or workflow steps that are absent from the approved capture evidence.',
      ].filter(Boolean).join(' ')
    : [
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
    if (!card.capturedScreenEvidence) errors.push('a software-interface frame cannot be ready without approved capture evidence');
    if (!card.portablePrompt.includes('approved captured screen evidence')) errors.push('screen-backed prompt lost capture-evidence boundary');
    if (!card.portablePrompt.includes(CAPTURE_BASE_DIRECTIVE)) errors.push('screen-backed prompt lost non-reconstruction boundary');
    if (card.capturedScreenEvidence) {
      for (const reference of captureReferences(card.capturedScreenEvidence)) {
        if (!card.portablePrompt.includes(reference)) errors.push(`screen-backed prompt lost capture reference: ${reference}`);
      }
    }
  } else if (!card.portablePrompt.includes(NON_RECONSTRUCTION_DIRECTIVE)) {
    errors.push('portable prompt lost the non-reconstruction directive');
  }
  if (!card.portablePrompt.includes(card.application)) errors.push('portable prompt lost modeled application identity');
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

export function projectReviewedStepToVisualSpecification(
  step: ReviewedStepProjection,
  authoring: PromptAuthoringInput,
  tutorial: ReviewedTutorialProjection,
  captureBundle: CaptureEvidenceBundle | null = null,
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
  const requiresScreenFidelity = derivesScreenFidelity(base, authoring.screenFidelityRequired === true);
  const requests = effectiveUiRequests(base);
  const binding = requiresScreenFidelity
    ? bindCaptureEvidence(step, authoring.imageState, requests, captureBundle)
    : { evidence: null, blocker_reasons: [] as CaptureBlockerReason[] };
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
    requiresScreenFidelity,
    capturedScreenEvidence: binding.evidence,
    captureBlockerReasons: binding.blocker_reasons,
    evidence,
    uncertainty: authoring.uncertainty,
  };
}

export function projectReviewedTutorialToPromptCards(
  tutorial: ReviewedTutorialProjection,
  authoringByStepId: ReadonlyMap<string, PromptAuthoringInput>,
  captureBundle: CaptureEvidenceBundle | null = null,
): PromptCardModel[] {
  const cards: PromptCardModel[] = [];
  for (const step of tutorial.retained_steps) {
    const authoring = authoringByStepId.get(step.review_step_id);
    if (!authoring) continue;
    cards.push(buildPortablePrompt(projectReviewedStepToVisualSpecification(step, authoring, tutorial, captureBundle)));
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
  if (source.requiresScreenFidelity && !adaptedPrompt.includes(CAPTURE_BASE_DIRECTIVE)) {
    errors.push('provider adapter removed capture non-reconstruction boundary');
  }
  return errors;
}
