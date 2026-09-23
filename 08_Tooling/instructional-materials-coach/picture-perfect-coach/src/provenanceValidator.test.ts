import { describe, expect, it } from 'vitest';
import {
  DEFAULT_EXCLUSION_BUDGET,
  GATE_A_BLOCKER_REASONS,
  GATE_B_BLOCKER_REASONS,
  RESAMPLED_PIXEL_TOLERANCE,
  TIGHT_PIXEL_TOLERANCE,
  buildExclusionMask,
  constructExpectedImage,
  validatePixelFidelity,
  validateReportIntegrity,
} from './provenanceValidator';
import {
  createFixtureSource,
  renderExactCompositeFixture,
  withDiffuseLowLevelEdit,
  withGlobalTint,
  withLocalizedRedraw,
  withLossyRequantization,
} from './fixtures/exactCompositeFixture';
import { createImage, imageSha256, planSha256, type RgbaImage } from './exactCompositePrimitives';
import type { ExecutorProvenanceReport } from './executorContract';
import {
  DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  RECT_CONVENTION,
  RECT_SPACES,
  RENDER_MODES,
  TUTORIAL_FRAME_PLAN_VERSION,
  type TutorialFramePlan,
} from './framePlan';

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
    source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 64, 36] },
    output_aspect: { width: 16, height: 9 },
    output_width_px: 64,
    output_height_px: 36,
    render_mode: RENDER_MODES.cropOnly,
    scale_x: 1,
    scale_y: 1,
    render_spec: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
    asset_fills: [],
    overlays: [
      {
        overlay_id: 'spotlight-1',
        kind: 'spotlight',
        bounds: { space: RECT_SPACES.outputPixel, rect: [18, 10, 20, 14] },
        region_id: 'add-content-button',
        boundary: { space: RECT_SPACES.outputPixel, rect: [20, 12, 16, 10] },
        padding_px: 2,
        falloff_px: 2,
        falloff_function: 'smoothstep',
      },
      {
        overlay_id: 'badge-1',
        kind: 'badge',
        bounds: { space: RECT_SPACES.outputPixel, rect: [46, 16, 6, 6] },
        ordinal: 1,
        centre_x_px: 49,
        centre_y_px: 19,
      },
    ],
    anchored_rects: [{ region_id: 'add-content-button', rect: { space: RECT_SPACES.outputPixel, rect: [20, 12, 16, 10] } }],
    must_show_region_ids: ['add-content-button'],
    annotation_intent: { target_region_id: 'add-content-button', label: 'Add content', preferred_side: 'right' },
    execution_authorized: false,
    ...overrides,
  };
}

const source = createFixtureSource(64, 36);
const plan = planWith();
const rendered = renderExactCompositeFixture(plan, source);
const output = rendered.image!;
const report = rendered.report!;

const reportWith = (overrides: Partial<ExecutorProvenanceReport>): ExecutorProvenanceReport => ({ ...report, ...overrides });
const check = (overrides: Partial<ExecutorProvenanceReport> = {}, image: RgbaImage = output) =>
  validateReportIntegrity({ plan, report: reportWith(overrides), source, output: image });

describe('exclusion mask', () => {
  it('excludes the spotlight ramp band but keeps its interior comparable', () => {
    const mask = buildExclusionMask(plan);
    const at = (x: number, y: number) => mask.excluded[y * mask.width + x];

    expect(at(28, 16)).toBe(0);
    expect(at(19, 11)).toBe(1);
    expect(at(0, 0)).toBe(0);
  });

  it('dilates non-spotlight overlays by the declared bleed', () => {
    const mask = buildExclusionMask(plan);
    const at = (x: number, y: number) => mask.excluded[y * mask.width + x];

    expect(at(48, 18)).toBe(1);
    expect(at(45, 15)).toBe(1);
    expect(at(42, 12)).toBe(0);
  });

  it('stays inside the default budget for a realistic frame', () => {
    expect(buildExclusionMask(plan).excluded_fraction).toBeLessThan(DEFAULT_EXCLUSION_BUDGET);
  });
});

describe('Gate B on a clean pair', () => {
  it('passes and recovers the executed dim alpha', () => {
    const result = validateReportIntegrity({ plan, report, source, output });

    expect(result.passed).toBe(true);
    expect(result.status).toBe('valid');
    expect(result.blocker_reasons).toEqual([]);
    expect(result.recovered_dim_alpha).toBeCloseTo(DEFAULT_EXACT_COMPOSITE_RENDER_SPEC.dim_rgba[3], 2);
  });

  it('always reports the excluded fraction, passing or failing', () => {
    expect(validateReportIntegrity({ plan, report, source, output }).excluded_fraction).toBeGreaterThan(0);
    expect(check({ generation_used: true }).excluded_fraction).toBeGreaterThan(0);
  });
});

describe('Gate B1 artifact binding', () => {
  it('binds the report to artifacts that actually exist', () => {
    expect(check({ source_sha256: 'f'.repeat(64) }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.sourceDigestMismatch);
    expect(check({ output_sha256: 'f'.repeat(64) }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.outputDigestMismatch);
    expect(check({ plan_sha256: 'f'.repeat(64) }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.planDigestMismatch);
  });

  it('rejects declared dimensions that the artifacts do not have', () => {
    expect(check({ output_width_px: 63 }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.outputDimensionsMismatch);
    expect(check({ source_height_px: 35 }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.sourceDimensionsMismatch);
  });

  it('rejects every Stage 5 corruption on identity alone', () => {
    const corruptions: readonly RgbaImage[] = [
      withLocalizedRedraw(output, [2, 2, 4, 4]),
      withGlobalTint(output, 6),
      withDiffuseLowLevelEdit(output, 2),
      withLossyRequantization(output, 8),
    ];

    for (const corrupted of corruptions) {
      expect(imageSha256(corrupted)).not.toBe(report.output_sha256);
      expect(check({}, corrupted).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.outputDigestMismatch);
    }
  });
});

describe('Gate B2 internal consistency', () => {
  it('rejects an unknown schema or rect convention', () => {
    expect(check({ report_version: 'provenance-v0' } as unknown as Partial<ExecutorProvenanceReport>).blocker_reasons)
      .toContain(GATE_B_BLOCKER_REASONS.reportVersionUnsupported);
    expect(check({ rect_convention: 'ltrb' } as unknown as Partial<ExecutorProvenanceReport>).blocker_reasons)
      .toContain(GATE_B_BLOCKER_REASONS.rectConventionMismatch);
  });

  it('requires executed geometry to equal the planned geometry', () => {
    expect(check({ render_mode: RENDER_MODES.integerScale }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.renderModeMismatch);
    expect(check({ source_rect: { space: RECT_SPACES.sourcePixel, rect: [1, 0, 64, 36] } }).blocker_reasons)
      .toContain(GATE_B_BLOCKER_REASONS.sourceRectMismatch);
    expect(check({ scale_x: 2, scale_y: 2 }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.scaleMismatch);
  });

  it('requires executed plan-controlled values to equal their planned counterparts', () => {
    expect(check({ resampler: 'bilinear' }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.resamplerMismatch);
    expect(check({ compositing_colour_space: 'linear' }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.colourSpaceMismatch);
    expect(check({ executed_dim_rgba: [0, 0, 0, 0.65] }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.dimValueMismatch);
    expect(check({ overlay_bleed_px: 5 }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.overlayBleedMismatch);
  });

  it('requires masks, spotlight, and placements to match the plan', () => {
    expect(check({ overlay_masks: report.overlay_masks.slice(0, 1) }).blocker_reasons)
      .toContain(GATE_B_BLOCKER_REASONS.overlayMaskMismatch);
    expect(check({ executed_spotlight: null }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.spotlightRecordMismatch);
    expect(check({
      executed_spotlight: { ...report.executed_spotlight!, falloff_px: 9 },
    }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.spotlightRecordMismatch);
    expect(check({
      asset_placements: [{
        fill_id: 'ghost', asset_id: 'ghost', asset_fingerprint: 'sha256:ghost',
        destination: { space: RECT_SPACES.outputPixel, rect: [0, 0, 2, 2] },
      }],
    }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.assetPlacementMismatch);
  });

  it('rejects an attested generation on the exact-composite path', () => {
    expect(check({ generation_used: true }).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.generationAttested);
  });

  it('enforces the exclusion budget and stays configurable', () => {
    const tight = validateReportIntegrity({ plan, report, source, output }, { exclusion_budget: 0.05 });

    expect(tight.blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.exclusionBudgetExceeded);
    expect(tight.excluded_fraction).toBeGreaterThan(0.05);
  });
});

describe('Gate B3 direct measurement', () => {
  it('catches a wrong compositing colour space that is internally consistent', () => {
    const linearPlan = planWith({
      render_spec: { ...DEFAULT_EXACT_COMPOSITE_RENDER_SPEC, compositing_colour_space: 'linear' },
    });
    const result = validateReportIntegrity({
      plan: linearPlan,
      report: reportWith({ compositing_colour_space: 'linear', plan_sha256: planSha256(linearPlan) }),
      source,
      output,
    });

    expect(result.blocker_reasons).toEqual([GATE_B_BLOCKER_REASONS.dimAlphaMismatch]);
  });

  it('catches a wrong dim alpha declared in the same colour space', () => {
    const strongPlan = planWith({
      render_spec: { ...DEFAULT_EXACT_COMPOSITE_RENDER_SPEC, dim_rgba: [0, 0, 0, 0.8] },
    });
    const result = validateReportIntegrity({
      plan: strongPlan,
      report: reportWith({ executed_dim_rgba: [0, 0, 0, 0.8], plan_sha256: planSha256(strongPlan) }),
      source,
      output,
    });

    expect(result.blocker_reasons).toEqual([GATE_B_BLOCKER_REASONS.dimAlphaMismatch]);
    expect(result.recovered_dim_alpha).toBeCloseTo(0.55, 2);
  });
});

describe('Gate A on a clean pair', () => {
  it('matches the forward-constructed expected image exactly outside exclusions', () => {
    const result = validatePixelFidelity({ plan, source, output });

    expect(result.passed).toBe(true);
    expect(result.status).toBe('valid');
    expect(result.blocker_reasons).toEqual([]);
    expect(result.compared_pixels).toBeGreaterThan(0);
    for (const channel of [result.metrics!.red, result.metrics!.green, result.metrics!.blue]) {
      expect(channel.max_abs_error).toBe(0);
      expect(channel.mean_abs_error).toBe(0);
      expect(channel.fraction_above_soft_threshold).toBe(0);
    }
  });

  it('selects the tight band with no resampling and always reports the excluded fraction', () => {
    const result = validatePixelFidelity({ plan, source, output });

    expect(result.tolerance).toEqual(TIGHT_PIXEL_TOLERANCE);
    expect(result.excluded_fraction).toBeGreaterThan(0);
    expect(result.excluded_fraction).toBeLessThan(DEFAULT_EXCLUSION_BUDGET);
  });

  it('constructs the expected image deterministically from source and plan alone', () => {
    const first = constructExpectedImage(plan, source);
    const second = constructExpectedImage(plan, source);

    expect(Array.from(first.data)).toEqual(Array.from(second.data));
    expect(imageSha256(first)).not.toBe(imageSha256(output));
  });

  it('applies the looser bounded band when the plan requires resampling', () => {
    const scaledPlan = planWith({
      source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 32, 18] },
      render_mode: RENDER_MODES.integerScale,
      scale_x: 2,
      scale_y: 2,
      render_spec: { ...DEFAULT_EXACT_COMPOSITE_RENDER_SPEC, resampler: 'nearest' },
    });
    const scaled = renderExactCompositeFixture(scaledPlan, source);
    const result = validatePixelFidelity({ plan: scaledPlan, source, output: scaled.image! });

    expect(result.tolerance).toEqual(RESAMPLED_PIXEL_TOLERANCE);
    expect(result.passed).toBe(true);
  });
});

describe('Gate A pixel corruption detection', () => {
  const fidelity = (image: RgbaImage) => validatePixelFidelity({ plan, source, output: image });

  it('rejects a small localized redraw', () => {
    const result = fidelity(withLocalizedRedraw(output, [2, 2, 4, 4]));

    expect(result.passed).toBe(false);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.softThresholdFractionExceeded);
  });

  it('rejects a global tint', () => {
    const result = fidelity(withGlobalTint(output, 6));

    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.meanAbsErrorExceeded);
  });

  it('rejects a diffuse low-amplitude edit that no single metric would catch alone', () => {
    const result = fidelity(withDiffuseLowLevelEdit(output, 2));

    expect(result.metrics!.red.max_abs_error).toBeLessThanOrEqual(2);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.meanAbsErrorExceeded);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.softThresholdFractionExceeded);
  });

  it('rejects a lossy re-encode against the tight native-artifact band', () => {
    const result = fidelity(withLossyRequantization(output, 8));

    expect(result.passed).toBe(false);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
  });

  it('reports all three metrics per channel even when it fails', () => {
    const result = fidelity(withGlobalTint(output, 6));

    for (const channel of [result.metrics!.red, result.metrics!.green, result.metrics!.blue]) {
      expect(channel.max_abs_error).toBeGreaterThan(0);
      expect(channel.mean_abs_error).toBeGreaterThan(0);
      expect(channel.fraction_above_soft_threshold).toBeGreaterThan(0);
    }
  });

  it('rejects a frame dimmed in a different colour space than the plan declares', () => {
    const linearPlan = planWith({
      render_spec: { ...DEFAULT_EXACT_COMPOSITE_RENDER_SPEC, compositing_colour_space: 'linear' },
    });
    const result = validatePixelFidelity({ plan: linearPlan, source, output });

    expect(result.passed).toBe(false);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
  });
});

describe('Gate A fail-closed inputs', () => {
  it('blocks output dimensions that do not match the plan', () => {
    const result = validatePixelFidelity({ plan, source, output: createImage(63, 36, [0, 0, 0, 1]) });

    expect(result.blocker_reasons).toEqual([GATE_A_BLOCKER_REASONS.outputDimensionsMismatch]);
    expect(result.metrics).toBeNull();
  });

  it('blocks a source rect outside the source artifact', () => {
    const wide = planWith({ source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 128, 72] } });
    const result = validatePixelFidelity({ plan: wide, source, output });

    expect(result.blocker_reasons).toEqual([GATE_A_BLOCKER_REASONS.sourceRectOutOfBounds]);
  });

  it('blocks an unavailable or unverified asset instead of composing without it', () => {
    const withAsset = planWith({
      asset_fills: [{
        fill_id: 'fill-1',
        asset_id: 'callout',
        asset_fingerprint: 'sha256:callout',
        destination: { space: RECT_SPACES.outputPixel, rect: [4, 4, 2, 2] },
      }],
    });

    expect(validatePixelFidelity({ plan: withAsset, source, output }).blocker_reasons)
      .toEqual([GATE_A_BLOCKER_REASONS.assetUnavailable]);
    expect(validatePixelFidelity({
      plan: withAsset,
      source,
      output,
      assets: new Map([['callout', { image: createImage(2, 2, [1, 2, 3, 1]), fingerprint: 'sha256:recaptured' }]]),
    }).blocker_reasons).toEqual([GATE_A_BLOCKER_REASONS.assetFingerprintMismatch]);
  });

  it('enforces the exclusion budget it reports', () => {
    const result = validatePixelFidelity({ plan, source, output }, { exclusion_budget: 0.05 });

    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.exclusionBudgetExceeded);
    expect(result.excluded_fraction).toBeGreaterThan(0.05);
  });
});
