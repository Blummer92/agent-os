import { describe, expect, it } from 'vitest';
import {
  ANNOTATION_BLOCKER_REASONS,
  OVERLAY_PAINT_ORDER,
  resolveFrameOverlays,
} from './annotationSystem';
import {
  DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  RECT_CONVENTION,
  RECT_SPACES,
  RENDER_MODES,
  TUTORIAL_FRAME_PLAN_VERSION,
  type AnchoredRegionRect,
  type TutorialFramePlan,
} from './framePlan';

const anchored = (regionId: string, rect: readonly [number, number, number, number]): AnchoredRegionRect => ({
  region_id: regionId,
  rect: { space: RECT_SPACES.outputPixel, rect },
});

function planWith(overrides: Partial<TutorialFramePlan> = {}): TutorialFramePlan {
  return {
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
    overlays: [],
    anchored_rects: [anchored('add-content-button', [400, 300, 240, 80])],
    must_show_region_ids: ['add-content-button'],
    annotation_intent: { target_region_id: 'add-content-button', label: 'Add content', preferred_side: 'right' },
    execution_authorized: false,
    ...overrides,
  };
}

describe('resolveFrameOverlays geometry', () => {
  it('resolves every overlay deterministically in paint order', () => {
    const result = resolveFrameOverlays(planWith(), { ordinal: 1 });

    expect(result.status).toBe('valid');
    expect(result.blocker_reasons).toEqual([]);
    expect(result.overlays?.map((overlay) => overlay.kind)).toEqual([...OVERLAY_PAINT_ORDER]);
    expect(result.overlays?.map((overlay) => overlay.overlay_id)).toEqual([
      'spotlight-1', 'badge-1', 'arrow-1', 'label-1',
    ]);
  });

  it('pads the spotlight boundary and dilates its bounds by the declared falloff', () => {
    const result = resolveFrameOverlays(planWith(), { ordinal: 1 });
    const spotlight = result.overlays?.[0];

    expect(spotlight?.kind).toBe('spotlight');
    expect(spotlight?.bounds).toEqual({ space: 'output-pixel', rect: [382, 282, 276, 116] });
    expect(spotlight && 'boundary' in spotlight ? spotlight.boundary.rect : null).toEqual([388, 288, 264, 104]);
    expect(spotlight && 'falloff_px' in spotlight ? spotlight.falloff_px : null)
      .toBe(DEFAULT_EXACT_COMPOSITE_RENDER_SPEC.spotlight.falloff_px);
  });

  it('places badge, arrow, and label on the preferred side with deterministic clearance', () => {
    const result = resolveFrameOverlays(planWith(), { ordinal: 1 });
    const [, badge, arrow, label] = result.overlays ?? [];

    expect(badge?.bounds.rect).toEqual([668, 318, 44, 44]);
    expect(arrow?.bounds.rect).toEqual([644, 332, 32, 16]);
    expect(label?.bounds.rect).toEqual([728, 320, 320, 40]);
    expect(label && 'resolved_side' in label ? label.resolved_side : null).toBe('right');
    expect(label && 'text' in label ? label.text : null).toBe('Add content');
  });

  it('gives every overlay an output-pixel bounding rect for the exclusion mask', () => {
    const result = resolveFrameOverlays(planWith(), { ordinal: 1 });

    for (const overlay of result.overlays ?? []) {
      expect(overlay.bounds.space).toBe('output-pixel');
      expect(overlay.bounds.rect).toHaveLength(4);
    }
  });

  it('resolves only the requested subset', () => {
    const result = resolveFrameOverlays(planWith(), { ordinal: 1, kinds: ['spotlight'] });

    expect(result.overlays).toHaveLength(1);
    expect(result.overlays?.[0]!.kind).toBe('spotlight');
  });
});

describe('resolveFrameOverlays placement rules', () => {
  it('falls back through the fixed side order when the preferred side does not fit', () => {
    const plan = planWith({
      anchored_rects: [anchored('add-content-button', [1000, 300, 240, 80])],
    });
    const result = resolveFrameOverlays(plan, { ordinal: 2 });
    const label = result.overlays?.find((overlay) => overlay.kind === 'label');

    expect(result.status).toBe('valid');
    expect(label && 'resolved_side' in label ? label.resolved_side : null).toBe('left');
  });

  it('never places an annotation over anchored evidence', () => {
    const plan = planWith({
      anchored_rects: [
        anchored('add-content-button', [400, 300, 240, 80]),
        anchored('media-tab', [660, 300, 300, 80]),
      ],
    });
    const result = resolveFrameOverlays(plan, { ordinal: 3 });
    const label = result.overlays?.find((overlay) => overlay.kind === 'label');

    expect(label && 'resolved_side' in label ? label.resolved_side : null).toBe('below');
    for (const overlay of result.overlays ?? []) {
      if (overlay.kind === 'spotlight' || overlay.kind === 'arrow') continue;
      const [x, y, width, height] = overlay.bounds.rect;
      for (const anchor of plan.anchored_rects) {
        const [ax, ay, aw, ah] = anchor.rect.rect;
        expect(x < ax + aw && ax < x + width && y < ay + ah && ay < y + height).toBe(false);
      }
    }
  });

  it('blocks rather than shrinking or shifting when no side has clearance', () => {
    const plan = planWith({
      output_width_px: 304,
      output_height_px: 171,
      anchored_rects: [anchored('add-content-button', [24, 49, 256, 72])],
    });
    const result = resolveFrameOverlays(plan, { ordinal: 1 });

    expect(result.status).toBe('blocked');
    expect(result.overlays).toBeNull();
    expect(result.blocker_reasons).toEqual([ANNOTATION_BLOCKER_REASONS.clearanceUnavailable]);
  });
});

describe('resolveFrameOverlays fail-closed behaviour', () => {
  it('blocks an unknown overlay kind', () => {
    const result = resolveFrameOverlays(planWith(), { ordinal: 1, kinds: ['spotlight', 'halo'] });

    expect(result.blocker_reasons).toEqual([ANNOTATION_BLOCKER_REASONS.unknownOverlayKind]);
  });

  it('blocks a requested inset instead of dropping it silently', () => {
    const result = resolveFrameOverlays(planWith(), { ordinal: 1, kinds: ['inset'] });

    expect(result.overlays).toBeNull();
    expect(result.blocker_reasons).toEqual([ANNOTATION_BLOCKER_REASONS.unknownOverlayKind]);
  });

  it('blocks when the plan carries no anchored rect for the resolved target', () => {
    const plan = planWith({ resolved_target_region_id: 'missing-region' });
    const result = resolveFrameOverlays(plan, { ordinal: 1 });

    expect(result.blocker_reasons).toContain(ANNOTATION_BLOCKER_REASONS.targetRectMissing);
  });

  it('blocks a label with no text instead of inventing one', () => {
    const plan = planWith({
      annotation_intent: { target_region_id: 'add-content-button', label: null, preferred_side: 'right' },
    });
    const result = resolveFrameOverlays(plan, { ordinal: 1 });

    expect(result.blocker_reasons).toContain(ANNOTATION_BLOCKER_REASONS.labelTextMissing);
  });

  it('blocks an invalid badge ordinal', () => {
    const result = resolveFrameOverlays(planWith(), { ordinal: 0 });

    expect(result.blocker_reasons).toContain(ANNOTATION_BLOCKER_REASONS.badgeOrdinalInvalid);
  });
});
