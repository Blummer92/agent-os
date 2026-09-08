import {
  CAPTURE_BLOCKER_REASONS,
  bindCaptureEvidence,
  type BoundScreenEvidence,
  type CaptureEvidenceBundle,
  type CaptureImageState,
} from './captureEvidence';
import type { ReviewedStepProjection } from './types';

export type CaptureReuseDisposition =
  | 'REUSE_EXISTING_CAPTURE'
  | 'CAPTURE_REQUIRED'
  | 'MANUAL_REVIEW_REQUIRED';

export const CAPTURE_REUSE_REASONS = {
  exactCurrentEvidence: 'exact-current-evidence',
  missingEvidence: 'missing-evidence',
  recordingMismatch: 'recording-mismatch',
  actionIdentityMismatch: 'action-identity-mismatch',
  screenStateMissing: 'screen-state-missing',
  staleEvidence: 'stale-evidence',
  claimsNotCoVisible: 'claims-not-co-visible',
  privacyUnresolved: 'privacy-unresolved',
  assetEligibilityUnresolved: 'asset-eligibility-unresolved',
  applicationIdentityMissing: 'application-identity-missing',
  applicationIdentityConflict: 'application-identity-conflict',
  requiredTargetGeometryMissing: 'required-target-geometry-missing',
  captureStatusInvalid: 'capture-status-invalid',
  manualReviewStatus: 'manual-review-status',
} as const;

export type CaptureReuseReason = (typeof CAPTURE_REUSE_REASONS)[keyof typeof CAPTURE_REUSE_REASONS];

export type CaptureReuseRequirement = Readonly<{
  logical_request_id: string;
  expected_application: string;
  image_state: CaptureImageState;
  requested_ui_claims: readonly string[];
  require_target_geometry: boolean;
}>;

export type ReusedStateIdentity = Readonly<{
  role: 'action' | 'result';
  source_index: number;
  source_fingerprint: string;
  screenshot_reference: string;
  asset_id: string;
  stable_ref: string;
  content_fingerprint: string;
}>;

export type ReusedEvidenceIdentity = Readonly<{
  capture_id: string;
  recording_sha256: string;
  states: readonly ReusedStateIdentity[];
}>;

export type CaptureReuseObservability = Readonly<{
  browser_runs_requested: 0 | 1;
  browser_runs_launched: 0;
  existing_capture_reuses: 0 | 1;
  duplicate_runs_avoided: 0;
}>;

export type CaptureReuseDecision = Readonly<{
  logical_request_id: string;
  disposition: CaptureReuseDisposition;
  reason_codes: readonly CaptureReuseReason[];
  reused_evidence: ReusedEvidenceIdentity | null;
  observability: CaptureReuseObservability;
  picture_perfect_ready: false;
  classroom_ready: false;
  publication_authorized: false;
  provider_execution_authorized: false;
  external_write_authorized: false;
}>;

function baseDecision(
  requirement: CaptureReuseRequirement,
  disposition: CaptureReuseDisposition,
  reasonCodes: readonly CaptureReuseReason[],
  reusedEvidence: ReusedEvidenceIdentity | null,
): CaptureReuseDecision {
  return {
    logical_request_id: requirement.logical_request_id,
    disposition,
    reason_codes: [...new Set(reasonCodes)],
    reused_evidence: reusedEvidence,
    observability: {
      browser_runs_requested: disposition === 'CAPTURE_REQUIRED' ? 1 : 0,
      browser_runs_launched: 0,
      existing_capture_reuses: disposition === 'REUSE_EXISTING_CAPTURE' ? 1 : 0,
      duplicate_runs_avoided: 0,
    },
    picture_perfect_ready: false,
    classroom_ready: false,
    publication_authorized: false,
    provider_execution_authorized: false,
    external_write_authorized: false,
  };
}

function stateIdentities(evidence: BoundScreenEvidence): readonly ReusedStateIdentity[] {
  return [evidence.action, evidence.result]
    .filter((state): state is NonNullable<typeof state> => state !== null)
    .map((state) => ({
      role: state.role,
      source_index: state.source_index,
      source_fingerprint: state.source_fingerprint,
      screenshot_reference: state.screenshot_reference,
      asset_id: state.asset_reference.asset_id,
      stable_ref: state.asset_reference.stable_ref,
      content_fingerprint: state.asset_reference.content_fingerprint,
    }));
}

function missingRequiredGeometry(evidence: BoundScreenEvidence, imageState: CaptureImageState): boolean {
  const states = imageState === 'action'
    ? [evidence.action]
    : imageState === 'result'
      ? [evidence.result]
      : [evidence.action, evidence.result];
  return states.some((state) => state === null || state.target_geometry === null);
}

function mapBindingReasons(
  blockerReasons: readonly string[],
  status: string,
): { disposition: CaptureReuseDisposition; reasons: CaptureReuseReason[] } {
  const manualReasons: CaptureReuseReason[] = [];
  if (blockerReasons.includes(CAPTURE_BLOCKER_REASONS.capturePrivacyUnresolved)) {
    manualReasons.push(CAPTURE_REUSE_REASONS.privacyUnresolved);
  }
  if (blockerReasons.includes(CAPTURE_BLOCKER_REASONS.captureAssetIneligible)) {
    manualReasons.push(CAPTURE_REUSE_REASONS.assetEligibilityUnresolved);
  }
  if (manualReasons.length > 0) {
    return { disposition: 'MANUAL_REVIEW_REQUIRED', reasons: manualReasons };
  }
  if (status === 'manual-review-required') {
    return { disposition: 'MANUAL_REVIEW_REQUIRED', reasons: [CAPTURE_REUSE_REASONS.manualReviewStatus] };
  }

  const reasons: CaptureReuseReason[] = [];
  if (blockerReasons.includes(CAPTURE_BLOCKER_REASONS.captureRecordingMismatch)) {
    reasons.push(CAPTURE_REUSE_REASONS.recordingMismatch);
  }
  if (blockerReasons.includes(CAPTURE_BLOCKER_REASONS.captureActionIdentityMismatch)) {
    reasons.push(CAPTURE_REUSE_REASONS.actionIdentityMismatch);
  }
  if (blockerReasons.includes(CAPTURE_BLOCKER_REASONS.captureScreenStateMissing)) {
    reasons.push(CAPTURE_REUSE_REASONS.screenStateMissing);
  }
  if (blockerReasons.includes(CAPTURE_BLOCKER_REASONS.captureStale)) {
    reasons.push(CAPTURE_REUSE_REASONS.staleEvidence);
  }
  if (blockerReasons.includes(CAPTURE_BLOCKER_REASONS.captureClaimsNotCoVisible)) {
    reasons.push(CAPTURE_REUSE_REASONS.claimsNotCoVisible);
  }
  if (blockerReasons.includes(CAPTURE_BLOCKER_REASONS.captureStatusInvalid)) {
    reasons.push(CAPTURE_REUSE_REASONS.captureStatusInvalid);
  }
  if (reasons.length === 0) reasons.push(CAPTURE_REUSE_REASONS.missingEvidence);
  return { disposition: 'CAPTURE_REQUIRED', reasons };
}

/**
 * Pure pre-capture routing decision for #2109.
 *
 * This function intentionally does not launch a browser, search for assets, mutate
 * evidence, or create a new identity/currentness model. It consumes the existing
 * PPUX capture-binding contract and returns only a routing disposition plus bounded
 * non-authorizing observability. #2100 remains the owner of live capture invocation.
 */
export function decideCaptureReuse(
  step: ReviewedStepProjection,
  requirement: CaptureReuseRequirement,
  bundle: CaptureEvidenceBundle | null,
): CaptureReuseDecision {
  if (!step.modeled_application) {
    return baseDecision(
      requirement,
      'MANUAL_REVIEW_REQUIRED',
      [CAPTURE_REUSE_REASONS.applicationIdentityMissing],
      null,
    );
  }
  if (step.modeled_application !== requirement.expected_application) {
    return baseDecision(
      requirement,
      'MANUAL_REVIEW_REQUIRED',
      [CAPTURE_REUSE_REASONS.applicationIdentityConflict],
      null,
    );
  }

  if (!bundle) {
    return baseDecision(requirement, 'CAPTURE_REQUIRED', [CAPTURE_REUSE_REASONS.missingEvidence], null);
  }
  if (bundle.status === 'manual-review-required') {
    return baseDecision(requirement, 'MANUAL_REVIEW_REQUIRED', [CAPTURE_REUSE_REASONS.manualReviewStatus], null);
  }

  const binding = bindCaptureEvidence(
    step,
    requirement.image_state,
    requirement.requested_ui_claims,
    bundle,
  );
  if (binding.status !== 'valid' || !binding.evidence || !bundle.capture) {
    const mapped = mapBindingReasons(binding.blocker_reasons, binding.status);
    return baseDecision(requirement, mapped.disposition, mapped.reasons, null);
  }

  if (requirement.require_target_geometry && missingRequiredGeometry(binding.evidence, requirement.image_state)) {
    return baseDecision(
      requirement,
      'CAPTURE_REQUIRED',
      [CAPTURE_REUSE_REASONS.requiredTargetGeometryMissing],
      null,
    );
  }

  return baseDecision(
    requirement,
    'REUSE_EXISTING_CAPTURE',
    [CAPTURE_REUSE_REASONS.exactCurrentEvidence],
    {
      capture_id: bundle.capture.capture_id,
      recording_sha256: bundle.capture.source.recording_sha256,
      states: stateIdentities(binding.evidence),
    },
  );
}
