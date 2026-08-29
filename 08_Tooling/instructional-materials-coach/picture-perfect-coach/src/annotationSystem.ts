import type { CaptureStatus } from './captureEvidence';
import {
  OVERLAY_KINDS,
  RECT_SPACES,
  type AnnotationSide,
  type ArrowOverlay,
  type BadgeOverlay,
  type ExactCompositeRenderSpec,
  type FrameOverlay,
  type LabelOverlay,
  type OutputPixelRect,
  type OverlayKind,
  type RectXywh,
  type SpotlightOverlay,
  type TutorialFramePlan,
} from './framePlan';

/**
 * PPUX-VRL7 (#1484) Slice 3 overlay resolution.
 *
 * Overlays are resolved from the plan's own anchored geometry and its resolved
 * render constants, never from the source pixels: nothing here inspects an
 * image, measures glyphs, detects a target, or nudges an annotation for
 * appearance. Placement walks a fixed side order and fails closed when no side
 * satisfies the bounded geometry rules, because shifting an annotation to make
 * it fit would be exactly the aesthetic judgement #1484 forbids.
 *
 * Every overlay carries an output-pixel bounding rect. Those rects are the
 * input the validator dilates by `overlay_bleed_px` to build its exclusion
 * mask, and the spotlight additionally exposes its own boundary so the mask can
 * dilate that by the declared falloff.
 */

export const ANNOTATION_BLOCKER_REASONS = {
  unknownOverlayKind: 'annotation-unknown-overlay-kind',
  targetRectMissing: 'annotation-target-rect-missing',
  labelTextMissing: 'annotation-label-text-missing',
  badgeOrdinalInvalid: 'annotation-badge-ordinal-invalid',
  clearanceUnavailable: 'annotation-clearance-unavailable',
} as const;

export type AnnotationBlockerReason =
  (typeof ANNOTATION_BLOCKER_REASONS)[keyof typeof ANNOTATION_BLOCKER_REASONS];

/** Deterministic paint order; a request's own ordering never changes it. */
export const OVERLAY_PAINT_ORDER: readonly OverlayKind[] = [
  OVERLAY_KINDS.spotlight,
  OVERLAY_KINDS.badge,
  OVERLAY_KINDS.arrow,
  OVERLAY_KINDS.label,
];

/** Tried after the preferred side, in this order, and never reordered. */
const SIDE_ORDER: readonly AnnotationSide[] = ['right', 'left', 'below', 'above'];

export type OverlayResolutionRequest = Readonly<{
  /** Step number the badge shows. Supplied, never derived from the plan. */
  ordinal: number;
  /** Overlay kinds to resolve. Validated at runtime against `OVERLAY_KINDS`. */
  kinds?: readonly string[];
}>;

export type OverlayResolutionResult = Readonly<{
  status: CaptureStatus;
  overlays: readonly FrameOverlay[] | null;
  blocker_reasons: readonly AnnotationBlockerReason[];
}>;

type Box = Readonly<{ left: number; top: number; right: number; bottom: number }>;

function boxFromRect(rect: RectXywh): Box {
  const [x, y, width, height] = rect;
  return { left: x, top: y, right: x + width, bottom: y + height };
}

function outputRect(box: Box): OutputPixelRect {
  return {
    space: RECT_SPACES.outputPixel,
    rect: [box.left, box.top, box.right - box.left, box.bottom - box.top],
  };
}

function expandBox(box: Box, horizontal: number, vertical: number): Box {
  return {
    left: box.left - horizontal,
    top: box.top - vertical,
    right: box.right + horizontal,
    bottom: box.bottom + vertical,
  };
}

function clampBox(box: Box, width: number, height: number): Box {
  return {
    left: Math.max(0, box.left),
    top: Math.max(0, box.top),
    right: Math.min(width, box.right),
    bottom: Math.min(height, box.bottom),
  };
}

function withinBounds(box: Box, width: number, height: number): boolean {
  return box.left >= 0 && box.top >= 0 && box.right <= width && box.bottom <= height;
}

function boxesIntersect(a: Box, b: Box): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/**
 * True only for kinds this resolver can actually resolve. `inset` is a valid
 * plan overlay kind whose geometry is not resolved here, so requesting one
 * fails closed rather than being silently dropped from the result.
 */
function isResolvableOverlayKind(kind: string): kind is OverlayKind {
  return (OVERLAY_PAINT_ORDER as readonly string[]).includes(kind);
}

function candidateSides(preferred: AnnotationSide | null): readonly AnnotationSide[] {
  if (!preferred) return SIDE_ORDER;
  return [preferred, ...SIDE_ORDER.filter((side) => side !== preferred)];
}

type Placement = Readonly<{ side: AnnotationSide; badge: Box; label: Box; arrow: Box; from: readonly [number, number]; to: readonly [number, number] }>;

/**
 * Label boxes are sized from plan constants alone -- `max_width_px` wide and one
 * `line_height_px` plus vertical padding tall. #1484 excludes a deterministic
 * typography subsystem from this slice, so no text is measured and no box is
 * fitted to its glyphs.
 */
function placeOnSide(boundary: Box, side: AnnotationSide, spec: ExactCompositeRenderSpec): Placement {
  const clearance = spec.annotation_clearance_px;
  const diameter = spec.badge.diameter_px;
  const labelWidth = spec.label.max_width_px;
  const labelHeight = spec.label.line_height_px + 2 * spec.label.padding_y_px;
  const centreX = Math.round((boundary.left + boundary.right) / 2);
  const centreY = Math.round((boundary.top + boundary.bottom) / 2);

  let badge: Box;
  let label: Box;
  let from: readonly [number, number];
  let to: readonly [number, number];

  if (side === 'right') {
    const badgeLeft = boundary.right + clearance;
    const badgeTop = centreY - Math.round(diameter / 2);
    badge = { left: badgeLeft, top: badgeTop, right: badgeLeft + diameter, bottom: badgeTop + diameter };
    const labelLeft = badge.right + clearance;
    const labelTop = centreY - Math.round(labelHeight / 2);
    label = { left: labelLeft, top: labelTop, right: labelLeft + labelWidth, bottom: labelTop + labelHeight };
    from = [badge.left, centreY];
    to = [boundary.right, centreY];
  } else if (side === 'left') {
    const badgeRight = boundary.left - clearance;
    const badgeTop = centreY - Math.round(diameter / 2);
    badge = { left: badgeRight - diameter, top: badgeTop, right: badgeRight, bottom: badgeTop + diameter };
    const labelRight = badge.left - clearance;
    const labelTop = centreY - Math.round(labelHeight / 2);
    label = { left: labelRight - labelWidth, top: labelTop, right: labelRight, bottom: labelTop + labelHeight };
    from = [badge.right, centreY];
    to = [boundary.left, centreY];
  } else if (side === 'below') {
    const badgeTop = boundary.bottom + clearance;
    const badgeLeft = centreX - Math.round(diameter / 2);
    badge = { left: badgeLeft, top: badgeTop, right: badgeLeft + diameter, bottom: badgeTop + diameter };
    const labelTop = badge.bottom + clearance;
    const labelLeft = centreX - Math.round(labelWidth / 2);
    label = { left: labelLeft, top: labelTop, right: labelLeft + labelWidth, bottom: labelTop + labelHeight };
    from = [centreX, badge.top];
    to = [centreX, boundary.bottom];
  } else {
    const badgeBottom = boundary.top - clearance;
    const badgeLeft = centreX - Math.round(diameter / 2);
    badge = { left: badgeLeft, top: badgeBottom - diameter, right: badgeLeft + diameter, bottom: badgeBottom };
    const labelBottom = badge.top - clearance;
    const labelLeft = centreX - Math.round(labelWidth / 2);
    label = { left: labelLeft, top: labelBottom - labelHeight, right: labelLeft + labelWidth, bottom: labelBottom };
    from = [centreX, badge.bottom];
    to = [centreX, boundary.top];
  }

  const reach = Math.round(Math.max(spec.arrow.shaft_width_px, spec.arrow.head_width_px) / 2);
  const arrow = expandBox({
    left: Math.min(from[0], to[0]),
    top: Math.min(from[1], to[1]),
    right: Math.max(from[0], to[0]),
    bottom: Math.max(from[1], to[1]),
  }, reach, reach);

  return { side, badge, label, arrow, from, to };
}

/**
 * Resolve the frame's overlays, or fail closed.
 *
 * The spotlight is the target's anchored rect padded by the plan's spotlight
 * constants. Badge, arrow, and label are placed together on one side: the
 * preferred side is tried first, then the remaining sides in fixed order, and a
 * side is accepted only when the badge and label both fit inside the output
 * frame and cover no anchored rect. The arrow is exempt from the anchored-rect
 * test because it terminates on the spotlight boundary and so never enters the
 * evidence it points at.
 */
export function resolveFrameOverlays(
  plan: TutorialFramePlan,
  request: OverlayResolutionRequest,
): OverlayResolutionResult {
  const requestedKinds = request.kinds ?? OVERLAY_PAINT_ORDER;
  const unknown = requestedKinds.filter((kind) => !isResolvableOverlayKind(kind));
  if (unknown.length > 0) {
    return { status: 'blocked', overlays: null, blocker_reasons: [ANNOTATION_BLOCKER_REASONS.unknownOverlayKind] };
  }
  const kinds = new Set(requestedKinds as readonly OverlayKind[]);

  const reasons: AnnotationBlockerReason[] = [];
  const targetAnchor = plan.anchored_rects.find((anchor) => anchor.region_id === plan.resolved_target_region_id);
  if (!targetAnchor) reasons.push(ANNOTATION_BLOCKER_REASONS.targetRectMissing);

  const labelText = plan.annotation_intent.label?.trim() ?? '';
  if (kinds.has(OVERLAY_KINDS.label) && !labelText) {
    reasons.push(ANNOTATION_BLOCKER_REASONS.labelTextMissing);
  }
  if (kinds.has(OVERLAY_KINDS.badge) && !(Number.isInteger(request.ordinal) && request.ordinal > 0)) {
    reasons.push(ANNOTATION_BLOCKER_REASONS.badgeOrdinalInvalid);
  }
  if (reasons.length > 0 || !targetAnchor) {
    return { status: 'blocked', overlays: null, blocker_reasons: [...new Set(reasons)] };
  }

  const spec = plan.render_spec;
  const width = plan.output_width_px;
  const height = plan.output_height_px;
  const boundary = clampBox(
    expandBox(boxFromRect(targetAnchor.rect.rect), spec.spotlight.padding_px, spec.spotlight.padding_px),
    width,
    height,
  );
  const anchoredBoxes = plan.anchored_rects.map((anchor) => boxFromRect(anchor.rect.rect));

  const needsPlacement = kinds.has(OVERLAY_KINDS.badge) || kinds.has(OVERLAY_KINDS.arrow) || kinds.has(OVERLAY_KINDS.label);
  let placement: Placement | null = null;
  if (needsPlacement) {
    for (const side of candidateSides(plan.annotation_intent.preferred_side)) {
      const candidate = placeOnSide(boundary, side, spec);
      const covering: Box[] = [];
      if (kinds.has(OVERLAY_KINDS.badge)) covering.push(candidate.badge);
      if (kinds.has(OVERLAY_KINDS.label)) covering.push(candidate.label);
      const placed = kinds.has(OVERLAY_KINDS.arrow) ? [...covering, candidate.arrow] : covering;
      if (!placed.every((box) => withinBounds(box, width, height))) continue;
      if (covering.some((box) => anchoredBoxes.some((anchor) => boxesIntersect(box, anchor)))) continue;
      placement = candidate;
      break;
    }
    if (!placement) {
      return { status: 'blocked', overlays: null, blocker_reasons: [ANNOTATION_BLOCKER_REASONS.clearanceUnavailable] };
    }
  }

  const overlays: FrameOverlay[] = [];
  for (const kind of OVERLAY_PAINT_ORDER) {
    if (!kinds.has(kind)) continue;

    if (kind === OVERLAY_KINDS.spotlight) {
      const spotlight: SpotlightOverlay = {
        overlay_id: `spotlight-${request.ordinal}`,
        kind: OVERLAY_KINDS.spotlight,
        bounds: outputRect(clampBox(expandBox(boundary, spec.spotlight.falloff_px, spec.spotlight.falloff_px), width, height)),
        region_id: plan.resolved_target_region_id,
        boundary: outputRect(boundary),
        padding_px: spec.spotlight.padding_px,
        falloff_px: spec.spotlight.falloff_px,
        falloff_function: spec.spotlight.falloff_function,
      };
      overlays.push(spotlight);
      continue;
    }

    if (!placement) continue;

    if (kind === OVERLAY_KINDS.badge) {
      const badge: BadgeOverlay = {
        overlay_id: `badge-${request.ordinal}`,
        kind: OVERLAY_KINDS.badge,
        bounds: outputRect(placement.badge),
        ordinal: request.ordinal,
        centre_x_px: Math.round((placement.badge.left + placement.badge.right) / 2),
        centre_y_px: Math.round((placement.badge.top + placement.badge.bottom) / 2),
      };
      overlays.push(badge);
    } else if (kind === OVERLAY_KINDS.arrow) {
      const arrow: ArrowOverlay = {
        overlay_id: `arrow-${request.ordinal}`,
        kind: OVERLAY_KINDS.arrow,
        bounds: outputRect(placement.arrow),
        from_x_px: placement.from[0],
        from_y_px: placement.from[1],
        to_x_px: placement.to[0],
        to_y_px: placement.to[1],
      };
      overlays.push(arrow);
    } else if (kind === OVERLAY_KINDS.label) {
      const label: LabelOverlay = {
        overlay_id: `label-${request.ordinal}`,
        kind: OVERLAY_KINDS.label,
        bounds: outputRect(placement.label),
        text: labelText,
        preferred_side: plan.annotation_intent.preferred_side,
        resolved_side: placement.side,
      };
      overlays.push(label);
    }
  }

  return { status: 'valid', overlays, blocker_reasons: [] };
}
