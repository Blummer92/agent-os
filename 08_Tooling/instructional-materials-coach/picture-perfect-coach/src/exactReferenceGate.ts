import {
  admitReferenceRegions,
  selectVisualReference,
  type ReferenceRegionSet,
  type VisualReferenceLibrary,
  type VisualReferenceSelectionRequest,
} from './visualReference';

export type ExactReferenceBlocker =
  | 'exact-reference-source-missing'
  | 'exact-reference-routing-unresolved'
  | 'exact-reference-source-inaccessible'
  | 'exact-reference-synthetic-source-rejected'
  | 'exact-reference-required-region-missing'
  | string;

export type ExactReferenceRequest = Readonly<{
  library: VisualReferenceLibrary;
  selection: VisualReferenceSelectionRequest;
  region_set: ReferenceRegionSet | null;
  required_region_ids: readonly string[];
  source_expected: boolean;
  routing_resolved: boolean;
  source_accessible: boolean;
  source_kind: 'approved-source' | 'synthetic-reconstruction' | 'prose-only' | 'none';
}>;

export type ExactReferenceDecision =
  | Readonly<{
      status: 'admitted';
      reference_id: string;
      source_reference: string;
      fill_region_ids: readonly string[];
      fidelity_claim: 'exact-source-bound';
    }>
  | Readonly<{
      status: 'blocked';
      blocker_reasons: readonly ExactReferenceBlocker[];
      next_action: string;
      generated_reconstruction_allowed: false;
      fidelity_claim: null;
    }>;

function blocked(reasons: readonly ExactReferenceBlocker[], nextAction: string): ExactReferenceDecision {
  return {
    status: 'blocked',
    blocker_reasons: reasons,
    next_action: nextAction,
    generated_reconstruction_allowed: false,
    fidelity_claim: null,
  };
}

/**
 * #1496 exact-mode admission. This gate does not discover sources, infer state,
 * inspect pixels, or generate fallbacks. It composes the existing #1372/#1485
 * reference and region contracts and fails closed before exact planning.
 */
export function admitExactReference(request: ExactReferenceRequest): ExactReferenceDecision {
  if (!request.routing_resolved && request.source_expected) {
    return blocked(
      ['exact-reference-routing-unresolved'],
      'Resolve the expected approved source through the governed artifact-routing path.',
    );
  }

  if (request.source_kind === 'none') {
    return blocked(
      ['exact-reference-source-missing'],
      'Supply or resolve the approved source artifact required for exact reproduction.',
    );
  }

  if (request.source_kind === 'prose-only' || request.source_kind === 'synthetic-reconstruction') {
    return blocked(
      ['exact-reference-synthetic-source-rejected'],
      'Use an approved source artifact; prose or reconstructed pixels cannot establish exact fidelity.',
    );
  }

  if (!request.source_accessible) {
    return blocked(
      ['exact-reference-source-inaccessible'],
      'Restore access to the approved source artifact before exact reproduction.',
    );
  }

  const selected = selectVisualReference(request.library, request.selection);
  if (selected.status !== 'valid' || selected.reference === null) {
    return blocked(
      selected.blocker_reasons,
      'Resolve exactly one approved reference in the required application and instructional state.',
    );
  }

  if (request.region_set === null) {
    return blocked(
      ['exact-reference-required-region-missing'],
      'Bind the required target and must-show regions to the selected approved reference.',
    );
  }

  const admittedRegions = admitReferenceRegions(selected.reference, request.region_set);
  if (admittedRegions.status !== 'valid' || admittedRegions.regions === null) {
    return blocked(
      admittedRegions.blocker_reasons,
      'Correct the reference-region evidence before exact reproduction.',
    );
  }

  const regionIds = new Set(admittedRegions.regions.map((region) => region.region_id));
  const missing = request.required_region_ids.filter((regionId) => !regionIds.has(regionId));
  if (missing.length > 0) {
    return blocked(
      missing.map((regionId) => `exact-reference-required-region-missing:${regionId}`),
      'Bind every required target and must-show region to the selected approved reference.',
    );
  }

  return {
    status: 'admitted',
    reference_id: selected.reference.reference_id,
    source_reference: selected.reference.source_reference,
    fill_region_ids: admittedRegions.regions.filter((region) => region.fill_allowed).map((region) => region.region_id),
    fidelity_claim: 'exact-source-bound',
  };
}
