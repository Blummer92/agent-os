import {
  decideCaptureReuse,
  type CaptureReuseDecision,
  type CaptureReuseRequirement,
} from './captureReuse';
import type { CaptureEvidenceBundle } from './captureEvidence';
import type { ReviewedStepProjection } from './types';

export type CaptureRequestAdapterResult = Readonly<{
  request_id: string;
  capture_reference: string | null;
}>;

export type CaptureRequestAdapter = (
  requirement: CaptureReuseRequirement,
) => CaptureRequestAdapterResult;

export type CaptureReuseRouteResult = Readonly<{
  decision: CaptureReuseDecision;
  capture_result: CaptureRequestAdapterResult | null;
}>;

/**
 * Production composition seam for #2109/#2117.
 *
 * Reuse/manual-review outcomes stop before the #2100 adapter boundary. Only a
 * CAPTURE_REQUIRED decision may delegate exactly once. The adapter is injected
 * until #2100 lands on main, so this module adds no browser/cloud execution.
 */
export function routeCaptureNeed(
  step: ReviewedStepProjection,
  requirement: CaptureReuseRequirement,
  bundle: CaptureEvidenceBundle | null,
  captureRequestAdapter: CaptureRequestAdapter,
): CaptureReuseRouteResult {
  const decision = decideCaptureReuse(step, requirement, bundle);

  if (decision.disposition !== 'CAPTURE_REQUIRED') {
    return { decision, capture_result: null };
  }

  return {
    decision,
    capture_result: captureRequestAdapter(requirement),
  };
}
