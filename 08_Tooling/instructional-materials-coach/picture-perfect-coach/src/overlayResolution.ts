import type { CaptureStatus } from './captureEvidence';
import type {
  AnnotationSide,
  ArrowOverlay,
  BadgeOverlay,
  ExactCompositeRenderSpec,
  FrameOverlay,
  LabelOverlay,
  OutputPixelRect,
  OverlayKind,
  RectXywh,
  SpotlightOverlay,
  TutorialFramePlan,
} from './framePlan';

/**
 * PPUX-VRL7/#1791 shared deterministic overlay resolution.
 *
 * This module deliberately imports frame-plan contracts as types only so the
 * frame planner can consume the same resolver without creating a runtime
 * dependency cycle. Nothing here inspects source pixels or infers geometry.
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

/** Deterministic paint order; caller ordering never changes it. */
export const OVERLAY_PAINT_ORDER: readonly OverlayKind[] = [
  'spotlight',
  'badge',
  'arrow',
  'label',
];

/** Tried after the preferred side, in this order, and never reordered. */
const SIDE_ORDER: readonly AnnotationSide[] = ['right', 'left', 'below', 'above'];

export type OverlayResolutionRequest = Readonly<{
  /** Step number the badge shows. Supplied, never derived from the plan. */
  ordinal: number;
  /** Overlay kinds to resolve. Omit to request the standard paint-order set. */
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
    space: 'output-pixel',
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
 * `inset` is a valid frame-plan overlay kind but current #1484 evidence does not
 * deterministically resolve its geometry. It therefore fails closed here rather
 * than being silently dropped or guessed.
 */
function isResolvableOverlayKind(kind: string): kind is OverlayKind {
  return (OVERLAY_PAINT_ORDER as readonly string[]).includes(kind);
}

function candidateSides(preferred: AnnotationSide | null): readonly AnnotationSide[] {
  if (!preferred) return SIDE_ORDER;
  return [preferred, ...SIDE_ORDER.filter((side) => side !== preferred)];
}

type Placement = Readonly<{
  side: AnnotationSide;
  badge: Box;
  label: Box;
  arrow: Box;
  from: readonly [number, number];
  to: readonly [number, number];
}>;

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
 * Resolve the frame's overlays from already-admitted plan geometry, or fail
 * closed. No target discovery, pixel inspection, aesthetic movement, context
 * inference, or post-hoc mask widening is allowed.
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
  if (kinds.has('label') && !labelText) {
    reasons.push(ANNOTATION_BLOCKER_REASONS.labelTextMissing);
  }
  if (kinds.has('badge') && !(Number.isInteger(request.ordinal) && request.ordinal > 0)) {
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

  const needsPlacement = kinds.has('badge') || kinds.has('arrow') || kinds.has('label');
  let placement: Placement | null = null;
  if (needsPlacement) {
    for (const side of candidateSides(plan.annotation_intent.preferred_side)) {
      const candidate = placeOnSide(boundary, side, spec);
      const covering: Box[] = [];
      if (kinds.has('badge')) covering.push(candidate.badge);
      if (kinds.has('label')) covering.push(candidate.label);
      const placed = kinds.has('arrow') ? [...covering, candidate.arrow] : covering;
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

    if (kind === 'spotlight') {
      const spotlight: SpotlightOverlay = {
        overlay_id: `spotlight-${request.ordinal}`,
        kind: 'spotlight',
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

    if (kind === 'badge') {
      const badge: BadgeOverlay = {
        overlay_id: `badge-${request.ordinal}`,
        kind: 'badge',
        bounds: outputRect(placement.badge),
        ordinal: request.ordinal,
        centre_x_px: Math.round((placement.badge.left + placement.badge.right) / 2),
        centre_y_px: Math.round((placement.badge.top + placement.badge.bottom) / 2),
      };
      overlays.push(badge);
    } else if (kind === 'arrow') {
      const arrow: ArrowOverlay = {
        overlay_id: `arrow-${request.ordinal}`,
        kind: 'arrow',
        bounds: outputRect(placement.arrow),
        from_x_px: placement.from[0],
        from_y_px: placement.from[1],
        to_x_px: placement.to[0],
        to_y_px: placement.to[1],
      };
      overlays.push(arrow);
    } else if (kind === 'label') {
      const label: LabelOverlay = {
        overlay_id: `label-${request.ordinal}`,
        kind: 'label',
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
