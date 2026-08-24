import type {
  ArtifactManifestAssetEvidence,
  AssetReference,
  CaptureStatus,
  ManifestReference,
  VisualAssetCompatibilityEvidence,
} from './captureEvidence';

export const VISUAL_REFERENCE_BLOCKER_REASONS = {
  applicationIdentityMissing: 'visual-reference-application-identity-missing',
  contextStateMissing: 'visual-reference-context-state-missing',
  sourceProvenanceMissing: 'visual-reference-source-provenance-missing',
  sanitizedDerivativeMissing: 'visual-reference-sanitized-derivative-missing',
  privacyUnresolved: 'visual-reference-privacy-unresolved',
  assetIneligible: 'visual-reference-asset-ineligible',
  stale: 'visual-reference-stale',
  referenceMissing: 'visual-reference-missing',
  claimsNotCoVisible: 'visual-reference-claims-not-co-visible',
  currentRecordedUiConflict: 'visual-reference-current-recorded-ui-conflict',
} as const;

export type VisualReferenceBlockerReason =
  (typeof VISUAL_REFERENCE_BLOCKER_REASONS)[keyof typeof VISUAL_REFERENCE_BLOCKER_REASONS];

export type VisualReferenceContextState = string;

export type VisualReferenceSource = Readonly<{
  source_reference: string;
  source_kind: 'teacher-supplied-screenshot' | 'approved-capture' | 'synthetic-test-fixture';
  captured_at: string;
  provenance: readonly string[];
}>;

export type VisualReferenceCandidate = Readonly<{
  reference_id: string;
  application: string;
  application_variant: string | null;
  context_state: VisualReferenceContextState;
  source: VisualReferenceSource;
  sanitized_derivative_reference: string | null;
  sanitization: Readonly<{
    browser_chrome_removed: boolean;
    private_context_removed: boolean;
  }>;
  visible_ui_claims: readonly string[];
  manifest_reference: ManifestReference;
  asset_reference: AssetReference;
  artifact_manifest: ArtifactManifestAssetEvidence;
  compatibility: VisualAssetCompatibilityEvidence;
}>;

export type ApprovedVisualReference = Readonly<{
  reference_id: string;
  application: string;
  application_variant: string | null;
  context_state: VisualReferenceContextState;
  captured_at: string;
  verified_at: string;
  sanitized_derivative_reference: string;
  source_reference: string;
  provenance: readonly string[];
  visible_ui_claims: readonly string[];
  manifest_reference: ManifestReference;
  asset_reference: AssetReference;
}>;

export type VisualReferenceAdmissionResult = Readonly<{
  status: CaptureStatus;
  reference: ApprovedVisualReference | null;
  blocker_reasons: readonly VisualReferenceBlockerReason[];
}>;

export type VisualReferenceLibrary = Readonly<{
  references: readonly ApprovedVisualReference[];
}>;

export type VisualReferenceSelectionRequest = Readonly<{
  application: string;
  application_variant?: string | null;
  context_state: VisualReferenceContextState;
  required_ui_claims: readonly string[];
  recorded_ui_claims?: readonly string[];
}>;

export type VisualReferenceSelectionResult = Readonly<{
  status: CaptureStatus;
  reference: ApprovedVisualReference | null;
  blocker_reasons: readonly VisualReferenceBlockerReason[];
}>;

const CLEARED_RIGHTS = new Set(['cleared-internal', 'licensed', 'public-domain', 'permission-documented']);

function uniqueSorted(values: readonly string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function eligibilityReasons(candidate: VisualReferenceCandidate): VisualReferenceBlockerReason[] {
  const reasons: VisualReferenceBlockerReason[] = [];
  const asset = candidate.artifact_manifest.asset;
  const compatibility = candidate.compatibility;

  if (!candidate.application.trim()) reasons.push(VISUAL_REFERENCE_BLOCKER_REASONS.applicationIdentityMissing);
  if (!candidate.context_state.trim()) reasons.push(VISUAL_REFERENCE_BLOCKER_REASONS.contextStateMissing);
  if (!candidate.source.source_reference.trim() || candidate.source.provenance.length === 0) {
    reasons.push(VISUAL_REFERENCE_BLOCKER_REASONS.sourceProvenanceMissing);
  }

  const derivative = candidate.sanitized_derivative_reference?.trim() ?? '';
  if (
    !derivative ||
    derivative === candidate.source.source_reference ||
    !candidate.sanitization.browser_chrome_removed ||
    !candidate.sanitization.private_context_removed
  ) {
    reasons.push(VISUAL_REFERENCE_BLOCKER_REASONS.sanitizedDerivativeMissing);
  }

  if (!asset.privacy_resolved || asset.residual_privacy_risk) {
    reasons.push(VISUAL_REFERENCE_BLOCKER_REASONS.privacyUnresolved);
  }

  if (
    candidate.artifact_manifest.contract_version !== 'curriculum-artifact-manifest-v1' ||
    candidate.artifact_manifest.external_identity.access_state !== 'verified' ||
    candidate.artifact_manifest.statuses.classroom_readiness !== 'ready' ||
    !CLEARED_RIGHTS.has(asset.rights_classification) ||
    asset.direct_use_status !== 'student-ready' ||
    asset.replacement_required ||
    candidate.compatibility.contract_version !== 'curriculum-visual-asset-compatibility-v2' ||
    candidate.compatibility.classification !== 'eligible' ||
    compatibility.cohesion_profile.medium !== 'screen-capture' ||
    compatibility.cohesion_profile.representation_class !== 'interface-capture'
  ) {
    reasons.push(VISUAL_REFERENCE_BLOCKER_REASONS.assetIneligible);
  }

  if (compatibility.freshness.stale) reasons.push(VISUAL_REFERENCE_BLOCKER_REASONS.stale);
  return [...new Set(reasons)];
}

function statusForAdmission(reasons: readonly VisualReferenceBlockerReason[]): CaptureStatus {
  if (reasons.includes(VISUAL_REFERENCE_BLOCKER_REASONS.stale)) return 'stale';
  if (reasons.includes(VISUAL_REFERENCE_BLOCKER_REASONS.privacyUnresolved)) return 'manual-review-required';
  return 'blocked';
}

/**
 * Admit one reusable application-state reference. Raw teacher screenshots are
 * evidence only: a distinct sanitized derivative with explicit privacy clearance
 * and existing ArtifactManifest/compatibility eligibility is required.
 */
export function admitVisualReference(candidate: VisualReferenceCandidate): VisualReferenceAdmissionResult {
  const reasons = eligibilityReasons(candidate);
  if (reasons.length > 0) {
    return { status: statusForAdmission(reasons), reference: null, blocker_reasons: reasons };
  }

  return {
    status: 'valid',
    blocker_reasons: [],
    reference: {
      reference_id: candidate.reference_id,
      application: candidate.application.trim(),
      application_variant: candidate.application_variant?.trim() || null,
      context_state: candidate.context_state.trim(),
      captured_at: candidate.source.captured_at,
      verified_at: candidate.manifest_reference.verified_at,
      sanitized_derivative_reference: candidate.sanitized_derivative_reference!.trim(),
      source_reference: candidate.source.source_reference,
      provenance: [...candidate.source.provenance],
      visible_ui_claims: uniqueSorted(candidate.visible_ui_claims),
      manifest_reference: candidate.manifest_reference,
      asset_reference: candidate.asset_reference,
    },
  };
}

function sameVariant(reference: ApprovedVisualReference, requested: string | null | undefined): boolean {
  if (requested === undefined) return true;
  return (reference.application_variant ?? null) === (requested?.trim() || null);
}

function hasAllClaims(reference: ApprovedVisualReference, claims: readonly string[]): boolean {
  const visible = new Set(reference.visible_ui_claims);
  return claims.every((claim) => visible.has(claim));
}

function compareCurrentAndRecordedClaims(
  requiredClaims: readonly string[],
  currentClaims: readonly string[],
  recordedClaims: readonly string[] | undefined,
): boolean {
  if (!recordedClaims || requiredClaims.length === 0) return false;
  const current = new Set(currentClaims);
  const recorded = new Set(recordedClaims);
  return requiredClaims.some((claim) => current.has(claim) !== recorded.has(claim));
}

/**
 * Retrieve exactly one approved application/context-state reference. Claims from
 * multiple references are never unioned. A historical/current claim disagreement
 * is explicit manual review rather than silent normalization.
 */
export function selectVisualReference(
  library: VisualReferenceLibrary,
  request: VisualReferenceSelectionRequest,
): VisualReferenceSelectionResult {
  if (!request.application.trim()) {
    return {
      status: 'blocked',
      reference: null,
      blocker_reasons: [VISUAL_REFERENCE_BLOCKER_REASONS.applicationIdentityMissing],
    };
  }
  if (!request.context_state.trim()) {
    return {
      status: 'blocked',
      reference: null,
      blocker_reasons: [VISUAL_REFERENCE_BLOCKER_REASONS.contextStateMissing],
    };
  }

  const stateMatches = library.references.filter((reference) =>
    reference.application === request.application.trim() &&
    sameVariant(reference, request.application_variant) &&
    reference.context_state === request.context_state.trim(),
  );
  if (stateMatches.length === 0) {
    return {
      status: 'blocked',
      reference: null,
      blocker_reasons: [VISUAL_REFERENCE_BLOCKER_REASONS.referenceMissing],
    };
  }

  const requiredClaims = uniqueSorted(request.required_ui_claims);
  const supporting = stateMatches.filter((reference) => hasAllClaims(reference, requiredClaims));
  if (supporting.length === 0) {
    return {
      status: 'blocked',
      reference: null,
      blocker_reasons: [VISUAL_REFERENCE_BLOCKER_REASONS.claimsNotCoVisible],
    };
  }

  supporting.sort((left, right) =>
    right.verified_at.localeCompare(left.verified_at) ||
    right.captured_at.localeCompare(left.captured_at) ||
    left.reference_id.localeCompare(right.reference_id),
  );
  const selected = supporting[0];

  if (compareCurrentAndRecordedClaims(requiredClaims, selected.visible_ui_claims, request.recorded_ui_claims)) {
    return {
      status: 'manual-review-required',
      reference: null,
      blocker_reasons: [VISUAL_REFERENCE_BLOCKER_REASONS.currentRecordedUiConflict],
    };
  }

  return { status: 'valid', reference: selected, blocker_reasons: [] };
}

export function buildVisualReferenceDirective(reference: ApprovedVisualReference): string {
  return [
    `Use only approved current application visual-reference evidence ${reference.asset_reference.stable_ref} for ${reference.application}`,
    `in state ${reference.context_state}.`,
    'Preserve the supplied interface appearance and state.',
    'Do not redraw, reconstruct, invent, or merge controls, labels, geometry, or states from another reference.',
  ].join(' ');
}
