import type { CaptureStatus, RgbaColor } from './captureEvidence';
import {
  admitReferenceRegions,
  selectVisualReference,
  type ReferenceRegion,
  type ReferenceRegionSet,
  type VisualReferenceBlockerReason,
  type VisualReferenceLibrary,
  type VisualReferenceSelectionRequest,
} from './visualReference';

/**
 * PPUX-VRL7 (#1484) Slice 3 exact-composite frame-plan data contract.
 *
 * A `TutorialFramePlan` is a provider-neutral, fully resolved rasterization
 * instruction: everything an `ExactCompositeExecutor` needs to produce one
 * tutorial frame from approved source pixels, and nothing that would let it
 * decide anything. Provider or service identity never appears here, and never
 * enters canonical instructional evidence.
 *
 * This module is types and deterministic constants only. Plan construction,
 * blocker vocabulary, target resolution, framing derivation, and overlay
 * resolution are not implemented here.
 */

/* -------------------------------------------------------------------------
 * Rectangle space tagging
 * ---------------------------------------------------------------------- */

/**
 * The repository has exactly one rectangle ordering, `[x, y, width, height]`,
 * already shared by `TargetGeometry`, `TargetStyleEvidence.rect_normalized`
 * (`./captureEvidence`) and `ReferenceRegion.rect` (`./visualReference`, #1485).
 * #1484 introduces no second ordering.
 */
export const RECT_CONVENTION = 'xywh' as const;
export type RectConvention = typeof RECT_CONVENTION;

export type RectXywh = readonly [number, number, number, number];

/**
 * What differs between rectangles is the coordinate space, not the ordering,
 * and #1485 records that the spaces are numerically indistinguishable by rect
 * shape alone. Tagging makes the space a compile-time property so a
 * reference-normalized region rect can never be silently consumed where output
 * pixels are required, and so a rect-convention/space mismatch is a type error
 * rather than a plausible-looking wrong image.
 *
 * - `reference-normalized`: `[0,1]` against the sanitized derivative's own
 *   pixel box. The space #1485 `ReferenceRegion.rect` already occupies.
 * - `source-pixel`: raw pixels of the approved source artifact being composited.
 * - `output-pixel`: raw pixels of the produced frame; the space the executor
 *   provenance report declares under `RECT_CONVENTION`.
 *
 * Nothing in this module converts one space into another.
 */
export const RECT_SPACES = {
  referenceNormalized: 'reference-normalized',
  sourcePixel: 'source-pixel',
  outputPixel: 'output-pixel',
} as const;

export type RectSpace = (typeof RECT_SPACES)[keyof typeof RECT_SPACES];

export type SpacedRect<Space extends RectSpace> = Readonly<{
  space: Space;
  rect: RectXywh;
}>;

export type ReferenceNormalizedRect = SpacedRect<'reference-normalized'>;
export type SourcePixelRect = SpacedRect<'source-pixel'>;
export type OutputPixelRect = SpacedRect<'output-pixel'>;

/* -------------------------------------------------------------------------
 * Resolved render vocabulary
 * ---------------------------------------------------------------------- */

export const COMPOSITING_COLOUR_SPACES = {
  srgb: 'srgb',
  linear: 'linear',
} as const;

export type CompositingColourSpace =
  (typeof COMPOSITING_COLOUR_SPACES)[keyof typeof COMPOSITING_COLOUR_SPACES];

/** `none` is the only resampler permitted for a 1:1 crop-only frame. */
export const RESAMPLERS = {
  none: 'none',
  nearest: 'nearest',
  bilinear: 'bilinear',
} as const;

export type ResamplerName = (typeof RESAMPLERS)[keyof typeof RESAMPLERS];

/**
 * The framing ladder: crop/translation only, then integer or simple-rational
 * scale, then arbitrary fractional scale only when framing requires it.
 */
export const RENDER_MODES = {
  cropOnly: 'crop-only',
  integerScale: 'integer-scale',
  simpleRationalScale: 'simple-rational-scale',
  fractionalScale: 'fractional-scale',
} as const;

export type RenderMode = (typeof RENDER_MODES)[keyof typeof RENDER_MODES];

export const OVERLAY_KINDS = {
  spotlight: 'spotlight',
  badge: 'badge',
  arrow: 'arrow',
  label: 'label',
  inset: 'inset',
} as const;

export type OverlayKind = (typeof OVERLAY_KINDS)[keyof typeof OVERLAY_KINDS];

export const SPOTLIGHT_FALLOFF_FUNCTIONS = {
  none: 'none',
  linear: 'linear',
  smoothstep: 'smoothstep',
} as const;

export type SpotlightFalloffFunction =
  (typeof SPOTLIGHT_FALLOFF_FUNCTIONS)[keyof typeof SPOTLIGHT_FALLOFF_FUNCTIONS];

export type AnnotationSide = 'left' | 'right' | 'above' | 'below';

/* -------------------------------------------------------------------------
 * Deterministic render constants
 * ---------------------------------------------------------------------- */

export type SpotlightConstants = Readonly<{
  padding_px: number;
  falloff_px: number;
  falloff_function: SpotlightFalloffFunction;
}>;

/**
 * Typography constants are plain values carried for execution. #1484 excludes a
 * deterministic typography subsystem from this slice, so nothing here measures
 * glyphs, shapes text, or derives geometry from font metrics: label boxes are
 * sized from plan constants alone.
 */
export type BadgeConstants = Readonly<{
  diameter_px: number;
  border_width_px: number;
  fill_rgba: RgbaColor;
  border_rgba: RgbaColor;
  text_rgba: RgbaColor;
  font_family: string;
  font_size_px: number;
  font_weight: number;
}>;

export type ArrowConstants = Readonly<{
  shaft_width_px: number;
  head_length_px: number;
  head_width_px: number;
  rgba: RgbaColor;
}>;

export type LabelConstants = Readonly<{
  font_family: string;
  font_size_px: number;
  font_weight: number;
  line_height_px: number;
  padding_x_px: number;
  padding_y_px: number;
  corner_radius_px: number;
  max_width_px: number;
  background_rgba: RgbaColor;
  text_rgba: RgbaColor;
}>;

export type InsetConstants = Readonly<{
  magnification: number;
  border_width_px: number;
  border_rgba: RgbaColor;
}>;

/**
 * Every deterministic constant an executor needs and may not invent. `dim_rgba`
 * reuses the repository's canonical RGBA range (integer 0-255 channels, `[0,1]`
 * alpha) established by `parseComputedColorToRgba` in the capture package, so
 * no second colour representation is introduced.
 */
export type ExactCompositeRenderSpec = Readonly<{
  compositing_colour_space: CompositingColourSpace;
  dim_rgba: RgbaColor;
  resampler: ResamplerName;
  overlay_bleed_px: number;
  annotation_clearance_px: number;
  context_margin_fraction: number;
  spotlight: SpotlightConstants;
  badge: BadgeConstants;
  arrow: ArrowConstants;
  label: LabelConstants;
  inset: InsetConstants;
}>;

const UI_FONT_STACK = "'Inter', 'Segoe UI', system-ui, sans-serif";

/**
 * The resolved default render spec. Deep-frozen so a plan cannot be mutated
 * after construction and so two frames built from the defaults are byte-
 * comparable under the tight no-resample tolerance band.
 */
export const DEFAULT_EXACT_COMPOSITE_RENDER_SPEC: ExactCompositeRenderSpec = Object.freeze({
  compositing_colour_space: COMPOSITING_COLOUR_SPACES.srgb,
  dim_rgba: Object.freeze([0, 0, 0, 0.55] as const),
  resampler: RESAMPLERS.none,
  overlay_bleed_px: 2,
  annotation_clearance_px: 16,
  context_margin_fraction: 0.08,
  spotlight: Object.freeze({
    padding_px: 12,
    falloff_px: 6,
    falloff_function: SPOTLIGHT_FALLOFF_FUNCTIONS.smoothstep,
  }),
  badge: Object.freeze({
    diameter_px: 44,
    border_width_px: 3,
    fill_rgba: Object.freeze([255, 255, 255, 1] as const),
    border_rgba: Object.freeze([17, 17, 17, 1] as const),
    text_rgba: Object.freeze([17, 17, 17, 1] as const),
    font_family: UI_FONT_STACK,
    font_size_px: 22,
    font_weight: 700,
  }),
  arrow: Object.freeze({
    shaft_width_px: 6,
    head_length_px: 18,
    head_width_px: 16,
    rgba: Object.freeze([255, 255, 255, 1] as const),
  }),
  label: Object.freeze({
    font_family: UI_FONT_STACK,
    font_size_px: 18,
    font_weight: 600,
    line_height_px: 24,
    padding_x_px: 12,
    padding_y_px: 8,
    corner_radius_px: 8,
    max_width_px: 320,
    background_rgba: Object.freeze([17, 17, 17, 0.92] as const),
    text_rgba: Object.freeze([255, 255, 255, 1] as const),
  }),
  inset: Object.freeze({
    magnification: 2,
    border_width_px: 3,
    border_rgba: Object.freeze([255, 255, 255, 1] as const),
  }),
});

/* -------------------------------------------------------------------------
 * Plan records
 * ---------------------------------------------------------------------- */

/**
 * Identity of the one approved visual reference the frame is composited from,
 * projected from `ApprovedVisualReference` (`./visualReference`). The content
 * fingerprint is carried so a recaptured derivative can never satisfy a plan
 * built against the previous pixels.
 */
export type FrameBaseReference = Readonly<{
  reference_id: string;
  stable_ref: string;
  content_fingerprint: string;
}>;

/** Frozen by #1484; consumed unchanged. */
export type TutorialAnnotationIntent = Readonly<{
  target_region_id: string;
  label: string | null;
  preferred_side: 'left' | 'right' | 'above' | 'below' | null;
}>;

/** A #1485 region that must remain source-derived, in output coordinates. */
export type AnchoredRegionRect = Readonly<{
  region_id: string;
  rect: OutputPixelRect;
}>;

/**
 * Placement of one approved exact asset. Exact-composite admits zero fills or
 * asset-only fills: there is deliberately no synthesized-fill variant in this
 * slice, so a generated fill is unrepresentable rather than merely forbidden.
 */
export type ExactAssetFill = Readonly<{
  fill_id: string;
  asset_id: string;
  asset_fingerprint: string;
  destination: OutputPixelRect;
}>;

type OverlayBase<Kind extends OverlayKind> = Readonly<{
  overlay_id: string;
  kind: Kind;
  /** Bounding rect the validator dilates by `overlay_bleed_px` to exclude. */
  bounds: OutputPixelRect;
}>;

export type SpotlightOverlay = OverlayBase<'spotlight'> & Readonly<{
  region_id: string;
  boundary: OutputPixelRect;
  padding_px: number;
  falloff_px: number;
  falloff_function: SpotlightFalloffFunction;
}>;

export type BadgeOverlay = OverlayBase<'badge'> & Readonly<{
  ordinal: number;
  centre_x_px: number;
  centre_y_px: number;
}>;

export type ArrowOverlay = OverlayBase<'arrow'> & Readonly<{
  from_x_px: number;
  from_y_px: number;
  to_x_px: number;
  to_y_px: number;
}>;

export type LabelOverlay = OverlayBase<'label'> & Readonly<{
  text: string;
  preferred_side: AnnotationSide | null;
  resolved_side: AnnotationSide;
}>;

export type InsetOverlay = OverlayBase<'inset'> & Readonly<{
  source_rect: SourcePixelRect;
  magnification: number;
}>;

/** Closed union: an unknown overlay kind cannot appear in a plan. */
export type FrameOverlay =
  | SpotlightOverlay
  | BadgeOverlay
  | ArrowOverlay
  | LabelOverlay
  | InsetOverlay;

export type OutputAspect = Readonly<{
  width: number;
  height: number;
}>;

export const TUTORIAL_FRAME_PLAN_VERSION = 'picture-perfect-exact-composite-plan-v1' as const;

/**
 * One fully resolved exact-composite frame plan.
 *
 * Output dimensions are carried, not derived, because the validator forward-
 * constructs the expected image in output coordinates from source and plan
 * alone. `scale_x`/`scale_y` are the declared geometry the report is checked
 * against. Like every other PPUX projection, a plan is presentation evidence:
 * `execution_authorized` stays `false`.
 */
export type TutorialFramePlan = Readonly<{
  plan_version: typeof TUTORIAL_FRAME_PLAN_VERSION;
  rect_convention: RectConvention;
  base_reference: FrameBaseReference;
  /**
   * The region the annotation actually resolved to. Carried explicitly because
   * `annotation_intent.target_region_id` is empty whenever the target was
   * resolved from the state-local UI claim, and a plan must never require its
   * consumer to recover a missing value.
   */
  resolved_target_region_id: string;
  source_rect: SourcePixelRect;
  output_aspect: OutputAspect;
  output_width_px: number;
  output_height_px: number;
  render_mode: RenderMode;
  scale_x: number;
  scale_y: number;
  render_spec: ExactCompositeRenderSpec;
  asset_fills: readonly ExactAssetFill[];
  overlays: readonly FrameOverlay[];
  anchored_rects: readonly AnchoredRegionRect[];
  must_show_region_ids: readonly string[];
  annotation_intent: TutorialAnnotationIntent;
  execution_authorized: false;
}>;

/* -------------------------------------------------------------------------
 * Frame planner
 * ---------------------------------------------------------------------- */

/**
 * Above this denominator a reduced scale stops being a simple rational and is
 * classified as arbitrary fractional scale, which #1484 permits only when
 * framing requires it.
 */
export const SIMPLE_RATIONAL_MAX_DENOMINATOR = 8;

export const FRAME_PLAN_BLOCKER_REASONS = {
  targetUnresolved: 'frame-plan-target-unresolved',
  labelClaimNotVisible: 'frame-plan-label-claim-not-visible',
  mustShowRegionMissing: 'frame-plan-must-show-region-missing',
  mustShowRegionOutsideFrame: 'frame-plan-must-show-region-outside-frame',
  sourceDimensionsInvalid: 'frame-plan-source-dimensions-invalid',
  outputGeometryInconsistent: 'frame-plan-output-geometry-inconsistent',
  framingUnresolvable: 'frame-plan-framing-unresolvable',
} as const;

export type FramePlanBlockerReason =
  (typeof FRAME_PLAN_BLOCKER_REASONS)[keyof typeof FRAME_PLAN_BLOCKER_REASONS];

/**
 * Upstream reasons are surfaced verbatim rather than translated, so a #1485
 * region-admission or reference-selection failure keeps its own identity.
 */
export type FramePlanBlocker = FramePlanBlockerReason | VisualReferenceBlockerReason;

export type FramePlanRequest = Readonly<{
  library: VisualReferenceLibrary;
  /** Reference selection is delegated unchanged to `selectVisualReference`. */
  selection: VisualReferenceSelectionRequest;
  region_set: ReferenceRegionSet;
  /** Instructional must-show claims; the keep-set is the regions carrying them. */
  must_show_claims: readonly string[];
  annotation_intent: TutorialAnnotationIntent;
  source_width_px: number;
  source_height_px: number;
  output_width_px: number;
  output_height_px: number;
  render_spec?: ExactCompositeRenderSpec;
}>;

export type FramePlanResult = Readonly<{
  status: CaptureStatus;
  plan: TutorialFramePlan | null;
  blocker_reasons: readonly FramePlanBlocker[];
}>;

type Box = Readonly<{ left: number; top: number; right: number; bottom: number }>;

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

function greatestCommonDivisor(a: number, b: number): number {
  let x = Math.abs(a);
  let y = Math.abs(b);
  while (y !== 0) {
    const next = x % y;
    x = y;
    y = next;
  }
  return x;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * The one conversion this module performs. `ReferenceRegion.rect` is normalized
 * against the sanitized derivative's own pixel box (#1485) and the source
 * artifact is that same derivative, bound by `reference_id` and
 * `content_fingerprint`. Capture-viewport space is never involved, and nothing
 * here converts into or out of it.
 */
function regionBox(region: ReferenceRegion, sourceWidth: number, sourceHeight: number): Box {
  const [x, y, width, height] = region.rect;
  return {
    left: Math.round(x * sourceWidth),
    top: Math.round(y * sourceHeight),
    right: Math.round((x + width) * sourceWidth),
    bottom: Math.round((y + height) * sourceHeight),
  };
}

function unionBox(boxes: readonly Box[]): Box {
  return boxes.reduce((accumulated, box) => ({
    left: Math.min(accumulated.left, box.left),
    top: Math.min(accumulated.top, box.top),
    right: Math.max(accumulated.right, box.right),
    bottom: Math.max(accumulated.bottom, box.bottom),
  }));
}

function containsBox(outer: Box, inner: Box): boolean {
  return inner.left >= outer.left && inner.top >= outer.top &&
    inner.right <= outer.right && inner.bottom <= outer.bottom;
}

/**
 * Resolve the annotated target from `target_region_id`, else from the
 * state-local target UI claim. An absent, unknown, or ambiguous target is
 * unresolved: the planner never guesses which region was meant.
 */
function resolveTargetRegion(
  regions: readonly ReferenceRegion[],
  intent: TutorialAnnotationIntent,
): ReferenceRegion | null {
  const requestedId = intent.target_region_id.trim();
  if (requestedId) return regions.find((region) => region.region_id === requestedId) ?? null;

  const label = intent.label?.trim() ?? '';
  if (!label) return null;
  const claimed = regions.filter((region) => region.claim === label);
  return claimed.length === 1 ? claimed[0]! : null;
}

function derivedRenderMode(numerator: number, denominator: number): RenderMode {
  if (numerator === 1 && denominator === 1) return RENDER_MODES.cropOnly;
  if (numerator === 1 || denominator === 1) return RENDER_MODES.integerScale;
  if (denominator <= SIMPLE_RATIONAL_MAX_DENOMINATOR) return RENDER_MODES.simpleRationalScale;
  return RENDER_MODES.fractionalScale;
}

function resamplerFor(mode: RenderMode): ResamplerName {
  if (mode === RENDER_MODES.cropOnly) return RESAMPLERS.none;
  if (mode === RENDER_MODES.integerScale) return RESAMPLERS.nearest;
  return RESAMPLERS.bilinear;
}

function blockedResult(reasons: readonly FramePlanBlocker[], status: CaptureStatus = 'blocked'): FramePlanResult {
  return { status, plan: null, blocker_reasons: [...new Set(reasons)] };
}

/**
 * Plan one exact-composite tutorial frame, or emit explicit blockers.
 *
 * The planner selects exactly one approved reference, consumes #1485 admitted
 * regions without redesigning them, resolves the annotation target, builds the
 * must-show keep-set, and derives framing deterministically. It fails closed
 * rather than inferring: no target discovery, no pixel inspection, no geometry
 * estimation, and no reconstruction of source UI or student artwork. Framing is
 * crop and proportional scale only, and no synthesized fill is produced.
 *
 * Overlay resolution is not performed here; a plan carries the resolved
 * constants overlays are built from.
 */
export function planTutorialFrame(request: FramePlanRequest): FramePlanResult {
  const selected = selectVisualReference(request.library, request.selection);
  if (selected.status !== 'valid' || !selected.reference) {
    return blockedResult(selected.blocker_reasons, selected.status);
  }
  const reference = selected.reference;

  const admitted = admitReferenceRegions(reference, request.region_set);
  if (admitted.status !== 'valid' || !admitted.regions) {
    return blockedResult(admitted.blocker_reasons, admitted.status);
  }
  const regions = admitted.regions;

  const reasons: FramePlanBlocker[] = [];

  if (!isPositiveInteger(request.source_width_px) || !isPositiveInteger(request.source_height_px)) {
    reasons.push(FRAME_PLAN_BLOCKER_REASONS.sourceDimensionsInvalid);
  }
  if (!isPositiveInteger(request.output_width_px) || !isPositiveInteger(request.output_height_px)) {
    reasons.push(FRAME_PLAN_BLOCKER_REASONS.outputGeometryInconsistent);
  }

  const target = resolveTargetRegion(regions, request.annotation_intent);
  if (!target) reasons.push(FRAME_PLAN_BLOCKER_REASONS.targetUnresolved);

  const intentLabel = request.annotation_intent.label?.trim() ?? '';
  if (intentLabel && !reference.visible_ui_claims.includes(intentLabel)) {
    reasons.push(FRAME_PLAN_BLOCKER_REASONS.labelClaimNotVisible);
  }

  const keepSet: ReferenceRegion[] = [];
  for (const claim of request.must_show_claims) {
    const matched = regions.filter((region) => region.claim === claim);
    if (matched.length === 0) {
      reasons.push(FRAME_PLAN_BLOCKER_REASONS.mustShowRegionMissing);
      continue;
    }
    keepSet.push(...matched);
  }

  if (reasons.length > 0 || !target) return blockedResult(reasons);

  const sourceWidth = request.source_width_px;
  const sourceHeight = request.source_height_px;
  const keepBoxes = [target, ...keepSet].map((region) => regionBox(region, sourceWidth, sourceHeight));
  const union = unionBox(keepBoxes);

  const spec = request.render_spec ?? DEFAULT_EXACT_COMPOSITE_RENDER_SPEC;
  const marginX = Math.round(spec.context_margin_fraction * (union.right - union.left));
  const marginY = Math.round(spec.context_margin_fraction * (union.bottom - union.top));
  const expanded: Box = {
    left: union.left - marginX,
    top: union.top - marginY,
    right: union.right + marginX,
    bottom: union.bottom + marginY,
  };

  const outputDivisor = greatestCommonDivisor(request.output_width_px, request.output_height_px);
  const aspectWidth = request.output_width_px / outputDivisor;
  const aspectHeight = request.output_height_px / outputDivisor;

  const steps = Math.max(
    Math.ceil((expanded.right - expanded.left) / aspectWidth),
    Math.ceil((expanded.bottom - expanded.top) / aspectHeight),
    1,
  );
  const frameWidth = aspectWidth * steps;
  const frameHeight = aspectHeight * steps;
  if (frameWidth > sourceWidth || frameHeight > sourceHeight) {
    return blockedResult([FRAME_PLAN_BLOCKER_REASONS.framingUnresolvable]);
  }

  const centreX = (expanded.left + expanded.right) / 2;
  const centreY = (expanded.top + expanded.bottom) / 2;
  const frameLeft = clamp(Math.round(centreX - frameWidth / 2), 0, sourceWidth - frameWidth);
  const frameTop = clamp(Math.round(centreY - frameHeight / 2), 0, sourceHeight - frameHeight);
  const frame: Box = {
    left: frameLeft,
    top: frameTop,
    right: frameLeft + frameWidth,
    bottom: frameTop + frameHeight,
  };

  if (!keepBoxes.every((box) => containsBox(frame, box))) {
    return blockedResult([FRAME_PLAN_BLOCKER_REASONS.mustShowRegionOutsideFrame]);
  }

  const scaleDivisor = greatestCommonDivisor(outputDivisor, steps);
  const scaleNumerator = outputDivisor / scaleDivisor;
  const scaleDenominator = steps / scaleDivisor;
  const renderMode = derivedRenderMode(scaleNumerator, scaleDenominator);
  const scale = scaleNumerator / scaleDenominator;

  const toOutput = (value: number): number => Math.round((value * scaleNumerator) / scaleDenominator);
  const keepIds = new Set([target.region_id, ...keepSet.map((region) => region.region_id)]);
  const anchored: AnchoredRegionRect[] = [];
  for (const region of regions) {
    const isAnchored = region.fill_allowed === false;
    if (!isAnchored && !keepIds.has(region.region_id)) continue;
    const box = regionBox(region, sourceWidth, sourceHeight);
    if (!containsBox(frame, box)) continue;
    anchored.push({
      region_id: region.region_id,
      rect: {
        space: RECT_SPACES.outputPixel,
        rect: [
          toOutput(box.left - frame.left),
          toOutput(box.top - frame.top),
          toOutput(box.right - box.left),
          toOutput(box.bottom - box.top),
        ],
      },
    });
  }

  return {
    status: 'valid',
    blocker_reasons: [],
    plan: {
      plan_version: TUTORIAL_FRAME_PLAN_VERSION,
      rect_convention: RECT_CONVENTION,
      base_reference: {
        reference_id: reference.reference_id,
        stable_ref: reference.asset_reference.stable_ref,
        content_fingerprint: reference.asset_reference.content_fingerprint,
      },
      resolved_target_region_id: target.region_id,
      source_rect: { space: RECT_SPACES.sourcePixel, rect: [frame.left, frame.top, frameWidth, frameHeight] },
      output_aspect: { width: aspectWidth, height: aspectHeight },
      output_width_px: request.output_width_px,
      output_height_px: request.output_height_px,
      render_mode: renderMode,
      scale_x: scale,
      scale_y: scale,
      render_spec: { ...spec, resampler: resamplerFor(renderMode) },
      asset_fills: [],
      overlays: [],
      anchored_rects: anchored,
      must_show_region_ids: [...keepIds],
      annotation_intent: request.annotation_intent,
      execution_authorized: false,
    },
  };
}
