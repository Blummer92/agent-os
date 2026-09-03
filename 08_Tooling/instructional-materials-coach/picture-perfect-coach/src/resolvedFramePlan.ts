import type { CaptureStatus } from './captureEvidence';
import {
  planTutorialFrame,
  type FramePlanBlocker,
  type FramePlanRequest,
  type TutorialFramePlan,
} from './framePlan';
import {
  resolveFrameOverlays,
  type AnnotationBlockerReason,
  type OverlayResolutionRequest,
} from './overlayResolution';

/**
 * #1791 fully resolved exact-composite planning seam.
 *
 * `planTutorialFrame` remains the deterministic geometry projection frozen by
 * #1484. This composition step immediately resolves the plan-authorized overlay
 * records with the one existing resolver so an executor never receives a
 * geometry-only plan whose overlays must be recovered later.
 */
export type ResolvedFramePlanRequest = Readonly<{
  frame: FramePlanRequest;
  overlays: OverlayResolutionRequest;
}>;

export type ResolvedFramePlanBlocker = FramePlanBlocker | AnnotationBlockerReason;

export type ResolvedFramePlanResult = Readonly<{
  status: CaptureStatus;
  plan: TutorialFramePlan | null;
  blocker_reasons: readonly ResolvedFramePlanBlocker[];
}>;

export function planResolvedTutorialFrame(request: ResolvedFramePlanRequest): ResolvedFramePlanResult {
  const framed = planTutorialFrame(request.frame);
  if (framed.status !== 'valid' || !framed.plan) {
    return {
      status: framed.status,
      plan: null,
      blocker_reasons: framed.blocker_reasons,
    };
  }

  const resolved = resolveFrameOverlays(framed.plan, request.overlays);
  if (resolved.status !== 'valid' || !resolved.overlays) {
    return {
      status: resolved.status,
      plan: null,
      blocker_reasons: resolved.blocker_reasons,
    };
  }

  return {
    status: 'valid',
    blocker_reasons: [],
    plan: {
      ...framed.plan,
      overlays: resolved.overlays,
      execution_authorized: false,
    },
  };
}
