import { describe, expect, it } from 'vitest';
import {
  DEFAULT_EXCLUSION_BUDGET,
  GATE_A_BLOCKER_REASONS,
  GATE_B_BLOCKER_REASONS,
  RESAMPLED_PIXEL_TOLERANCE,
  TIGHT_PIXEL_TOLERANCE,
  buildExclusionMask,
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
import { planSha256, type RgbaImage } from './exactCompositePrimitives';
import type { ExecutorProvenanceReport } from './executorContract';
import {
  DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  RECT_CONVENTION,
  RECT_SPACES,
  RENDER_MODES,
  TUTORIAL_FRAME_PLAN_VERSION,
  type FrameOverlay,
  type TutorialFramePlan,
} from './framePlan';

/**
 * PPUX-VRL7 (#1484) mandatory validator fixture and corruption suite.
 *
 * Eighteen cases prove the two gates before any external executor is trusted:
 * a clean pair must pass both, and every corruption must fail for its own
 * reason rather than merely failing. Several cases exist specifically to show
 * that neither gate subsumes the other -- a tampered report is invisible to
 * pixel comparison, and a tampered image is invisible to report consistency.
 */

const spotlight: FrameOverlay = {
  overlay_id: 'spotlight-1',
  kind: 'spotlight',
  bounds: { space: RECT_SPACES.outputPixel, rect: [18, 10, 20, 14] },
  region_id: 'add-content-button',
  boundary: { space: RECT_SPACES.outputPixel, rect: [20, 12, 16, 10] },
  padding_px: 2,
  falloff_px: 2,
  falloff_function: 'smoothstep',
};

const badge: FrameOverlay = {
  overlay_id: 'badge-1',
  kind: 'badge',
  bounds: { space: RECT_SPACES.outputPixel, rect: [46, 16, 6, 6] },
  ordinal: 1,
  centre_x_px: 49,
  centre_y_px: 19,
};

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
    overlays: [spotlight, badge],
    anchored_rects: [{ region_id: 'add-content-button', rect: { space: RECT_SPACES.outputPixel, rect: [20, 12, 16, 10] } }],
    must_show_region_ids: ['add-content-button'],
    annotation_intent: { target_region_id: 'add-content-button', label: 'Add content', preferred_side: 'right' },
    execution_authorized: false,
    ...overrides,
  };
}

const source = createFixtureSource(64, 36);
const plan = planWith();
const clean = renderExactCompositeFixture(plan, source);
const output = clean.image!;
const report = clean.report!;

const gateA = (image: RgbaImage = output, target: TutorialFramePlan = plan, artifact: RgbaImage = source) =>
  validatePixelFidelity({ plan: target, source: artifact, output: image });
const gateB = (overrides: Partial<ExecutorProvenanceReport> = {}, image: RgbaImage = output) =>
  validateReportIntegrity({ plan, report: { ...report, ...overrides }, source, output: image });

describe('#1484 validator suite — positive controls', () => {
  it('case 1: a clean pair passes both gates', () => {
    expect(gateA().passed).toBe(true);
    expect(gateB().passed).toBe(true);
    expect(gateB().blocker_reasons).toEqual([]);
  });

  it('case 10: a 1:1 no-resample frame passes on the tight band with zero error', () => {
    const result = gateA();

    expect(result.tolerance).toEqual(TIGHT_PIXEL_TOLERANCE);
    expect(result.metrics!.red.max_abs_error).toBe(0);
    expect(result.metrics!.green.max_abs_error).toBe(0);
    expect(result.metrics!.blue.max_abs_error).toBe(0);
  });

  it('case 11: a fractional resample passes under the looser bounded tolerance', () => {
    const fractional = planWith({
      source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 27, 18] },
      output_aspect: { width: 3, height: 2 },
      output_width_px: 39,
      output_height_px: 26,
      render_mode: RENDER_MODES.fractionalScale,
      scale_x: 13 / 9,
      scale_y: 13 / 9,
      render_spec: { ...DEFAULT_EXACT_COMPOSITE_RENDER_SPEC, resampler: 'bilinear' },
      overlays: [
        { ...spotlight, bounds: { space: RECT_SPACES.outputPixel, rect: [13, 9, 10, 8] }, boundary: { space: RECT_SPACES.outputPixel, rect: [14, 10, 8, 6] }, falloff_px: 1 },
        { ...badge, bounds: { space: RECT_SPACES.outputPixel, rect: [32, 11, 4, 4] } },
      ],
      anchored_rects: [{ region_id: 'add-content-button', rect: { space: RECT_SPACES.outputPixel, rect: [14, 10, 8, 6] } }],
    });
    const rendered = renderExactCompositeFixture(fractional, source);
    const fidelity = gateA(rendered.image!, fractional);

    expect(rendered.status).toBe('valid');
    expect(fidelity.tolerance).toEqual(RESAMPLED_PIXEL_TOLERANCE);
    expect(fidelity.passed).toBe(true);
    expect(validateReportIntegrity({ plan: fractional, report: rendered.report!, source, output: rendered.image! }).passed).toBe(true);
  });
});

describe('#1484 validator suite — pixel corruption', () => {
  it('case 2: a tiny localized redraw fails Gate A on max error and soft-threshold count', () => {
    const result = gateA(withLocalizedRedraw(output, [2, 2, 4, 4]));

    expect(result.passed).toBe(false);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.softThresholdFractionExceeded);
  });

  it('case 3: a global tint fails Gate A on max and mean error', () => {
    const corrupted = withGlobalTint(output, 6);

    expect(gateA(corrupted).blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
    expect(gateA(corrupted).blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.meanAbsErrorExceeded);
    expect(gateB({}, corrupted).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.outputDigestMismatch);
  });

  it('case 4: diffuse low-level edits fail on mean and soft-threshold despite a small maximum', () => {
    const result = gateA(withDiffuseLowLevelEdit(output, 2));

    expect(result.metrics!.red.max_abs_error).toBeLessThanOrEqual(2);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.meanAbsErrorExceeded);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.softThresholdFractionExceeded);
  });

  it('case 9: a change outside the mask fails Gate A, while an identical change inside it does not', () => {
    const outside = gateA(withLocalizedRedraw(output, [0, 0, 2, 2]));
    const inside = gateA(withLocalizedRedraw(output, [47, 17, 2, 2]));

    expect(outside.passed).toBe(false);
    expect(outside.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
    expect(inside.passed).toBe(true);
    expect(gateB({}, withLocalizedRedraw(output, [47, 17, 2, 2])).blocker_reasons)
      .toContain(GATE_B_BLOCKER_REASONS.outputDigestMismatch);
  });

  it('case 18: a lossy re-encode fails the tight native-artifact band', () => {
    const result = gateA(withLossyRequantization(output, 8));

    expect(result.tolerance).toEqual(TIGHT_PIXEL_TOLERANCE);
    expect(result.passed).toBe(false);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
  });
});

describe('#1484 validator suite — report integrity', () => {
  it('case 5: a wrong source SHA fails Gate B and is invisible to Gate A', () => {
    expect(gateB({ source_sha256: 'f'.repeat(64) }).blocker_reasons).toEqual([GATE_B_BLOCKER_REASONS.sourceDigestMismatch]);
    expect(gateA().passed).toBe(true);
  });

  it('case 6: a wrong plan SHA fails Gate B and is invisible to Gate A', () => {
    expect(gateB({ plan_sha256: 'f'.repeat(64) }).blocker_reasons).toEqual([GATE_B_BLOCKER_REASONS.planDigestMismatch]);
    expect(gateA().passed).toBe(true);
  });

  it('case 7: a wrong output SHA fails Gate B and is invisible to Gate A', () => {
    expect(gateB({ output_sha256: 'f'.repeat(64) }).blocker_reasons).toEqual([GATE_B_BLOCKER_REASONS.outputDigestMismatch]);
    expect(gateA().passed).toBe(true);
  });

  it('case 16: a rect-convention mismatch fails Gate B', () => {
    const result = gateB({ rect_convention: 'ltrb' } as unknown as Partial<ExecutorProvenanceReport>);

    expect(result.blocker_reasons).toEqual([GATE_B_BLOCKER_REASONS.rectConventionMismatch]);
    expect(gateA().passed).toBe(true);
  });

  it('case 17: a one-pixel source-rect offset is caught by report consistency and by pixel comparison', () => {
    expect(gateB({ source_rect: { space: RECT_SPACES.sourcePixel, rect: [1, 0, 64, 36] } }).blocker_reasons)
      .toContain(GATE_B_BLOCKER_REASONS.sourceRectMismatch);

    const wideSource = createFixtureSource(66, 36);
    const offsetPlan = planWith({ source_rect: { space: RECT_SPACES.sourcePixel, rect: [1, 0, 64, 36] } });
    const offsetOutput = renderExactCompositeFixture(offsetPlan, wideSource).image!;
    const result = gateA(offsetOutput, planWith(), wideSource);

    expect(result.passed).toBe(false);
    expect(result.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
  });
});

describe('#1484 validator suite — exclusion mask and budget', () => {
  it('case 8: over-budget exclusions fail both gates and report the fraction', () => {
    const wideLabel: FrameOverlay = {
      overlay_id: 'label-1',
      kind: 'label',
      bounds: { space: RECT_SPACES.outputPixel, rect: [0, 0, 44, 28] },
      text: 'Add content',
      preferred_side: 'right',
      resolved_side: 'right',
    };
    const heavy = planWith({ overlays: [wideLabel, spotlight, badge] });
    const rendered = renderExactCompositeFixture(heavy, source);
    const fidelity = validatePixelFidelity({ plan: heavy, source, output: rendered.image! });
    const integrity = validateReportIntegrity({ plan: heavy, report: rendered.report!, source, output: rendered.image! });

    expect(buildExclusionMask(heavy).excluded_fraction).toBeGreaterThan(DEFAULT_EXCLUSION_BUDGET);
    expect(fidelity.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.exclusionBudgetExceeded);
    expect(integrity.blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.exclusionBudgetExceeded);
    expect(fidelity.excluded_fraction).toBeGreaterThan(DEFAULT_EXCLUSION_BUDGET);
  });

  it('case 12: a change inside the spotlight falloff band is excluded from Gate A', () => {
    const corrupted = withLocalizedRedraw(output, [19, 11, 1, 1]);

    expect(buildExclusionMask(plan).excluded[11 * 64 + 19]).toBe(1);
    expect(gateA(corrupted).passed).toBe(true);
    expect(gateB({}, corrupted).blocker_reasons).toContain(GATE_B_BLOCKER_REASONS.outputDigestMismatch);
  });

  it('case 13: overlay anti-aliasing bleed is excluded, and anything beyond it is not', () => {
    const withinBleed = withLocalizedRedraw(output, [45, 15, 1, 1]);
    const beyondBleed = withLocalizedRedraw(output, [42, 12, 1, 1]);

    expect(gateA(withinBleed).passed).toBe(true);
    expect(gateA(beyondBleed).passed).toBe(false);
    expect(gateA(beyondBleed).blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
  });
});

describe('#1484 validator suite — colour space and dim', () => {
  it('case 14: a wrong compositing colour space fails both gates', () => {
    const linearPlan = planWith({
      render_spec: { ...DEFAULT_EXACT_COMPOSITE_RENDER_SPEC, compositing_colour_space: 'linear' },
    });
    const integrity = validateReportIntegrity({
      plan: linearPlan,
      report: { ...report, compositing_colour_space: 'linear', plan_sha256: planSha256(linearPlan) },
      source,
      output,
    });

    expect(gateA(output, linearPlan).blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
    expect(integrity.blocker_reasons).toEqual([GATE_B_BLOCKER_REASONS.dimAlphaMismatch]);
  });

  it('case 15: a wrong dim alpha in the same colour space fails both gates', () => {
    const strongPlan = planWith({
      render_spec: { ...DEFAULT_EXACT_COMPOSITE_RENDER_SPEC, dim_rgba: [0, 0, 0, 0.8] },
    });
    const integrity = validateReportIntegrity({
      plan: strongPlan,
      report: { ...report, executed_dim_rgba: [0, 0, 0, 0.8], plan_sha256: planSha256(strongPlan) },
      source,
      output,
    });

    expect(gateA(output, strongPlan).blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
    expect(integrity.blocker_reasons).toEqual([GATE_B_BLOCKER_REASONS.dimAlphaMismatch]);
    expect(integrity.recovered_dim_alpha).toBeCloseTo(0.55, 2);
  });
});
