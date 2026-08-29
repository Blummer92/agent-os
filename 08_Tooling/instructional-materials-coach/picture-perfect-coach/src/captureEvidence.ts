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

export type RgbaColor = readonly [number, number, number, number];

/**
 * Optional bounded target-style evidence (#1485). Captured only from the
 * already-resolved target handle in `capture/replay_capture.mjs` using a frozen
 * `getComputedStyle` allowlist. `rect_normalized` is `[x, y, width, height]`
 * normalized against the capture viewport -- the repository's one rectangle
 * ordering, shared with `TargetGeometry` and with `ReferenceRegion.rect` (in
 * `./visualReference`). Only the coordinate space differs: capture/viewport
 * here, sanitized derivative there, and nothing in this module converts one
 * space into the other.
 */
export type TargetStyleEvidence = Readonly<{
  rect_normalized: readonly [number, number, number, number];
  color_rgba: RgbaColor | null;
  background_rgba: RgbaColor | null;
  opacity: number | null;
  font_family: string | null;
  font_size_px: number | null;
  font_weight: number | null;
  font_style: string | null;
  line_height: string | null;
  letter_spacing: string | null;
  border_radius: string | null;
  background_image: string | null;
  box_shadow: string | null;
  text_shadow: string | null;
  transform: string | null;
}>;

export type CaptureActionV2 = CaptureAction & Readonly<{ target_style?: TargetStyleEvidence | null }>;

export type SoftwareTutorialCaptureV2 = Readonly<{
  format_version: 'software-tutorial-capture-v2';
  capture_id: string;
  source: Readonly<{ recording_sha256: string }>;
  actions: readonly CaptureActionV2[];
}>;

export type AnySoftwareTutorialCapture = SoftwareTutorialCapture | SoftwareTutorialCaptureV2;

export type ManifestReference = Readonly<{
  manifest_id: string;
  record_revision: number;
  fingerprint: string;
  verified_at: string;
  external_file_id: string;
}>;

export type AssetReference = Readonly<{
  asset_id: string;
  stable_ref: string;
  content_fingerprint: string;
}>;

export type ArtifactManifestAssetEvidence = Readonly<{
  contract_version: 'curriculum-artifact-manifest-v1';
  external_identity: Readonly<{ access_state: string }>;
  statuses: Readonly<{ classroom_readiness: string }>;
  asset: Readonly<{
    privacy_resolved: boolean;
    residual_privacy_risk: boolean;
    rights_classification: string;
    direct_use_status: string;
    replacement_required: boolean;
    transformations: readonly string[];
  }>;
}>;

export type VisualAssetCompatibilityEvidence = Readonly<{
  contract_version: 'curriculum-visual-asset-compatibility-v2';
  classification: string;
  cohesion_profile: Readonly<{
    medium: string;
    representation_class: string;
  }>;
  freshness: Readonly<{ stale: boolean }>;
}>;

export type ApprovedScreenshotEvidence = Readonly<{
  source_index: number;
  source_fingerprint: string;
  screenshot_role: ScreenshotRole;
  screenshot_reference: string;
  visible_ui_claims: readonly string[];
  manifest_reference: ManifestReference;
  asset_reference: AssetReference;
  artifact_manifest: ArtifactManifestAssetEvidence;
  compatibility: VisualAssetCompatibilityEvidence;
}>;

export type CaptureEvidenceBundle = Readonly<{
  status: CaptureStatus;
  capture: AnySoftwareTutorialCapture | null;
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
  target_style: TargetStyleEvidence | null;
}>;

export type BoundScreenEvidence = Readonly<{
  action: BoundScreenState | null;
  result: BoundScreenState | null;
}>;

export type CaptureBindingResult = Readonly<{
  status: CaptureStatus;
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
  const manifest = approval.artifact_manifest;
  const asset = manifest.asset;
  const compatibility = approval.compatibility;

  if (!asset.privacy_resolved || asset.residual_privacy_risk) {
    reasons.push(CAPTURE_BLOCKER_REASONS.capturePrivacyUnresolved);
  }
  if (
    manifest.contract_version !== 'curriculum-artifact-manifest-v1' ||
    manifest.external_identity.access_state !== 'verified' ||
    manifest.statuses.classroom_readiness !== 'ready' ||
    !CLEARED_RIGHTS.has(asset.rights_classification) ||
    asset.direct_use_status !== 'student-ready' ||
    asset.replacement_required
  ) reasons.push(CAPTURE_BLOCKER_REASONS.captureAssetIneligible);
  if (compatibility.freshness.stale) reasons.push(CAPTURE_BLOCKER_REASONS.captureStale);
  if (
    compatibility.contract_version !== 'curriculum-visual-asset-compatibility-v2' ||
    compatibility.classification !== 'eligible' ||
    compatibility.cohesion_profile.medium !== 'screen-capture' ||
    compatibility.cohesion_profile.representation_class !== 'interface-capture'
  ) reasons.push(CAPTURE_BLOCKER_REASONS.captureAssetIneligible);
  return [...new Set(reasons)];
}

function bindingStatus(reasons: readonly CaptureBlockerReason[]): CaptureStatus {
  if (
    reasons.includes(CAPTURE_BLOCKER_REASONS.captureRecordingMismatch) ||
    reasons.includes(CAPTURE_BLOCKER_REASONS.captureActionIdentityMismatch) ||
    reasons.includes(CAPTURE_BLOCKER_REASONS.captureStale)
  ) return 'stale';
  if (reasons.includes(CAPTURE_BLOCKER_REASONS.capturePrivacyUnresolved)) return 'manual-review-required';
  return 'blocked';
}

function roleName(role: ScreenshotRole): 'action' | 'result' {
  return role === 'before' ? 'action' : 'result';
}

function targetStyleOf(action: CaptureAction | CaptureActionV2): TargetStyleEvidence | null {
  return ('target_style' in action ? action.target_style : null) ?? null;
}

function pickRole(
  step: ReviewedStepProjection,
  capture: AnySoftwareTutorialCapture,
  bundle: CaptureEvidenceBundle,
  role: ScreenshotRole,
  requestedUiClaims: readonly string[],
): { state: BoundScreenState | null; reasons: CaptureBlockerReason[] } {
  const sourceIndexes = new Set(step.source_indexes);
  const identities = new Map(step.action_identity.map((identity) => [identity.sourceIndex, identity.sourceFingerprint]));
  const candidates: Array<{ approval: ApprovedScreenshotEvidence; action: CaptureAction | CaptureActionV2 }> = [];
  const observedReasons: CaptureBlockerReason[] = [];

  for (const approval of bundle.approved_screenshots) {
    if (!sourceIndexes.has(approval.source_index)) continue;
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
      target_style: targetStyleOf(action),
    },
    reasons: [],
  };
}

/**
 * Bind one reviewed frame to software-tutorial-capture-v1 without changing the
 * capture contract. Identity is the recording SHA plus a source index that belongs
 * to the reviewed step plus the exact action fingerprint. Each screen-state role is
 * satisfied by one approved screenshot; claims and geometry are never unioned.
 */
export function bindCaptureEvidence(
  step: ReviewedStepProjection,
  imageState: CaptureImageState,
  requestedUiClaims: readonly string[],
  bundle: CaptureEvidenceBundle | null,
): CaptureBindingResult {
  if (!bundle) {
    return { status: 'blocked', evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureScreenStateMissing] };
  }
  if (bundle.status !== 'valid' || bundle.capture === null) {
    const status = bundle.status === 'valid' ? 'invalid' : bundle.status;
    return { status, evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureStatusInvalid] };
  }
  const capture = bundle.capture;
  if (capture.format_version !== 'software-tutorial-capture-v1' && capture.format_version !== 'software-tutorial-capture-v2') {
    return { status: 'invalid', evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureStatusInvalid] };
  }
  if (capture.source.recording_sha256 !== step.recording_sha256) {
    return { status: 'stale', evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureRecordingMismatch] };
  }

  const sourceIndexes = new Set(step.source_indexes);
  const identityByIndex = new Map(step.action_identity.map((identity) => [identity.sourceIndex, identity.sourceFingerprint]));
  if (
    identityByIndex.size !== sourceIndexes.size ||
    [...sourceIndexes].some((sourceIndex) => !identityByIndex.has(sourceIndex)) ||
    [...identityByIndex.keys()].some((sourceIndex) => !sourceIndexes.has(sourceIndex))
  ) {
    return { status: 'stale', evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureActionIdentityMismatch] };
  }
  for (const [sourceIndex, sourceFingerprint] of identityByIndex) {
    const action = capture.actions.find((item) => item.source_index === sourceIndex);
    if (!action || action.source_fingerprint !== sourceFingerprint) {
      return { status: 'stale', evidence: null, blocker_reasons: [CAPTURE_BLOCKER_REASONS.captureActionIdentityMismatch] };
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
  if (uniqueReasons.length > 0) {
    return { status: bindingStatus(uniqueReasons), evidence: null, blocker_reasons: uniqueReasons };
  }
  return { status: 'valid', evidence: states, blocker_reasons: [] };
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
