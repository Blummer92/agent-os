import { describe, expect, it } from 'vitest';
import { createImage, imageSha256, setPixel } from './exactCompositePrimitives';
import {
  BOUNDED_FILL_BLOCKER_REASONS,
  admitBoundedFill,
  composeGeneratedPatch,
  validateGeneratedPatch,
  type BoundedFillIntent,
} from './boundedFillGeneration';
import type { ApprovedVisualReference, ReferenceRegionSet } from './visualReference';

const reference: ApprovedVisualReference = {
  reference_id: 'candy-scaffold',
  application: 'Adobe Express',
  application_variant: 'Education',
  context_state: 'editor/candy-branding',
  captured_at: '2026-08-30T12:00:00Z',
  verified_at: '2026-08-30T12:05:00Z',
  sanitized_derivative_reference: 'sanitized://candy-scaffold',
  source_reference: 'teacher-upload://candy-scaffold',
  provenance: ['synthetic privacy-safe Candy Branding fixture'],
  visible_ui_claims: ['wrapper-art-area', 'brand-name-anchor'],
  manifest_reference: {
    manifest_id: 'manifest-candy',
    record_revision: 1,
    fingerprint: 'manifest-candy-fingerprint',
    verified_at: '2026-08-30T12:05:00Z',
    external_file_id: 'candy-scaffold-file',
  },
  asset_reference: {
    asset_id: 'asset-candy-scaffold',
    stable_ref: 'visual-reference://candy-scaffold',
    content_fingerprint: 'candy-scaffold-fingerprint',
  },
};

const regionSet: ReferenceRegionSet = {
  reference_id: reference.reference_id,
  content_fingerprint: reference.asset_reference.content_fingerprint,
  regions: [
    { region_id: 'brand-fill', claim: 'wrapper-art-area', rect: [0.25, 0.25, 0.5, 0.5], fill_allowed: true },
    { region_id: 'brand-anchor', claim: 'brand-name-anchor', rect: [0.05, 0.05, 0.1, 0.1], fill_allowed: false },
  ],
};

function intent(overrides: Partial<BoundedFillIntent> = {}): BoundedFillIntent {
  return {
    fill_id: 'fill-brand-art',
    region_id: 'brand-fill',
    prompt: 'Create new colorful candy-brand artwork inside this bounded wrapper art region.',
    fill_required: true,
    exact_content_required: false,
    ...overrides,
  };
}

function admittedPlan() {
  const admitted = admitBoundedFill(reference, regionSet, intent(), 8, 8);
  expect(admitted.status).toBe('valid');
  if (!admitted.plan) throw new Error('expected admitted bounded fill plan');
  return admitted.plan;
}

describe('PPUX-VRL11 bounded reference-conditioned fill generation', () => {
  it('admits the Candy sparse-scaffold case only for an explicit fill region and intent', () => {
    const admitted = admitBoundedFill(reference, regionSet, intent(), 8, 8);
    expect(admitted.status).toBe('valid');
    expect(admitted.plan?.destination.rect).toEqual([2, 2, 4, 4]);
    expect(admitted.plan?.execution_authorized).toBe(false);
    expect(JSON.stringify(admitted.plan)).not.toMatch(/gemini|flash|firefly|provider|price/i);
  });

  it('blocks an anchor, missing intent, and exact-content requirements', () => {
    expect(admitBoundedFill(reference, regionSet, intent({ region_id: 'brand-anchor' }), 8, 8).blocker_reasons)
      .toContain(BOUNDED_FILL_BLOCKER_REASONS.fillRegionNotAllowed);
    expect(admitBoundedFill(reference, regionSet, intent({ prompt: '   ' }), 8, 8).blocker_reasons)
      .toContain(BOUNDED_FILL_BLOCKER_REASONS.generationIntentMissing);
    expect(admitBoundedFill(reference, regionSet, intent({ exact_content_required: true }), 8, 8).blocker_reasons)
      .toContain(BOUNDED_FILL_BLOCKER_REASONS.exactContentRequired);
  });

  it('reuses #1485 overlap safety instead of widening fill authority', () => {
    const overlapping: ReferenceRegionSet = {
      ...regionSet,
      regions: [
        { region_id: 'brand-fill', claim: 'wrapper-art-area', rect: [0.25, 0.25, 0.5, 0.5], fill_allowed: true },
        { region_id: 'brand-anchor', claim: 'brand-name-anchor', rect: [0.5, 0.5, 0.2, 0.2], fill_allowed: false },
      ],
    };
    const result = admitBoundedFill(reference, overlapping, intent(), 8, 8);
    expect(result.status).toBe('blocked');
    expect(result.blocker_reasons).toContain('visual-reference-fill-region-overlaps-anchor');
  });

  it('rejects missing, malformed, wrong-size, and copy-through patches', () => {
    const plan = admittedPlan();
    const source = createImage(8, 8, [240, 240, 240, 1]);
    expect(validateGeneratedPatch(plan, source, null).blocker_reasons)
      .toContain(BOUNDED_FILL_BLOCKER_REASONS.patchMissing);

    const wrongSize = createImage(8, 8, [20, 30, 40, 1]);
    expect(validateGeneratedPatch(plan, source, {
      fill_id: plan.fill_id,
      image: wrongSize,
      sha256: imageSha256(wrongSize),
    }).blocker_reasons).toContain(BOUNDED_FILL_BLOCKER_REASONS.patchDimensionsMismatch);

    const copy = createImage(4, 4, [240, 240, 240, 1]);
    expect(validateGeneratedPatch(plan, source, {
      fill_id: plan.fill_id,
      image: copy,
      sha256: imageSha256(copy),
    }).blocker_reasons).toContain(BOUNDED_FILL_BLOCKER_REASONS.patchCopyThrough);

    const changed = createImage(4, 4, [20, 30, 40, 1]);
    expect(validateGeneratedPatch(plan, source, {
      fill_id: plan.fill_id,
      image: changed,
      sha256: 'not-the-image-digest',
    }).blocker_reasons).toContain(BOUNDED_FILL_BLOCKER_REASONS.patchIdentityMismatch);
  });

  it('composes only inside the exact fill rectangle and preserves every outside pixel', () => {
    const plan = admittedPlan();
    const source = createImage(8, 8, [240, 240, 240, 1]);
    setPixel(source, 0, 0, [1, 2, 3, 1]);
    const patch = createImage(4, 4, [80, 20, 140, 1]);
    const output = composeGeneratedPatch(plan, source, {
      fill_id: plan.fill_id,
      image: patch,
      sha256: imageSha256(patch),
    });

    for (let y = 0; y < 8; y += 1) {
      for (let x = 0; x < 8; x += 1) {
        const inside = x >= 2 && x < 6 && y >= 2 && y < 6;
        const at = (y * 8 + x) * 4;
        if (inside) {
          expect(Array.from(output.data.slice(at, at + 4))).toEqual([80, 20, 140, 255]);
        } else {
          expect(Array.from(output.data.slice(at, at + 4))).toEqual(Array.from(source.data.slice(at, at + 4)));
        }
      }
    }
  });

  it('is byte-stable for repeated composition of the same accepted patch', () => {
    const plan = admittedPlan();
    const source = createImage(8, 8, [240, 240, 240, 1]);
    const patch = createImage(4, 4, [10, 120, 200, 1]);
    const generated = { fill_id: plan.fill_id, image: patch, sha256: imageSha256(patch) };
    expect(imageSha256(composeGeneratedPatch(plan, source, generated)))
      .toBe(imageSha256(composeGeneratedPatch(plan, source, generated)));
  });
});
