import { describe, expect, it, vi } from 'vitest';
import { tutorial0SyntheticCapture } from './fixtures/tutorial0-capture';
import { tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import { routeCaptureNeed } from './captureReuseRouting';
import type { CaptureReuseRequirement } from './captureReuse';

const square = tutorial0ReviewedTutorial.retained_steps.find(
  (item) => item.review_step_id === 'tutorial0-step-03-square-file',
);
if (!square) throw new Error('missing square fixture');

function requirement(): CaptureReuseRequirement {
  return {
    logical_request_id: 'capture-request:tutorial0:square:action',
    expected_application: 'Adobe Express',
    image_state: 'action',
    requested_ui_claims: ['Create new'],
    require_target_geometry: true,
  };
}

describe('capture reuse production routing', () => {
  it('returns reusable evidence without invoking the #2100 adapter boundary', () => {
    const adapter = vi.fn(() => ({ request_id: 'unexpected', capture_reference: null }));
    const result = routeCaptureNeed(square, requirement(), tutorial0SyntheticCapture, adapter);

    expect(result.decision.disposition).toBe('REUSE_EXISTING_CAPTURE');
    expect(result.capture_result).toBeNull();
    expect(adapter).not.toHaveBeenCalled();
  });

  it('returns manual review without invoking the #2100 adapter boundary', () => {
    const adapter = vi.fn(() => ({ request_id: 'unexpected', capture_reference: null }));
    const result = routeCaptureNeed(
      square,
      requirement(),
      { ...tutorial0SyntheticCapture, status: 'manual-review-required' },
      adapter,
    );

    expect(result.decision.disposition).toBe('MANUAL_REVIEW_REQUIRED');
    expect(result.capture_result).toBeNull();
    expect(adapter).not.toHaveBeenCalled();
  });

  it('delegates exactly once when current governed evidence requires capture', () => {
    const adapter = vi.fn((request: CaptureReuseRequirement) => ({
      request_id: request.logical_request_id,
      capture_reference: 'software-tutorial-capture:pending',
    }));
    const result = routeCaptureNeed(square, requirement(), null, adapter);

    expect(result.decision.disposition).toBe('CAPTURE_REQUIRED');
    expect(adapter).toHaveBeenCalledTimes(1);
    expect(adapter).toHaveBeenCalledWith(requirement());
    expect(result.capture_result).toEqual({
      request_id: requirement().logical_request_id,
      capture_reference: 'software-tutorial-capture:pending',
    });
  });
});
