import { describe, expect, it } from 'vitest';
import { ANNOTATION_BLOCKER_REASONS, OVERLAY_PAINT_ORDER } from './annotationSystem';
import { planResolvedTutorialFrame } from './resolvedFramePlan';
import type { FramePlanRequest } from './framePlan';
import type { ApprovedVisualReference, ReferenceRegion } from './visualReference';

const reference: ApprovedVisualReference = {
  reference_id: 'adobe-editor-add-content',
  application: 'Adobe Express',
  application_variant: 'Education',
  context_state: 'editor/add-content',
  captured_at: '2026-08-24T14:57:20Z',
  verified_at: '2026-08-24T15:00:00Z',
  sanitized_derivative_reference: 'sanitized://editor-add-content',
  source_reference: 'teacher-upload://editor-add-content',
  provenance: ['PPUX fixture'],
  visible_ui_claims: ['Add content', 'Media'],
  manifest_reference: {
    manifest_id: 'manifest-editor-add-content',
    record_revision: 3,
    fingerprint: 'sha256:manifest',
    verified_at: '2026-08-24T15:00:00Z',
    external_file_id: 'drive-file-editor-add-content',
  },
  asset_reference: {
    asset_id: 'asset-editor-add-content',
    stable_ref: 'asset://sanitized/editor-add-content',
    content_fingerprint: 'sha256:approved-image',
  },
};

const target: ReferenceRegion = {
  region_id: 'add-content-button',
  claim: 'Add content',
  rect: [0.3, 0.4, 0.2, 0.1],
  fill_allowed: false,
};

function frame(overrides: Partial<FramePlanRequest> = {}): FramePlanRequest {
  return {
    library: { references: [reference] },
    selection: {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'editor/add-content',
      required_ui_claims: ['Add content'],
    },
    region_set: {
      reference_id: reference.reference_id,
      content_fingerprint: reference.asset_reference.content_fingerprint,
      regions: [target],
    },
    must_show_claims: ['Add content'],
    annotation_intent: {
      target_region_id: target.region_id,
      label: 'Add content',
      preferred_side: 'right',
    },
    source_width_px: 1280,
    source_height_px: 720,
    output_width_px: 1280,
    output_height_px: 720,
    ...overrides,
  };
}

describe('planResolvedTutorialFrame', () => {
  it('emits the standard plan-authorized overlays in canonical paint order', () => {
    const result = planResolvedTutorialFrame({ frame: frame(), overlays: { ordinal: 2 } });

    expect(result.status).toBe('valid');
    expect(result.blocker_reasons).toEqual([]);
    expect(result.plan?.overlays.map((overlay) => overlay.kind)).toEqual([...OVERLAY_PAINT_ORDER]);
    expect(result.plan?.overlays.map((overlay) => overlay.overlay_id)).toEqual([
      'spotlight-2', 'badge-2', 'arrow-2', 'label-2',
    ]);
    expect(result.plan?.execution_authorized).toBe(false);
  });

  it('is structurally deterministic for identical inputs', () => {
    const request = { frame: frame(), overlays: { ordinal: 3 } } as const;

    expect(planResolvedTutorialFrame(request)).toEqual(planResolvedTutorialFrame(request));
  });

  it('keeps zero-overlay intent explicit', () => {
    const result = planResolvedTutorialFrame({
      frame: frame(),
      overlays: { ordinal: 1, kinds: [] },
    });

    expect(result.status).toBe('valid');
    expect(result.plan?.overlays).toEqual([]);
  });

  it('fails closed for unsupported inset instead of silently dropping it', () => {
    const result = planResolvedTutorialFrame({
      frame: frame(),
      overlays: { ordinal: 1, kinds: ['inset'] },
    });

    expect(result.status).toBe('blocked');
    expect(result.plan).toBeNull();
    expect(result.blocker_reasons).toEqual([ANNOTATION_BLOCKER_REASONS.unknownOverlayKind]);
  });

  it('surfaces overlay placement blockers without returning a partial plan', () => {
    const result = planResolvedTutorialFrame({
      frame: frame({ output_width_px: 304, output_height_px: 171 }),
      overlays: { ordinal: 1 },
    });

    expect(result.status).toBe('blocked');
    expect(result.plan).toBeNull();
    expect(result.blocker_reasons).toContain(ANNOTATION_BLOCKER_REASONS.clearanceUnavailable);
  });
});
