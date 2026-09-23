import { describe, expect, it } from 'vitest';
import {
  COMPOSITING_COLOUR_SPACES,
  DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  FRAME_PLAN_BLOCKER_REASONS,
  OVERLAY_KINDS,
  RECT_CONVENTION,
  RECT_SPACES,
  RENDER_MODES,
  RESAMPLERS,
  SPOTLIGHT_FALLOFF_FUNCTIONS,
  TUTORIAL_FRAME_PLAN_VERSION,
  planTutorialFrame,
  type FramePlanRequest,
  type OutputPixelRect,
  type ReferenceNormalizedRect,
  type SourcePixelRect,
  type TutorialFramePlan,
} from './framePlan';
import {
  VISUAL_REFERENCE_BLOCKER_REASONS,
  type ApprovedVisualReference,
  type ReferenceRegion,
} from './visualReference';

const outputRect = (rect: readonly [number, number, number, number]): OutputPixelRect => ({
  space: RECT_SPACES.outputPixel,
  rect,
});

const plan: TutorialFramePlan = {
  plan_version: TUTORIAL_FRAME_PLAN_VERSION,
  rect_convention: RECT_CONVENTION,
  base_reference: {
    reference_id: 'adobe-editor-add-content',
    stable_ref: 'asset://sanitized/editor-add-content',
    content_fingerprint: 'sha256:approved-image',
  },
  resolved_target_region_id: 'add-content-button',
  source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 1280, 720] },
  output_aspect: { width: 16, height: 9 },
  output_width_px: 1280,
  output_height_px: 720,
  render_mode: RENDER_MODES.cropOnly,
  scale_x: 1,
  scale_y: 1,
  render_spec: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  asset_fills: [],
  overlays: [
    {
      overlay_id: 'spotlight-1',
      kind: OVERLAY_KINDS.spotlight,
      bounds: outputRect([400, 300, 240, 80]),
      region_id: 'add-content-button',
      boundary: outputRect([412, 312, 216, 56]),
      padding_px: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC.spotlight.padding_px,
      falloff_px: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC.spotlight.falloff_px,
      falloff_function: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC.spotlight.falloff_function,
    },
    {
      overlay_id: 'label-1',
      kind: OVERLAY_KINDS.label,
      bounds: outputRect([660, 300, 320, 40]),
      text: 'Add content',
      preferred_side: 'right',
      resolved_side: 'right',
    },
  ],
  anchored_rects: [{ region_id: 'add-content-button', rect: outputRect([412, 312, 216, 56]) }],
  must_show_region_ids: ['add-content-button'],
  annotation_intent: { target_region_id: 'add-content-button', label: 'Add content', preferred_side: 'right' },
  execution_authorized: false,
};

describe('rectangle space tagging', () => {
  it('keeps one repository rectangle ordering', () => {
    expect(RECT_CONVENTION).toBe('xywh');
    expect(plan.rect_convention).toBe(RECT_CONVENTION);
  });

  it('gives every plan rectangle an explicit distinct space', () => {
    expect(new Set(Object.values(RECT_SPACES)).size).toBe(3);
    expect(plan.source_rect.space).toBe('source-pixel');
    expect(plan.anchored_rects[0]!.rect.space).toBe('output-pixel');
    expect(plan.overlays[0]!.bounds.space).toBe('output-pixel');
  });

  it('rejects a rectangle from another space at compile time', () => {
    const region: ReferenceNormalizedRect = { space: RECT_SPACES.referenceNormalized, rect: [0.32, 0.43, 0.17, 0.08] };
    // @ts-expect-error a #1485 reference-normalized rect is not an output-pixel rect
    const anchored: OutputPixelRect = region;
    // @ts-expect-error source pixels and output pixels are distinct spaces
    const cropped: SourcePixelRect = outputRect([0, 0, 8, 8]);
    expect(anchored.rect).toHaveLength(4);
    expect(cropped.rect).toHaveLength(4);
  });
});

describe('resolved render constants', () => {
  const spec = DEFAULT_EXACT_COMPOSITE_RENDER_SPEC;

  it('resolves every constant an executor may not invent', () => {
    expect(Object.values(COMPOSITING_COLOUR_SPACES)).toContain(spec.compositing_colour_space);
    expect(Object.values(RESAMPLERS)).toContain(spec.resampler);
    expect(Object.values(SPOTLIGHT_FALLOFF_FUNCTIONS)).toContain(spec.spotlight.falloff_function);
    for (const value of [
      spec.overlay_bleed_px,
      spec.annotation_clearance_px,
      spec.context_margin_fraction,
      spec.spotlight.padding_px,
      spec.spotlight.falloff_px,
      spec.badge.diameter_px,
      spec.badge.font_size_px,
      spec.arrow.shaft_width_px,
      spec.arrow.head_length_px,
      spec.arrow.head_width_px,
      spec.label.font_size_px,
      spec.label.line_height_px,
      spec.label.max_width_px,
      spec.inset.magnification,
    ]) {
      expect(Number.isFinite(value)).toBe(true);
      expect(value).toBeGreaterThan(0);
    }
  });

  it('uses the repository canonical RGBA range', () => {
    const colours = [
      spec.dim_rgba,
      spec.badge.fill_rgba,
      spec.badge.border_rgba,
      spec.badge.text_rgba,
      spec.arrow.rgba,
      spec.label.background_rgba,
      spec.label.text_rgba,
      spec.inset.border_rgba,
    ];
    for (const [r, g, b, a] of colours) {
      for (const channel of [r, g, b]) {
        expect(Number.isInteger(channel)).toBe(true);
        expect(channel).toBeGreaterThanOrEqual(0);
        expect(channel).toBeLessThanOrEqual(255);
      }
      expect(a).toBeGreaterThanOrEqual(0);
      expect(a).toBeLessThanOrEqual(1);
    }
  });

  it('pairs the crop-only default with no resampling', () => {
    expect(spec.resampler).toBe(RESAMPLERS.none);
    expect(plan.render_mode).toBe(RENDER_MODES.cropOnly);
    expect(plan.scale_x).toBe(1);
    expect(plan.scale_y).toBe(1);
  });

  it('is deep frozen so a resolved plan cannot drift', () => {
    expect(Object.isFrozen(spec)).toBe(true);
    for (const nested of [spec.spotlight, spec.badge, spec.arrow, spec.label, spec.inset, spec.dim_rgba]) {
      expect(Object.isFrozen(nested)).toBe(true);
    }
  });
});

describe('plan boundaries', () => {
  it('carries no provider or service identity', () => {
    const serialized = JSON.stringify(plan).toLowerCase();
    for (const token of ['openai', 'anthropic', 'gemini', 'firefly', 'dall-e', 'midjourney', 'stability', 'provider', 'api_key', 'endpoint']) {
      expect(serialized).not.toContain(token);
    }
  });

  it('produces no synthesized fill under exact-composite', () => {
    expect(plan.asset_fills).toHaveLength(0);
  });

  it('remains presentation evidence rather than execution authority', () => {
    expect(plan.execution_authorized).toBe(false);
    expect(plan.plan_version).toBe('picture-perfect-exact-composite-plan-v1');
  });

  it('binds the base reference by identity and content fingerprint', () => {
    expect(plan.base_reference.reference_id).toBeTruthy();
    expect(plan.base_reference.content_fingerprint).toBeTruthy();
  });

  it('keeps must-show identities and anchored rects aligned', () => {
    for (const regionId of plan.must_show_region_ids) {
      expect(plan.anchored_rects.some((anchor) => anchor.region_id === regionId)).toBe(true);
    }
  });
});

const reference: ApprovedVisualReference = {
  reference_id: 'adobe-editor-add-content',
  application: 'Adobe Express',
  application_variant: 'Education',
  context_state: 'editor/add-content',
  captured_at: '2026-08-24T14:57:20Z',
  verified_at: '2026-08-24T15:00:00Z',
  sanitized_derivative_reference: 'sanitized://editor-add-content',
  source_reference: 'teacher-upload://editor-add-content',
  provenance: ['PPUX fixture', 'source-state:editor/add-content'],
  visible_ui_claims: ['Add content', 'Adobe Express', 'Media'],
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

const targetRegion: ReferenceRegion = {
  region_id: 'add-content-button',
  claim: 'Add content',
  rect: [0.3, 0.4, 0.2, 0.1],
  fill_allowed: false,
};

const mediaRegion: ReferenceRegion = {
  region_id: 'media-tab',
  claim: 'Media',
  rect: [0.32, 0.42, 0.06, 0.04],
  fill_allowed: false,
};

function request(overrides: Partial<FramePlanRequest> = {}): FramePlanRequest {
  return {
    library: { references: [reference] },
    selection: {
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'editor/add-content',
      required_ui_claims: ['Add content', 'Media'],
    },
    region_set: {
      reference_id: reference.reference_id,
      content_fingerprint: reference.asset_reference.content_fingerprint,
      regions: [targetRegion, mediaRegion],
    },
    must_show_claims: ['Add content', 'Media'],
    annotation_intent: { target_region_id: 'add-content-button', label: 'Add content', preferred_side: 'right' },
    source_width_px: 1280,
    source_height_px: 720,
    output_width_px: 304,
    output_height_px: 171,
    ...overrides,
  };
}

describe('planTutorialFrame framing', () => {
  it('derives a deterministic crop-only frame from the target and keep-set', () => {
    const result = planTutorialFrame(request());

    expect(result.status).toBe('valid');
    expect(result.blocker_reasons).toEqual([]);
    expect(result.plan?.source_rect).toEqual({ space: 'source-pixel', rect: [360, 239, 304, 171] });
    expect(result.plan?.render_mode).toBe(RENDER_MODES.cropOnly);
    expect(result.plan?.render_spec.resampler).toBe(RESAMPLERS.none);
    expect(result.plan?.scale_x).toBe(1);
    expect(result.plan?.scale_y).toBe(1);
    expect(result.plan?.output_aspect).toEqual({ width: 16, height: 9 });
  });

  it('derives anchored rects in output coordinates', () => {
    const result = planTutorialFrame(request());

    expect(result.plan?.anchored_rects).toEqual([
      { region_id: 'add-content-button', rect: { space: 'output-pixel', rect: [24, 49, 256, 72] } },
      { region_id: 'media-tab', rect: { space: 'output-pixel', rect: [50, 63, 76, 29] } },
    ]);
    expect(result.plan?.must_show_region_ids).toEqual(['add-content-button', 'media-tab']);
  });

  it('prefers integer scale over fractional when framing allows it', () => {
    const result = planTutorialFrame(request({ output_width_px: 608, output_height_px: 342 }));

    expect(result.plan?.render_mode).toBe(RENDER_MODES.integerScale);
    expect(result.plan?.render_spec.resampler).toBe(RESAMPLERS.nearest);
    expect(result.plan?.scale_x).toBe(2);
    expect(result.plan?.source_rect.rect).toEqual([360, 239, 304, 171]);
    expect(result.plan?.anchored_rects[0]!.rect.rect).toEqual([48, 98, 512, 144]);
  });

  it('binds the plan to the exact reference identity and fingerprint', () => {
    const result = planTutorialFrame(request());

    expect(result.plan?.base_reference).toEqual({
      reference_id: 'adobe-editor-add-content',
      stable_ref: 'asset://sanitized/editor-add-content',
      content_fingerprint: 'sha256:approved-image',
    });
  });

  it('produces no synthesized fill and resolves no overlay', () => {
    const result = planTutorialFrame(request());

    expect(result.plan?.asset_fills).toEqual([]);
    expect(result.plan?.overlays).toEqual([]);
    expect(result.plan?.execution_authorized).toBe(false);
  });
});

describe('planTutorialFrame fail-closed behaviour', () => {
  it('blocks an unknown target region instead of guessing', () => {
    const result = planTutorialFrame(request({
      annotation_intent: { target_region_id: 'not-a-region', label: 'Add content', preferred_side: null },
    }));

    expect(result.status).toBe('blocked');
    expect(result.plan).toBeNull();
    expect(result.blocker_reasons).toContain(FRAME_PLAN_BLOCKER_REASONS.targetUnresolved);
  });

  it('resolves the target from the state-local UI claim when no region id is given', () => {
    const result = planTutorialFrame(request({
      annotation_intent: { target_region_id: '', label: 'Media', preferred_side: null },
    }));

    expect(result.status).toBe('valid');
    expect(result.plan?.must_show_region_ids).toContain('media-tab');
  });

  it('blocks an ambiguous claim-resolved target', () => {
    const duplicate: ReferenceRegion = { ...targetRegion, region_id: 'add-content-button-2' };
    const result = planTutorialFrame(request({
      region_set: {
        reference_id: reference.reference_id,
        content_fingerprint: reference.asset_reference.content_fingerprint,
        regions: [targetRegion, duplicate, mediaRegion],
      },
      annotation_intent: { target_region_id: '', label: 'Add content', preferred_side: null },
    }));

    expect(result.blocker_reasons).toContain(FRAME_PLAN_BLOCKER_REASONS.targetUnresolved);
  });

  it('blocks a must-show claim that has no region', () => {
    const result = planTutorialFrame(request({ must_show_claims: ['Add content', 'Adobe Express'] }));

    expect(result.blocker_reasons).toContain(FRAME_PLAN_BLOCKER_REASONS.mustShowRegionMissing);
  });

  it('blocks a UI-naming label absent from the selected reference claims', () => {
    const result = planTutorialFrame(request({
      annotation_intent: { target_region_id: 'add-content-button', label: 'Insert media', preferred_side: null },
    }));

    expect(result.blocker_reasons).toContain(FRAME_PLAN_BLOCKER_REASONS.labelClaimNotVisible);
  });

  it('blocks inconsistent output geometry', () => {
    const result = planTutorialFrame(request({ output_width_px: 0 }));

    expect(result.blocker_reasons).toContain(FRAME_PLAN_BLOCKER_REASONS.outputGeometryInconsistent);
  });

  it('blocks framing that cannot fit the keep-set inside the source', () => {
    const wide: ReferenceRegion = { region_id: 'whole-screen', claim: 'Media', rect: [0, 0, 1, 1], fill_allowed: false };
    const result = planTutorialFrame(request({
      region_set: {
        reference_id: reference.reference_id,
        content_fingerprint: reference.asset_reference.content_fingerprint,
        regions: [targetRegion, wide],
      },
      must_show_claims: ['Media'],
    }));

    expect(result.blocker_reasons).toContain(FRAME_PLAN_BLOCKER_REASONS.framingUnresolvable);
  });

  it('surfaces #1485 region-admission reasons verbatim', () => {
    const result = planTutorialFrame(request({
      region_set: {
        reference_id: reference.reference_id,
        content_fingerprint: 'sha256:recaptured-image',
        regions: [targetRegion, mediaRegion],
      },
    }));

    expect(result.blocker_reasons).toEqual([VISUAL_REFERENCE_BLOCKER_REASONS.regionIdentityMismatch]);
  });

  it('surfaces reference-selection reasons verbatim', () => {
    const result = planTutorialFrame(request({
      selection: {
        application: 'Adobe Express',
        application_variant: 'Education',
        context_state: 'editor/media',
        required_ui_claims: ['Media'],
      },
    }));

    expect(result.blocker_reasons).toEqual([VISUAL_REFERENCE_BLOCKER_REASONS.referenceMissing]);
  });
});
