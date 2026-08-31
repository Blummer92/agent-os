import { describe, expect, it } from 'vitest';
import { admitExactReference, type ExactReferenceRequest } from './exactReferenceGate';
import type { ApprovedVisualReference, ReferenceRegionSet } from './visualReference';

const reference: ApprovedVisualReference = {
  reference_id: 'adobe-elements-shapes',
  application: 'Adobe Express',
  application_variant: 'Education',
  context_state: 'editor/elements/shapes',
  captured_at: '2026-08-30T12:00:00Z',
  verified_at: '2026-08-30T12:05:00Z',
  sanitized_derivative_reference: 'sanitized://elements-shapes',
  source_reference: 'teacher-upload://elements-shapes',
  provenance: ['teacher-approved-source'],
  visible_ui_claims: ['Adobe Express', 'Elements', 'Shapes', 'circle', 'Fill color'],
  manifest_reference: {
    manifest_id: 'manifest-elements-shapes',
    record_revision: 1,
    fingerprint: 'manifest-fingerprint',
    verified_at: '2026-08-30T12:05:00Z',
    external_file_id: 'elements-shapes',
  },
  asset_reference: {
    asset_id: 'asset-elements-shapes',
    stable_ref: 'visual-reference://elements-shapes',
    content_fingerprint: 'fingerprint-elements-shapes',
  },
};

const regions: ReferenceRegionSet = {
  reference_id: reference.reference_id,
  content_fingerprint: reference.asset_reference.content_fingerprint,
  regions: [
    { region_id: 'elements-panel', claim: 'Elements', rect: [0.02, 0.1, 0.25, 0.8], fill_allowed: false },
    { region_id: 'shape-target', claim: 'circle', rect: [0.35, 0.3, 0.2, 0.2], fill_allowed: false },
    { region_id: 'future-artwork', claim: null, rect: [0.65, 0.3, 0.25, 0.4], fill_allowed: true },
  ],
};

const base: ExactReferenceRequest = {
  library: { references: [reference] },
  selection: {
    application: 'Adobe Express',
    application_variant: 'Education',
    context_state: 'editor/elements/shapes',
    required_ui_claims: ['Elements', 'Shapes', 'circle'],
  },
  region_set: regions,
  required_region_ids: ['elements-panel', 'shape-target'],
  source_expected: true,
  routing_resolved: true,
  source_accessible: true,
  source_kind: 'approved-source',
};

describe('exact reference fail-closed gate', () => {
  it('admits exactly one approved source in the required state', () => {
    expect(admitExactReference(base)).toEqual({
      status: 'admitted',
      reference_id: reference.reference_id,
      source_reference: reference.source_reference,
      fill_region_ids: ['future-artwork'],
      fidelity_claim: 'exact-source-bound',
    });
  });

  it('blocks an exact request with no source', () => {
    const result = admitExactReference({ ...base, source_kind: 'none', library: { references: [] } });
    expect(result.status).toBe('blocked');
    if (result.status === 'blocked') {
      expect(result.blocker_reasons).toEqual(['exact-reference-source-missing']);
      expect(result.generated_reconstruction_allowed).toBe(false);
      expect(result.fidelity_claim).toBeNull();
    }
  });

  it('rejects prose and plausible synthetic reconstruction as exact evidence', () => {
    for (const source_kind of ['prose-only', 'synthetic-reconstruction'] as const) {
      const result = admitExactReference({ ...base, source_kind });
      expect(result.status).toBe('blocked');
      if (result.status === 'blocked') expect(result.blocker_reasons).toContain('exact-reference-synthetic-source-rejected');
    }
  });

  it('distinguishes unresolved routing from true source absence', () => {
    const result = admitExactReference({ ...base, routing_resolved: false });
    expect(result.status).toBe('blocked');
    if (result.status === 'blocked') expect(result.blocker_reasons).toEqual(['exact-reference-routing-unresolved']);
  });

  it('blocks inaccessible, wrong-state, and missing required-region evidence', () => {
    const inaccessible = admitExactReference({ ...base, source_accessible: false });
    expect(inaccessible.status).toBe('blocked');

    const wrongState = admitExactReference({ ...base, selection: { ...base.selection, context_state: 'editor/media' } });
    expect(wrongState.status).toBe('blocked');

    const missingRegion = admitExactReference({ ...base, required_region_ids: ['shape-target', 'fill-control'] });
    expect(missingRegion.status).toBe('blocked');
    if (missingRegion.status === 'blocked') expect(missingRegion.blocker_reasons).toContain('exact-reference-required-region-missing:fill-control');
  });

  it('admits a sparse scaffold when fill authority is explicit and anchors remain present', () => {
    const result = admitExactReference(base);
    expect(result.status).toBe('admitted');
    if (result.status === 'admitted') expect(result.fill_region_ids).toEqual(['future-artwork']);
  });

  it('does not infer fill authority from visual blankness or provider claims', () => {
    const noFill: ReferenceRegionSet = {
      ...regions,
      regions: regions.regions.map((region) => ({ ...region, fill_allowed: false })),
    };
    const result = admitExactReference({ ...base, region_set: noFill });
    expect(result.status).toBe('admitted');
    if (result.status === 'admitted') expect(result.fill_region_ids).toEqual([]);
  });
});
