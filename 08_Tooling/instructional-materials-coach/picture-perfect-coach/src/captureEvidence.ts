import type { ReviewedStepProjection } from './types';

export type CaptureStatus = 'valid' | 'invalid' | 'blocked' | 'stale' | 'manual-review-required';
export type CaptureImageState = 'action' | 'result' | 'action+result';
export type ScreenshotRole = 'before' | 'after';

export const CAPTURE_BLOCKER_REASONS = {
  captureStatusInvalid: 'capture-status-invalid',
  captureRecordingMismatch: 'capture-recording-mismatch',
  captureActionIdentityMismatch: 'capture-action-identity-mismatch',
  captureScreenStateMissing: 'capture-screen-state-missing',
  captureAssetIneligible: 'capture-asset-ineligible',
  capturePrivacyUnresolved: 'capture-privacy-unresolved',
  captureStale: 'capture-stale',
  captureClaimsNotCoVisible: 'capture-claims-not-co-visible',
} as const;

export type CaptureBlockerReason = (typeof CAPTURE_BLOCKER_REASONS)[keyof typeof CAPTURE_BLOCKER_REASONS];

export type TargetGeometry = Readonly<{
  target_x: number;
  target_y: number;
  target_width: number;
  target_height: number;
}>;

export type CaptureAction = Readonly<{
  source_index: number;
  source_fingerprint: string;
  target_geometry: TargetGeometry | null;
  screenshot_before: string | null;
  screenshot_after: string | null;
}>;

export type SoftwareTutorialCapture = Readonly<{
  format_version: 'software-tutorial-capture-v1';
  capture_id: string;
  source: Readonly<{ recording_sha256: string }>;
  actions: readonly CaptureAction[];
}>;

export type ManifestReference = Readonly<{
  manifest_id: string;
  record_revision: number;
  fingerprint: string;
  verified_at: string;
  external_file_id: string;
}>;

export type AssetReference = Readonly<{
  asset_id: string;
  stable_reference: string;
  content_fingerprint: string;
}>;

/**
 * Package-local projection of already-validated ArtifactManifest and
 * curriculum-visual-asset-compatibility-v2 evidence. It is not a second asset
 * record or schema: identity remains owned by manifest_reference/asset_reference,
 * and interface suitability remains owned by the compatibility classification.
 */
export type ApprovedScreenshotEvidence = Readonly<{
  source_index: number;
  source_fingerprint: string;
  screenshot_role: ScreenshotRole;
  screenshot_reference: string;
  visible_ui_claims: readonly string[];
  manifest_reference: ManifestReference;
  asset_reference: AssetReference;
  artifact_manifest: Readonly<{
    contract_version: 'curriculum-artifact-manifest-v1';
    privacy_resolved: boolean;
    rights_state: string;
    classroom_readiness: string;
  }>;
  compatibility: Readonly<{
    contract_version: 'curriculum-visual-asset-compatibility-v2';
    classification: string;
    medium: string;
    representation_class: string;
    stale: boolean;
  }>;
}>;

export type CaptureEvidenceBundle = Readonly<{
  status: CaptureStatus;
  capture: SoftwareTutorialCapture | null;
  approved_screenshots: readonly ApprovedScreenshotEvidence[];
}>;

export type BoundScreenState = Readonly<{
  role: 'action' | 'result';
  source_index: number;
  source_fingerprint: string;
  screenshot_reference: string;
  visible_ui_claims: readonly string[];
  manifest_reference: ManifestReference;
  asset_reference: AssetReference;
  target_geometry: TargetGeometry | null;
}>;

export type BoundScreenEvidence = Readonly<{
  action: BoundScreenState | null;
  result: BoundScreenState | null;
}>;

export type CaptureBindingResult = Readonly<{
  evidence: BoundScreenEvidence | null;
  blocker_reasons: readonly CaptureBlockerReason[];
}>;

const CLEARED_RIGHTS = new Set(['cleared-internal', 'licensed', 'public-domain', 'permission-documented']);

function requiredRoles(imageState: CaptureImageState): readonly ScreenshotRole[] {
  if (imageState === 'action') return ['before'];
  if (imageState === 'result') return ['after'];
  return ['before', 'after'];
}

function uniqueSorted(values: readonly string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}

function screenshotFor(action: CaptureAction, role: ScreenshotRole): string | null {
  return role === 'before' ? action.screenshot_before : action.screenshot_after;
}

function assetBlockers(approval: ApprovedScreenshotEvidence): CaptureBlockerReason[] {
  const reasons: CaptureBlockerReason[] = [];
  if (!approval.artifact_manifest.privacy_resolved) reasons.push(CAPTURE_BLOCKER_REASONS.capturePrivacyUnresolved);
  if (!CLEARED_RIGHTS.has(approval.artifact_manifest.rights_state)) reasons.push(CAPTURE_BLOCKER_REASONS.captureAssetIneligible);
  if (approval.artifact_manifest.classroom_readiness !== 'ready') reasons.push(CAPTURE_BLOCKER_REASONS.captureAssetIneligible);
  if (approval.compatibility.stale) reasons.push(CAPTURE_BLOCKER_REASONS.captureStale);
  if (
    approval.compatibility.contract_version !== 'curriculum-visual-asset-compatibility-v2' ||
    approval.compatibility.classification !== 'eligible' ||
    approval.compatibility.medium !== 'screen-capture' ||
    approval.compatibility.representation_class !== 'interface-capture'
  ) reasons.push(CAPTURE_BLOCKER_REASONS.captureAssetIneligible);
  return [...new Set(reasons)];
}

function roleName(role: ScreenshotRole): 'action' | 'result' {
  return role === 'before' ? 'action' : 'result';
}

function pickRole(
  step: ReviewedStepProjection,
  capture: SoftwareTutorialCapture,
  bundle: CaptureEvidenceBundle,
  role: ScreenshotRole,
  requestedUiClaims: readonly string[],
): { state: BoundScreenState | null; reasons: CaptureBlockerReason[] } {
  const identities = new Map(step.action_identity.map((identity) => [identity.sourceIndex, identity.sourceFingerprint]));
  const candidates: Array<{ approval: ApprovedScreenshotEvidence; action: CaptureAction }> = [];
  const observedReasons: CaptureBlockerReason[] = [];

  for (const approval of bundle.approved_screenshots) {
    const expectedFingerprint = identities.get(approval.source_index);
    if (!expectedFingerprint || expectedFingerprint !== approval.source_fingerprint) continue;
    const action = capture.actions.find((item) => item.source_index === approval.source_index);
    if (!action || action.source_fingerprint !== expectedFingerprint) continue;
    const expectedScreenshot = screenshotFor(action, role);
    if (!expectedScreenshot || approval.screenshot_role !== role || approval.screenshot_reference !== expectedScreenshot) continue;

    const blockers = assetBlockers(approval);
    if (blockers.length > 0) {
      observedReasons.push(...blockers);
      continue;
    }
    candidates.push({ approval, action });
  }

  const requested = uniqueSorted(requestedUiClaims);
  const supporting = candidates.filter(({ approval }) => {
    const visible = new Set(approval.visible_ui_claims);
    return requested.every((claim) => visible.has(claim));
  });

  if (supporting.length === 0) {
    if (candidates.length > 0 && requested.length > 0) observedReasons.push(CAPTURE_BLOCKER_REASONS.captureClaimsNotCoVisible);
    if (candidates.length === 0 && observedReasons.length === 0) observedReasons.push(CAPTURE_BLOCKER_REASONS.captureScreenStateMissing);
    return { state: null, reasons: [...new Set(observedReasons)] };
  }

  supporting.sort((left, right) =>
    left.approval.source_index - right.approval.source_index ||
    left.approval.asset_reference.asset_id.localeCompare(right.approval.asset_reference.asset_id),
  );
  const { approval, action } = supporting[0];
  return {
    state: {
      role: roleName(role),
      source_index: action.source_index,
      source_fingerprint: action.source_fingerprint,
      screenshot_reference: approval.screenshot_reference,
      visible_ui_claims: uniqueSorted(approval.visible_ui_claims),
      manifest_reference: approval.manifest_reference,
      asset_reference: approval.asset_reference,
      target_geometry: action.target_geometry,
    },
    reasons: [],
  };
}

/**
 * Bind one reviewed frame to software-tutorial-capture-v1 without changing the
 * capture contract. Every reviewed action identity must exist byte-for-byte in the
 * capture. Each required screen-state role is then satisfied by exactly one
 * approved screenshot from one action; claims and geometry are never unioned across
 * actions or combined reviewed steps.
 */
export function bindCaptureEvidence(
  step: ReviewedStepProjection,
  imageState: CaptureImageState,
  requestedUiClaims: readonly string[],
  bundle: CaptureEvidenceBundle | null,
): CaptureBindingResult {
  if (!bundle) return { evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureScreenStateMissing] };
  if (bundle.status !== 'valid' || bundle.capture === null) {
    return { evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureStatusInvalid] };
  }
  const capture = bundle.capture;
  if (capture.format_version !== 'software-tutorial-capture-v1' || capture.source.recording_sha256 !== step.recording_sha256) {
    return { evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureRecordingMismatch] };
  }

  for (const identity of step.action_identity) {
    const action = capture.actions.find((item) => item.source_index === identity.sourceIndex);
    if (!action || action.source_fingerprint !== identity.sourceFingerprint) {
      return { evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureActionIdentityMismatch] };
    }
  }

  const states: { action: BoundScreenState | null; result: BoundScreenState | null } = { action: null, result: null };
  const reasons: CaptureBlockerReason[] = [];
  for (const role of requiredRoles(imageState)) {
    const bound = pickRole(step, capture, bundle, role, requestedUiClaims);
    reasons.push(...bound.reasons);
    states[roleName(role)] = bound.state;
  }
  const uniqueReasons = [...new Set(reasons)];
  if (uniqueReasons.length > 0) return { evidence: null, blocker_reasons: uniqueReasons };
  return { evidence: states, blocker_reasons: [] };
}

export function boundEvidenceSupportsClaims(
  evidence: BoundScreenEvidence | null,
  imageState: CaptureImageState,
  requestedUiClaims: readonly string[],
): boolean {
  if (!evidence) return false;
  const requested = uniqueSorted(requestedUiClaims);
  const states = imageState === 'action' ? [evidence.action]
    : imageState === 'result' ? [evidence.result]
      : [evidence.action, evidence.result];
  return states.every((state) => state !== null && requested.every((claim) => state.visible_ui_claims.includes(claim)));
}
