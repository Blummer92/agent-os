import type { CaptureStatus, RgbaColor } from './captureEvidence';
import {
  EXECUTOR_PROVENANCE_REPORT_VERSION,
  type ExecutorProvenanceReport,
} from './executorContract';
import { RECT_CONVENTION, type RectXywh, type TutorialFramePlan } from './framePlan';
import {
  blendChannel,
  cropImage,
  dimImage,
  getPixel,
  imageSha256,
  placeAsset,
  planSha256,
  scaleImage,
  type RgbaImage,
  type SpotlightSpec,
} from './exactCompositePrimitives';

/**
 * PPUX-VRL7 (#1484) Gate B -- report integrity.
 *
 * Gate B decides whether a provenance report can be believed at all. It binds
 * every declared identity to the artifact that actually exists, checks the
 * report against the plan it claims to have executed, and recovers the one
 * measurement that is uniquely determined by the pixels. It never scores,
 * recognises, or interprets image content, and it never treats a diagnostic
 * field as evidence.
 *
 * Gate A -- forward pixel-fidelity comparison -- is a separate gate and is not
 * implemented here. Both must pass.
 */

export const DEFAULT_EXCLUSION_BUDGET = 0.15;

/** Alpha is recovered from quantized 8-bit channels, so it lands near, not on. */
const DIM_ALPHA_TOLERANCE = 0.02;

/** A sample is only well-conditioned when source and dim colours differ enough. */
const MIN_CHANNEL_SEPARATION = 32;

export const GATE_B_BLOCKER_REASONS = {
  reportVersionUnsupported: 'gate-b-report-version-unsupported',
  rectConventionMismatch: 'gate-b-rect-convention-mismatch',
  sourceDigestMismatch: 'gate-b-source-digest-mismatch',
  outputDigestMismatch: 'gate-b-output-digest-mismatch',
  planDigestMismatch: 'gate-b-plan-digest-mismatch',
  sourceDimensionsMismatch: 'gate-b-source-dimensions-mismatch',
  outputDimensionsMismatch: 'gate-b-output-dimensions-mismatch',
  renderModeMismatch: 'gate-b-render-mode-mismatch',
  sourceRectMismatch: 'gate-b-source-rect-mismatch',
  sourceRectOutOfBounds: 'gate-b-source-rect-out-of-bounds',
  scaleMismatch: 'gate-b-scale-mismatch',
  resamplerMismatch: 'gate-b-resampler-mismatch',
  colourSpaceMismatch: 'gate-b-colour-space-mismatch',
  dimValueMismatch: 'gate-b-dim-value-mismatch',
  overlayBleedMismatch: 'gate-b-overlay-bleed-mismatch',
  overlayMaskMismatch: 'gate-b-overlay-mask-mismatch',
  spotlightRecordMismatch: 'gate-b-spotlight-record-mismatch',
  assetPlacementMismatch: 'gate-b-asset-placement-mismatch',
  exclusionBudgetExceeded: 'gate-b-exclusion-budget-exceeded',
  dimAlphaUnrecoverable: 'gate-b-dim-alpha-unrecoverable',
  dimAlphaMismatch: 'gate-b-dim-alpha-mismatch',
  generationAttested: 'gate-b-generation-attested',
} as const;

export type GateBBlockerReason =
  (typeof GATE_B_BLOCKER_REASONS)[keyof typeof GATE_B_BLOCKER_REASONS];

export type ExclusionMask = Readonly<{
  width: number;
  height: number;
  /** One byte per pixel: 1 excluded, 0 compared. */
  excluded: Uint8Array;
  excluded_fraction: number;
}>;

export type GateBInput = Readonly<{
  plan: TutorialFramePlan;
  report: ExecutorProvenanceReport;
  source: RgbaImage;
  output: RgbaImage;
}>;

export type GateBOptions = Readonly<{ exclusion_budget?: number }>;

export type GateBResult = Readonly<{
  status: CaptureStatus;
  passed: boolean;
  excluded_fraction: number;
  recovered_dim_alpha: number | null;
  blocker_reasons: readonly GateBBlockerReason[];
}>;

function sameRect(left: RectXywh, right: RectXywh): boolean {
  return left.every((value, index) => value === right[index]);
}

function sameColour(left: RgbaColor, right: RgbaColor): boolean {
  return left.every((value, index) => value === right[index]);
}

function markRect(mask: Uint8Array, width: number, height: number, rect: RectXywh, grow: number): void {
  const [x, y, rectWidth, rectHeight] = rect;
  const left = Math.max(0, x - grow);
  const top = Math.max(0, y - grow);
  const right = Math.min(width, x + rectWidth + grow);
  const bottom = Math.min(height, y + rectHeight + grow);
  for (let row = top; row < bottom; row += 1) {
    for (let column = left; column < right; column += 1) {
      mask[row * width + column] = 1;
    }
  }
}

/**
 * Build the exclusion mask from the plan, never from the report. A report that
 * understated its own overlays could otherwise shrink the very mask meant to
 * bound it.
 *
 * Non-spotlight overlays contribute their bounding rect dilated by
 * `overlay_bleed_px`, which covers anti-aliased edge bleed. The spotlight is
 * handled by its own rule and contributes only the band its dilation adds --
 * the ramp between the boundary and the boundary grown by `falloff_px`. Its
 * interior is exactly undimmed source and its exterior exactly fully dimmed, so
 * both reproduce exactly and excluding them would discard the source-derived
 * pixels most worth checking while spending the budget to do it.
 */
export function buildExclusionMask(plan: TutorialFramePlan): ExclusionMask {
  const width = plan.output_width_px;
  const height = plan.output_height_px;
  const excluded = new Uint8Array(width * height);

  for (const overlay of plan.overlays) {
    if (overlay.kind !== 'spotlight') {
      markRect(excluded, width, height, overlay.bounds.rect, plan.render_spec.overlay_bleed_px);
      continue;
    }
    // The band is built in isolation and then unioned in, so clearing the
    // spotlight interior can never erase another overlay's exclusion that
    // happens to fall inside it. The mask must not depend on overlay order.
    const band = new Uint8Array(width * height);
    markRect(band, width, height, overlay.boundary.rect, overlay.falloff_px);
    const [bx, by, bw, bh] = overlay.boundary.rect;
    for (let row = Math.max(0, by); row < Math.min(height, by + bh); row += 1) {
      for (let column = Math.max(0, bx); column < Math.min(width, bx + bw); column += 1) {
        band[row * width + column] = 0;
      }
    }
    for (let index = 0; index < excluded.length; index += 1) {
      if (band[index] === 1) excluded[index] = 1;
    }
  }

  let count = 0;
  for (const value of excluded) count += value;
  return { width, height, excluded, excluded_fraction: excluded.length === 0 ? 0 : count / excluded.length };
}

function isFullyDimmed(plan: TutorialFramePlan, x: number, y: number): boolean {
  for (const overlay of plan.overlays) {
    if (overlay.kind !== 'spotlight') continue;
    const [bx, by, bw, bh] = overlay.boundary.rect;
    const horizontal = Math.max(bx - x, x - (bx + bw - 1), 0);
    const vertical = Math.max(by - y, y - (by + bh - 1), 0);
    if (Math.max(horizontal, vertical) <= overlay.falloff_px) return false;
  }
  return true;
}

function insideAnyAssetFill(plan: TutorialFramePlan, x: number, y: number): boolean {
  return plan.asset_fills.some((fill) => {
    const [fx, fy, fw, fh] = fill.destination.rect;
    return x >= fx && x < fx + fw && y >= fy && y < fy + fh;
  });
}

type AlphaSample = Readonly<{ under: number; actual: number; dim: number }>;

/**
 * Solve the executed dim alpha over fully dimmed, non-excluded pixels.
 *
 * This is B3 direct measurement, not Gate A construction: only crop and the
 * declared resampler are applied, to recover each pixel's pre-dim value, and
 * the declared blend is then inverted numerically in the declared colour space.
 * The blend is monotonic in alpha for well-separated samples, so a bisection on
 * the mean residual converges to the one value the pixels admit. Solving in the
 * wrong colour space, or against a wrong declared alpha, does not converge to
 * the declared value -- which is exactly how both are caught.
 */
function recoverDimAlpha(input: GateBInput, mask: ExclusionMask): number | null {
  const { plan, report, source, output } = input;
  const cropped = cropImage(source, plan.source_rect.rect);
  const preDim = scaleImage(cropped, plan.output_width_px, plan.output_height_px, report.resampler);
  const dim = report.executed_dim_rgba;

  const samples: AlphaSample[] = [];
  for (let y = 0; y < output.height; y += 1) {
    for (let x = 0; x < output.width; x += 1) {
      if (mask.excluded[y * mask.width + x] === 1) continue;
      if (!isFullyDimmed(plan, x, y)) continue;
      if (insideAnyAssetFill(plan, x, y)) continue;
      const under = getPixel(preDim, x, y);
      const actual = getPixel(output, x, y);
      for (const channel of [0, 1, 2] as const) {
        if (Math.abs(under[channel] - dim[channel]) < MIN_CHANNEL_SEPARATION) continue;
        samples.push({ under: under[channel], actual: actual[channel], dim: dim[channel] });
      }
    }
  }
  if (samples.length === 0) return null;

  const meanResidual = (alpha: number): number => {
    let total = 0;
    for (const sample of samples) {
      total += blendChannel(sample.under, sample.dim, alpha, report.compositing_colour_space) - sample.actual;
    }
    return total / samples.length;
  };

  let low = 0;
  let high = 1;
  for (let iteration = 0; iteration < 40; iteration += 1) {
    const middle = (low + high) / 2;
    if (meanResidual(middle) > 0) low = middle;
    else high = middle;
  }
  return (low + high) / 2;
}

/**
 * Gate B. Returns `excluded_fraction` on every path, pass or fail, because the
 * budget is reported rather than merely enforced.
 */
export function validateReportIntegrity(input: GateBInput, options: GateBOptions = {}): GateBResult {
  const { plan, report, source, output } = input;
  const budget = options.exclusion_budget ?? DEFAULT_EXCLUSION_BUDGET;
  const mask = buildExclusionMask(plan);
  const reasons = new Set<GateBBlockerReason>();

  // B1 -- artifact binding.
  if (report.source_sha256 !== imageSha256(source)) reasons.add(GATE_B_BLOCKER_REASONS.sourceDigestMismatch);
  if (report.output_sha256 !== imageSha256(output)) reasons.add(GATE_B_BLOCKER_REASONS.outputDigestMismatch);
  if (report.plan_sha256 !== planSha256(plan)) reasons.add(GATE_B_BLOCKER_REASONS.planDigestMismatch);
  if (report.source_width_px !== source.width || report.source_height_px !== source.height) {
    reasons.add(GATE_B_BLOCKER_REASONS.sourceDimensionsMismatch);
  }
  if (
    report.output_width_px !== output.width || report.output_height_px !== output.height ||
    output.width !== plan.output_width_px || output.height !== plan.output_height_px
  ) {
    reasons.add(GATE_B_BLOCKER_REASONS.outputDimensionsMismatch);
  }

  // B2 -- internal consistency.
  if (report.report_version !== EXECUTOR_PROVENANCE_REPORT_VERSION) {
    reasons.add(GATE_B_BLOCKER_REASONS.reportVersionUnsupported);
  }
  if (report.rect_convention !== RECT_CONVENTION || report.rect_convention !== plan.rect_convention) {
    reasons.add(GATE_B_BLOCKER_REASONS.rectConventionMismatch);
  }
  if (report.render_mode !== plan.render_mode) reasons.add(GATE_B_BLOCKER_REASONS.renderModeMismatch);
  if (
    report.source_rect.space !== plan.source_rect.space ||
    !sameRect(report.source_rect.rect, plan.source_rect.rect)
  ) {
    reasons.add(GATE_B_BLOCKER_REASONS.sourceRectMismatch);
  }
  const [rectX, rectY, rectWidth, rectHeight] = report.source_rect.rect;
  if (rectX < 0 || rectY < 0 || rectX + rectWidth > source.width || rectY + rectHeight > source.height) {
    reasons.add(GATE_B_BLOCKER_REASONS.sourceRectOutOfBounds);
  }
  if (
    report.scale_x !== plan.scale_x || report.scale_y !== plan.scale_y ||
    Math.abs(rectWidth * report.scale_x - report.output_width_px) > 1e-9 ||
    Math.abs(rectHeight * report.scale_y - report.output_height_px) > 1e-9
  ) {
    reasons.add(GATE_B_BLOCKER_REASONS.scaleMismatch);
  }
  if (report.resampler !== plan.render_spec.resampler) reasons.add(GATE_B_BLOCKER_REASONS.resamplerMismatch);
  if (report.compositing_colour_space !== plan.render_spec.compositing_colour_space) {
    reasons.add(GATE_B_BLOCKER_REASONS.colourSpaceMismatch);
  }
  if (!sameColour(report.executed_dim_rgba, plan.render_spec.dim_rgba)) {
    reasons.add(GATE_B_BLOCKER_REASONS.dimValueMismatch);
  }
  if (report.overlay_bleed_px !== plan.render_spec.overlay_bleed_px) {
    reasons.add(GATE_B_BLOCKER_REASONS.overlayBleedMismatch);
  }
  if (report.generation_used) reasons.add(GATE_B_BLOCKER_REASONS.generationAttested);

  const plannedOverlays = plan.overlays.map((overlay) => `${overlay.overlay_id}:${overlay.kind}:${overlay.bounds.rect.join(',')}`);
  const reportedOverlays = report.overlay_masks.map((mask_) => `${mask_.overlay_id}:${mask_.kind}:${mask_.bounds.rect.join(',')}`);
  if (plannedOverlays.length !== reportedOverlays.length ||
    plannedOverlays.some((entry, index) => entry !== reportedOverlays[index])) {
    reasons.add(GATE_B_BLOCKER_REASONS.overlayMaskMismatch);
  }

  const plannedSpotlight = plan.overlays.find((overlay) => overlay.kind === 'spotlight') ?? null;
  const reportedSpotlight = report.executed_spotlight;
  if (Boolean(plannedSpotlight) !== Boolean(reportedSpotlight)) {
    reasons.add(GATE_B_BLOCKER_REASONS.spotlightRecordMismatch);
  } else if (plannedSpotlight && reportedSpotlight && plannedSpotlight.kind === 'spotlight') {
    if (
      reportedSpotlight.overlay_id !== plannedSpotlight.overlay_id ||
      !sameRect(reportedSpotlight.boundary.rect, plannedSpotlight.boundary.rect) ||
      reportedSpotlight.padding_px !== plannedSpotlight.padding_px ||
      reportedSpotlight.falloff_px !== plannedSpotlight.falloff_px ||
      reportedSpotlight.falloff_function !== plannedSpotlight.falloff_function
    ) {
      reasons.add(GATE_B_BLOCKER_REASONS.spotlightRecordMismatch);
    }
  }

  const plannedFills = plan.asset_fills.map((fill) => `${fill.fill_id}:${fill.asset_id}:${fill.asset_fingerprint}:${fill.destination.rect.join(',')}`);
  const reportedFills = report.asset_placements.map((placement) => `${placement.fill_id}:${placement.asset_id}:${placement.asset_fingerprint}:${placement.destination.rect.join(',')}`);
  if (plannedFills.length !== reportedFills.length ||
    plannedFills.some((entry, index) => entry !== reportedFills[index])) {
    reasons.add(GATE_B_BLOCKER_REASONS.assetPlacementMismatch);
  }

  if (mask.excluded_fraction > budget) reasons.add(GATE_B_BLOCKER_REASONS.exclusionBudgetExceeded);

  // B3 -- uniquely recoverable direct measurement.
  let recovered: number | null = null;
  if (report.output_width_px === output.width && report.output_height_px === output.height) {
    recovered = recoverDimAlpha(input, mask);
    if (recovered === null) reasons.add(GATE_B_BLOCKER_REASONS.dimAlphaUnrecoverable);
    else if (Math.abs(recovered - report.executed_dim_rgba[3]) > DIM_ALPHA_TOLERANCE) {
      reasons.add(GATE_B_BLOCKER_REASONS.dimAlphaMismatch);
    }
  }

  const blockers = [...reasons];
  return {
    status: blockers.length === 0 ? 'valid' : 'blocked',
    passed: blockers.length === 0,
    excluded_fraction: mask.excluded_fraction,
    recovered_dim_alpha: recovered,
    blocker_reasons: blockers,
  };
}

/* -------------------------------------------------------------------------
 * Gate A -- forward pixel fidelity
 * ---------------------------------------------------------------------- */

/**
 * Gate A never receives the provenance report. Expected pixels are constructed
 * from the source artifact and the resolved plan alone, so an executor's
 * account of its own work cannot influence what it is measured against, and the
 * output is never inverted to discover what it "must" have been.
 *
 * There is no feature detection, edge finding, thresholded recognition, text
 * extraction, structural similarity, or model scoring anywhere in this gate.
 * The only comparison is arithmetic difference per channel.
 */

export type PixelTolerance = Readonly<{
  max_abs_error: number;
  mean_abs_error: number;
  soft_threshold: number;
  max_fraction_above_soft_threshold: number;
}>;

/** A 1:1 frame with no resampling is copied arithmetic and must land on it. */
export const TIGHT_PIXEL_TOLERANCE: PixelTolerance = Object.freeze({
  max_abs_error: 1,
  mean_abs_error: 0.05,
  soft_threshold: 1,
  max_fraction_above_soft_threshold: 0.001,
});

/** Resampling admits implementation-legitimate rounding, bounded rather than open. */
export const RESAMPLED_PIXEL_TOLERANCE: PixelTolerance = Object.freeze({
  max_abs_error: 8,
  mean_abs_error: 1,
  soft_threshold: 4,
  max_fraction_above_soft_threshold: 0.02,
});

export const GATE_A_BLOCKER_REASONS = {
  outputDimensionsMismatch: 'gate-a-output-dimensions-mismatch',
  sourceRectOutOfBounds: 'gate-a-source-rect-out-of-bounds',
  assetUnavailable: 'gate-a-asset-unavailable',
  assetFingerprintMismatch: 'gate-a-asset-fingerprint-mismatch',
  exclusionBudgetExceeded: 'gate-a-exclusion-budget-exceeded',
  nothingComparable: 'gate-a-nothing-comparable',
  maxAbsErrorExceeded: 'gate-a-max-abs-error-exceeded',
  meanAbsErrorExceeded: 'gate-a-mean-abs-error-exceeded',
  softThresholdFractionExceeded: 'gate-a-soft-threshold-fraction-exceeded',
} as const;

export type GateABlockerReason =
  (typeof GATE_A_BLOCKER_REASONS)[keyof typeof GATE_A_BLOCKER_REASONS];

export type ChannelMetrics = Readonly<{
  max_abs_error: number;
  mean_abs_error: number;
  fraction_above_soft_threshold: number;
}>;

export type PixelFidelityMetrics = Readonly<{
  red: ChannelMetrics;
  green: ChannelMetrics;
  blue: ChannelMetrics;
}>;

export type GateAAsset = Readonly<{ image: RgbaImage; fingerprint: string }>;

export type GateAInput = Readonly<{
  plan: TutorialFramePlan;
  source: RgbaImage;
  output: RgbaImage;
  assets?: ReadonlyMap<string, GateAAsset>;
}>;

export type GateAOptions = Readonly<{
  exclusion_budget?: number;
  tolerance?: PixelTolerance;
}>;

export type GateAResult = Readonly<{
  status: CaptureStatus;
  passed: boolean;
  excluded_fraction: number;
  compared_pixels: number;
  tolerance: PixelTolerance;
  metrics: PixelFidelityMetrics | null;
  blocker_reasons: readonly GateABlockerReason[];
}>;

function spotlightSpecOf(plan: TutorialFramePlan): SpotlightSpec | null {
  for (const overlay of plan.overlays) {
    if (overlay.kind !== 'spotlight') continue;
    return {
      boundary: overlay.boundary.rect,
      falloff_px: overlay.falloff_px,
      falloff_function: overlay.falloff_function,
    };
  }
  return null;
}

/**
 * Construct the expected image in output coordinates, in the order #1484 fixes:
 * crop, declared resampler, fingerprint-verified asset placement, then dim in
 * the declared compositing colour space. Overlays are deliberately not painted
 * -- their pixels are excluded from comparison, so drawing them would only
 * invite a fixture's annotation style to masquerade as a fidelity requirement.
 */
export function constructExpectedImage(
  plan: TutorialFramePlan,
  source: RgbaImage,
  assets: ReadonlyMap<string, GateAAsset> = new Map(),
): RgbaImage {
  const cropped = cropImage(source, plan.source_rect.rect);
  const scaled = scaleImage(cropped, plan.output_width_px, plan.output_height_px, plan.render_spec.resampler);
  for (const fill of plan.asset_fills) {
    const asset = assets.get(fill.asset_id);
    if (!asset || asset.fingerprint !== fill.asset_fingerprint) continue;
    placeAsset(scaled, asset.image, fill.destination.rect);
  }
  return dimImage(
    scaled,
    plan.render_spec.dim_rgba,
    plan.render_spec.compositing_colour_space,
    spotlightSpecOf(plan),
  );
}

function emptyResult(
  reasons: readonly GateABlockerReason[],
  excludedFraction: number,
  tolerance: PixelTolerance,
): GateAResult {
  return {
    status: 'blocked',
    passed: false,
    excluded_fraction: excludedFraction,
    compared_pixels: 0,
    tolerance,
    metrics: null,
    blocker_reasons: reasons,
  };
}

/**
 * Gate A. Compares the produced output against the forward-constructed expected
 * image outside the exclusion mask, reporting all three required metrics per
 * channel: maximum absolute error, mean absolute error, and the fraction of
 * samples above a soft threshold. All three are reported whether or not the
 * gate passes, and `excluded_fraction` is always reported.
 *
 * Three metrics are required because each misses a different corruption on its
 * own: maximum error alone misses a diffuse low-amplitude edit, mean error
 * alone misses a small localized redraw, and a soft-threshold count alone
 * misses a single catastrophic pixel.
 */
export function validatePixelFidelity(input: GateAInput, options: GateAOptions = {}): GateAResult {
  const { plan, source, output } = input;
  const assets = input.assets ?? new Map<string, GateAAsset>();
  const budget = options.exclusion_budget ?? DEFAULT_EXCLUSION_BUDGET;
  const tolerance = options.tolerance ??
    (plan.render_spec.resampler === 'none' ? TIGHT_PIXEL_TOLERANCE : RESAMPLED_PIXEL_TOLERANCE);

  const mask = buildExclusionMask(plan);
  const reasons: GateABlockerReason[] = [];

  if (output.width !== plan.output_width_px || output.height !== plan.output_height_px) {
    return emptyResult([GATE_A_BLOCKER_REASONS.outputDimensionsMismatch], mask.excluded_fraction, tolerance);
  }
  const [rectX, rectY, rectWidth, rectHeight] = plan.source_rect.rect;
  if (rectX < 0 || rectY < 0 || rectX + rectWidth > source.width || rectY + rectHeight > source.height) {
    return emptyResult([GATE_A_BLOCKER_REASONS.sourceRectOutOfBounds], mask.excluded_fraction, tolerance);
  }
  for (const fill of plan.asset_fills) {
    const asset = assets.get(fill.asset_id);
    if (!asset) reasons.push(GATE_A_BLOCKER_REASONS.assetUnavailable);
    else if (asset.fingerprint !== fill.asset_fingerprint) reasons.push(GATE_A_BLOCKER_REASONS.assetFingerprintMismatch);
  }
  if (reasons.length > 0) return emptyResult([...new Set(reasons)], mask.excluded_fraction, tolerance);

  if (mask.excluded_fraction > budget) reasons.push(GATE_A_BLOCKER_REASONS.exclusionBudgetExceeded);

  const expected = constructExpectedImage(plan, source, assets);
  const maxima = [0, 0, 0];
  const totals = [0, 0, 0];
  const above = [0, 0, 0];
  let compared = 0;

  for (let y = 0; y < output.height; y += 1) {
    for (let x = 0; x < output.width; x += 1) {
      if (mask.excluded[y * mask.width + x] === 1) continue;
      compared += 1;
      const actual = getPixel(output, x, y);
      const predicted = getPixel(expected, x, y);
      for (const channel of [0, 1, 2] as const) {
        const error = Math.abs(actual[channel] - predicted[channel]);
        if (error > maxima[channel]!) maxima[channel] = error;
        totals[channel] += error;
        if (error > tolerance.soft_threshold) above[channel] += 1;
      }
    }
  }

  if (compared === 0) {
    return emptyResult([...new Set([...reasons, GATE_A_BLOCKER_REASONS.nothingComparable])], mask.excluded_fraction, tolerance);
  }

  const channelMetrics = (channel: 0 | 1 | 2): ChannelMetrics => ({
    max_abs_error: maxima[channel]!,
    mean_abs_error: totals[channel]! / compared,
    fraction_above_soft_threshold: above[channel]! / compared,
  });
  const metrics: PixelFidelityMetrics = {
    red: channelMetrics(0),
    green: channelMetrics(1),
    blue: channelMetrics(2),
  };

  for (const channel of [metrics.red, metrics.green, metrics.blue]) {
    if (channel.max_abs_error > tolerance.max_abs_error) reasons.push(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
    if (channel.mean_abs_error > tolerance.mean_abs_error) reasons.push(GATE_A_BLOCKER_REASONS.meanAbsErrorExceeded);
    if (channel.fraction_above_soft_threshold > tolerance.max_fraction_above_soft_threshold) {
      reasons.push(GATE_A_BLOCKER_REASONS.softThresholdFractionExceeded);
    }
  }

  const blockers = [...new Set(reasons)];
  return {
    status: blockers.length === 0 ? 'valid' : 'blocked',
    passed: blockers.length === 0,
    excluded_fraction: mask.excluded_fraction,
    compared_pixels: compared,
    tolerance,
    metrics,
    blocker_reasons: blockers,
  };
}
