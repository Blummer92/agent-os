import type { CaptureStatus, RgbaColor } from './captureEvidence';
import {
  RECT_CONVENTION,
  TUTORIAL_FRAME_PLAN_VERSION,
  type CompositingColourSpace,
  type OutputPixelRect,
  type OverlayKind,
  type RectConvention,
  type RenderMode,
  type ResamplerName,
  type SourcePixelRect,
  type SpotlightFalloffFunction,
  type TutorialFramePlan,
} from './framePlan';

/**
 * PPUX-VRL7 (#1484) Slice 3 exact-composite executor contract.
 *
 * An executor rasterizes a resolved plan and emits provenance. That is its
 * entire responsibility. It receives the plan, the source artifact, and the
 * approved exact assets, and it is given no capability with which to discover
 * anything else: no reference library, no capture evidence, no region
 * admission, no network or browser handle, and no callback that could answer a
 * question the plan failed to answer.
 *
 * This module defines the contract and admits a request as complete. It
 * performs no rasterization, decodes no artifact bytes, and validates no
 * report; report validation is the independent validator's job precisely
 * because an executor's account of its own work is not evidence.
 *
 * Provider neutrality is structural: no field here names a provider, service,
 * model, endpoint, or credential. Which executor implementation is bound is a
 * deployment concern that never enters a plan or canonical evidence.
 */

/** The complete set of operations an exact-composite executor may perform. */
export const EXACT_COMPOSITE_OPERATIONS = Object.freeze([
  'crop',
  'proportional-scale',
  'dim',
  'spotlight',
  'badge',
  'arrow',
  'label',
  'magnified-source-pixel-inset',
  'approved-exact-asset-placement',
] as const);

export type ExactCompositeOperation = (typeof EXACT_COMPOSITE_OPERATIONS)[number];

/**
 * Behaviours a production executor must never perform. Each one would move a
 * decision out of the plan and into the renderer, which is the failure this
 * architecture exists to prevent. They are recorded as data so the contract is
 * explicit and testable rather than prose an implementer may skim.
 */
export const FORBIDDEN_EXECUTOR_BEHAVIOURS = Object.freeze([
  'locate-targets',
  'detect-handles',
  'threshold-pixels',
  'scan-brightness',
  'infer-canvas-bounds',
  'estimate-geometry',
  'choose-framing',
  'move-annotations-for-aesthetics',
  'recover-missing-plan-values',
  'reconstruct-source-ui-or-artwork',
] as const);

export type ForbiddenExecutorBehaviour = (typeof FORBIDDEN_EXECUTOR_BEHAVIOURS)[number];

/**
 * An opaque artifact. Bytes are carried so an executor can read its source and
 * return its output; nothing in this module decodes, inspects, or reasons about
 * them. Identity is the SHA-256, which the validator binds against the real
 * artifact rather than trusting this record.
 */
export type ExactCompositeArtifact = Readonly<{
  sha256: string;
  width_px: number;
  height_px: number;
  bytes: Uint8Array;
}>;

export type ApprovedExactAsset = Readonly<{
  asset_id: string;
  asset_fingerprint: string;
  artifact: ExactCompositeArtifact;
}>;

export type ExactCompositeExecutionRequest = Readonly<{
  plan: TutorialFramePlan;
  source: ExactCompositeArtifact;
  assets: readonly ApprovedExactAsset[];
}>;

/* -------------------------------------------------------------------------
 * Provenance report
 * ---------------------------------------------------------------------- */

export const EXECUTOR_PROVENANCE_REPORT_VERSION = 'picture-perfect-executor-provenance-v1' as const;

export type ExecutedSpotlightRecord = Readonly<{
  overlay_id: string;
  boundary: OutputPixelRect;
  padding_px: number;
  falloff_px: number;
  falloff_function: SpotlightFalloffFunction;
}>;

export type ExecutedOverlayMask = Readonly<{
  overlay_id: string;
  kind: OverlayKind;
  bounds: OutputPixelRect;
}>;

export type ExecutedAssetPlacement = Readonly<{
  fill_id: string;
  asset_id: string;
  asset_fingerprint: string;
  destination: OutputPixelRect;
}>;

/**
 * Self-described process claims. None of these is verifiable through artifact
 * binding, internal consistency, or unique direct measurement, so none may ever
 * decide acceptance. A recovered spotlight estimate lives here rather than
 * beside the executed record for exactly that reason.
 */
export type ExecutorDiagnostics = Readonly<{
  executor_id: string | null;
  executor_version: string | null;
  narrative: string | null;
  elapsed_ms: number | null;
  step_trace: readonly string[] | null;
  recovered_spotlight_estimate: ExecutedSpotlightRecord | null;
}>;

/**
 * Versioned provenance. Every field outside `diagnostics` is authoritative:
 * verifiable by binding it to a real artifact, by internal consistency against
 * the plan, or by uniquely recoverable direct measurement.
 *
 * `generation_used: false` is an attestation, not proof. It is recorded because
 * a false attestation is itself evidence, but pixel fidelity remains the
 * correctness property and no attestation can substitute for it.
 */
export type ExecutorProvenanceReport = Readonly<{
  report_version: typeof EXECUTOR_PROVENANCE_REPORT_VERSION;
  rect_convention: RectConvention;
  source_sha256: string;
  source_width_px: number;
  source_height_px: number;
  plan_sha256: string;
  output_sha256: string;
  output_width_px: number;
  output_height_px: number;
  source_rect: SourcePixelRect;
  scale_x: number;
  scale_y: number;
  resampler: ResamplerName;
  compositing_colour_space: CompositingColourSpace;
  render_mode: RenderMode;
  generation_used: boolean;
  executed_dim_rgba: RgbaColor;
  executed_spotlight: ExecutedSpotlightRecord | null;
  overlay_masks: readonly ExecutedOverlayMask[];
  overlay_bleed_px: number;
  asset_placements: readonly ExecutedAssetPlacement[];
  diagnostics: ExecutorDiagnostics;
}>;

/** The authoritative field names, in report order. `diagnostics` is absent by design. */
export const AUTHORITATIVE_REPORT_FIELDS = Object.freeze([
  'report_version',
  'rect_convention',
  'source_sha256',
  'source_width_px',
  'source_height_px',
  'plan_sha256',
  'output_sha256',
  'output_width_px',
  'output_height_px',
  'source_rect',
  'scale_x',
  'scale_y',
  'resampler',
  'compositing_colour_space',
  'render_mode',
  'generation_used',
  'executed_dim_rgba',
  'executed_spotlight',
  'overlay_masks',
  'overlay_bleed_px',
  'asset_placements',
] as const);

export type AuthoritativeReportField = (typeof AUTHORITATIVE_REPORT_FIELDS)[number];

/** The diagnostic field names. None may decide acceptance. */
export const DIAGNOSTIC_REPORT_FIELDS = Object.freeze([
  'executor_id',
  'executor_version',
  'narrative',
  'elapsed_ms',
  'step_trace',
  'recovered_spotlight_estimate',
] as const);

export type DiagnosticReportField = (typeof DIAGNOSTIC_REPORT_FIELDS)[number];

export function isAuthoritativeReportField(field: string): field is AuthoritativeReportField {
  return (AUTHORITATIVE_REPORT_FIELDS as readonly string[]).includes(field);
}

export type ExactCompositeExecutionOutput = Readonly<{
  image: ExactCompositeArtifact;
  report: ExecutorProvenanceReport;
}>;

/**
 * The provider-neutral execution interface: `execute(plan, source, assets)`
 * yielding an image and its provenance. An implementation is bound outside this
 * module and is never named by a plan or by canonical instructional evidence.
 */
export type ExactCompositeExecutor = Readonly<{
  execute(request: ExactCompositeExecutionRequest): Promise<ExactCompositeExecutionOutput>;
}>;

/* -------------------------------------------------------------------------
 * Request admission
 * ---------------------------------------------------------------------- */

export const EXECUTOR_BLOCKER_REASONS = {
  planVersionUnsupported: 'executor-plan-version-unsupported',
  rectConventionUnsupported: 'executor-rect-convention-unsupported',
  sourceArtifactInvalid: 'executor-source-artifact-invalid',
  sourceRectOutOfBounds: 'executor-source-rect-out-of-bounds',
  outputGeometryInconsistent: 'executor-output-geometry-inconsistent',
  scaleInconsistent: 'executor-scale-inconsistent',
  overlayOutOfBounds: 'executor-overlay-out-of-bounds',
  assetUnavailable: 'executor-asset-unavailable',
  assetFingerprintMismatch: 'executor-asset-fingerprint-mismatch',
} as const;

export type ExecutorBlockerReason =
  (typeof EXECUTOR_BLOCKER_REASONS)[keyof typeof EXECUTOR_BLOCKER_REASONS];

export type ExecutionAdmissionResult = Readonly<{
  status: CaptureStatus;
  request: ExactCompositeExecutionRequest | null;
  blocker_reasons: readonly ExecutorBlockerReason[];
}>;

/** Geometry is integer; scale is an exact rational, compared within this slack. */
const SCALE_EPSILON = 1e-9;

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

/**
 * Admit an execution request as complete, or fail closed.
 *
 * An executor may not recover a missing plan value, so a plan that does not
 * fully determine the frame must be rejected before execution rather than
 * repaired during it. Admission is a completeness gate only: it grants no
 * execution authority, and passing it does not make a plan authorized to run.
 */
export function admitExecutionRequest(request: ExactCompositeExecutionRequest): ExecutionAdmissionResult {
  const { plan, source, assets } = request;
  const reasons = new Set<ExecutorBlockerReason>();

  if (plan.plan_version !== TUTORIAL_FRAME_PLAN_VERSION) {
    reasons.add(EXECUTOR_BLOCKER_REASONS.planVersionUnsupported);
  }
  if (plan.rect_convention !== RECT_CONVENTION) {
    reasons.add(EXECUTOR_BLOCKER_REASONS.rectConventionUnsupported);
  }
  if (!source.sha256.trim() || !isPositiveInteger(source.width_px) || !isPositiveInteger(source.height_px)) {
    reasons.add(EXECUTOR_BLOCKER_REASONS.sourceArtifactInvalid);
  }

  const [sourceX, sourceY, sourceWidth, sourceHeight] = plan.source_rect.rect;
  if (
    plan.source_rect.space !== 'source-pixel' ||
    ![sourceX, sourceY].every((value) => Number.isInteger(value) && value >= 0) ||
    !isPositiveInteger(sourceWidth) || !isPositiveInteger(sourceHeight) ||
    sourceX + sourceWidth > source.width_px || sourceY + sourceHeight > source.height_px
  ) {
    reasons.add(EXECUTOR_BLOCKER_REASONS.sourceRectOutOfBounds);
  }

  if (
    !isPositiveInteger(plan.output_width_px) || !isPositiveInteger(plan.output_height_px) ||
    plan.output_width_px * plan.output_aspect.height !== plan.output_height_px * plan.output_aspect.width
  ) {
    reasons.add(EXECUTOR_BLOCKER_REASONS.outputGeometryInconsistent);
  }

  if (
    plan.scale_x !== plan.scale_y ||
    Math.abs(sourceWidth * plan.scale_x - plan.output_width_px) > SCALE_EPSILON ||
    Math.abs(sourceHeight * plan.scale_y - plan.output_height_px) > SCALE_EPSILON
  ) {
    reasons.add(EXECUTOR_BLOCKER_REASONS.scaleInconsistent);
  }

  for (const overlay of plan.overlays) {
    const [x, y, width, height] = overlay.bounds.rect;
    if (x < 0 || y < 0 || x + width > plan.output_width_px || y + height > plan.output_height_px) {
      reasons.add(EXECUTOR_BLOCKER_REASONS.overlayOutOfBounds);
    }
  }

  for (const fill of plan.asset_fills) {
    const supplied = assets.find((asset) => asset.asset_id === fill.asset_id);
    if (!supplied) {
      reasons.add(EXECUTOR_BLOCKER_REASONS.assetUnavailable);
      continue;
    }
    if (supplied.asset_fingerprint !== fill.asset_fingerprint) {
      reasons.add(EXECUTOR_BLOCKER_REASONS.assetFingerprintMismatch);
    }
  }

  if (reasons.size > 0) {
    return { status: 'blocked', request: null, blocker_reasons: [...reasons] };
  }
  return { status: 'valid', request, blocker_reasons: [] };
}
