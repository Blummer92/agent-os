import { describe, expect, it } from 'vitest';
import { tutorial0SyntheticCapture } from './fixtures/tutorial0-capture';
import { tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import {
  CAPTURE_REUSE_REASONS,
  decideCaptureReuse,
  type CaptureReuseRequirement,
} from './captureReuse';
import type { CaptureEvidenceBundle } from './captureEvidence';

function reviewedStep(id: string) {
  const step = tutorial0ReviewedTutorial.retained_steps.find((item) => item.review_step_id === id);
  if (!step) throw new Error(`missing reviewed step: ${id}`);
  return step;
}

function mutateBundle(mutator: (bundle: CaptureEvidenceBundle) => CaptureEvidenceBundle): CaptureEvidenceBundle {
  return mutator(structuredClone(tutorial0SyntheticCapture));
}

const square = reviewedStep('tutorial0-step-03-square-file');
const landscape = reviewedStep('tutorial0-step-05-landscape-file');

function requirement(overrides: Partial<CaptureReuseRequirement> = {}): CaptureReuseRequirement {
  return {
    logical_request_id: 'capture-request:tutorial0:square:action',
    expected_application: 'Adobe Express',
    image_state: 'action',
    requested_ui_claims: ['Create new'],
    require_target_geometry: true,
    ...overrides,
  };
}

describe('PPUX-RUN2 reuse-before-recapture', () => {
  it('reuses exact current matching evidence without requesting or launching a browser run', () => {
    const result = decideCaptureReuse(square, requirement(), tutorial0SyntheticCapture);
    expect(result.disposition).toBe('REUSE_EXISTING_CAPTURE');
    expect(result.reason_codes).toEqual([CAPTURE_REUSE_REASONS.exactCurrentEvidence]);
    expect(result.observability).toEqual({
      browser_runs_requested: 0,
      browser_runs_launched: 0,
      existing_capture_reuses: 1,
      duplicate_runs_avoided: 0,
    });
    expect(result.reused_evidence?.capture_id).toBe(tutorial0SyntheticCapture.capture?.capture_id);
    expect(result.reused_evidence?.states).toHaveLength(1);
    expect(result.reused_evidence?.states[0]).toMatchObject({
      role: 'action',
      source_index: 13,
      screenshot_reference: '013-before.png',
    });
  });

  it('reports an explicitly identified repeated satisfied request as one avoided duplicate run', () => {
    const first = decideCaptureReuse(square, requirement(), tutorial0SyntheticCapture);
    const repeated = decideCaptureReuse(
      square,
      requirement({ already_satisfied_duplicate: true }),
      tutorial0SyntheticCapture,
    );

    expect(repeated.disposition).toBe('REUSE_EXISTING_CAPTURE');
    expect(repeated.reused_evidence).toEqual(first.reused_evidence);
    expect(repeated.observability).toEqual({
      browser_runs_requested: 0,
      browser_runs_launched: 0,
      existing_capture_reuses: 1,
      duplicate_runs_avoided: 1,
    });
  });

  it('does not claim a duplicate run was avoided when evidence is not reusable', () => {
    const result = decideCaptureReuse(
      square,
      requirement({ already_satisfied_duplicate: true }),
      null,
    );

    expect(result.disposition).toBe('CAPTURE_REQUIRED');
    expect(result.observability.duplicate_runs_avoided).toBe(0);
  });

  it('is deterministic for an identical repeated request and returns the same evidence identity', () => {
    const first = decideCaptureReuse(square, requirement(), tutorial0SyntheticCapture);
    const second = decideCaptureReuse(square, requirement(), tutorial0SyntheticCapture);
    expect(second).toEqual(first);
    expect(second.observability.browser_runs_launched).toBe(0);
  });

  it('requires capture when recording SHA drifts', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      capture: value.capture && { ...value.capture, source: { recording_sha256: 'e'.repeat(64) } },
    }));
    const result = decideCaptureReuse(square, requirement(), bundle);
    expect(result.disposition).toBe('CAPTURE_REQUIRED');
    expect(result.reason_codes).toContain(CAPTURE_REUSE_REASONS.recordingMismatch);
    expect(result.observability.browser_runs_requested).toBe(1);
    expect(result.reused_evidence).toBeNull();
  });

  it('requires capture when source index matches but fingerprint differs', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      capture: value.capture && {
        ...value.capture,
        actions: value.capture.actions.map((action) =>
          action.source_index === 13 ? { ...action, source_fingerprint: 'f'.repeat(64) } : action),
      },
    }));
    const result = decideCaptureReuse(square, requirement(), bundle);
    expect(result.disposition).toBe('CAPTURE_REQUIRED');
    expect(result.reason_codes).toContain(CAPTURE_REUSE_REASONS.actionIdentityMismatch);
  });

  it('does not let before-state evidence satisfy a requested result-state', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.filter(
        (approval) => !(approval.source_index === 13 && approval.screenshot_role === 'after'),
      ),
    }));
    const result = decideCaptureReuse(
      square,
      requirement({ image_state: 'result', requested_ui_claims: [] }),
      bundle,
    );
    expect(result.disposition).toBe('CAPTURE_REQUIRED');
    expect(result.reason_codes).toContain(CAPTURE_REUSE_REASONS.screenStateMissing);
  });

  it('requires capture for stale current evidence', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 13
          ? { ...approval, compatibility: { ...approval.compatibility, freshness: { stale: true } } }
          : approval),
    }));
    const result = decideCaptureReuse(square, requirement(), bundle);
    expect(result.disposition).toBe('CAPTURE_REQUIRED');
    expect(result.reason_codes).toContain(CAPTURE_REUSE_REASONS.staleEvidence);
  });

  it('routes unresolved privacy to manual review and does not spend browser compute to hide ambiguity', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 13
          ? {
              ...approval,
              artifact_manifest: {
                ...approval.artifact_manifest,
                asset: { ...approval.artifact_manifest.asset, privacy_resolved: false },
              },
            }
          : approval),
    }));
    const result = decideCaptureReuse(square, requirement(), bundle);
    expect(result.disposition).toBe('MANUAL_REVIEW_REQUIRED');
    expect(result.reason_codes).toContain(CAPTURE_REUSE_REASONS.privacyUnresolved);
    expect(result.observability.browser_runs_requested).toBe(0);
    expect(result.observability.browser_runs_launched).toBe(0);
  });

  it('routes conflicting application identity to manual review', () => {
    const result = decideCaptureReuse(square, requirement({ expected_application: 'Figma' }), tutorial0SyntheticCapture);
    expect(result.disposition).toBe('MANUAL_REVIEW_REQUIRED');
    expect(result.reason_codes).toEqual([CAPTURE_REUSE_REASONS.applicationIdentityConflict]);
    expect(result.observability.browser_runs_requested).toBe(0);
  });

  it('requires capture when exact state-local geometry is required but missing', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      capture: value.capture && {
        ...value.capture,
        actions: value.capture.actions.map((action) =>
          action.source_index === 13 ? { ...action, target_geometry: null } : action),
      },
    }));
    const result = decideCaptureReuse(square, requirement(), bundle);
    expect(result.disposition).toBe('CAPTURE_REQUIRED');
    expect(result.reason_codes).toEqual([CAPTURE_REUSE_REASONS.requiredTargetGeometryMissing]);
  });

  it('reuses complete action+result evidence only when both exact states satisfy the request', () => {
    const result = decideCaptureReuse(
      landscape,
      requirement({
        logical_request_id: 'capture-request:tutorial0:landscape:both',
        image_state: 'action+result',
        requested_ui_claims: ['Landscape'],
      }),
      tutorial0SyntheticCapture,
    );
    expect(result.disposition).toBe('REUSE_EXISTING_CAPTURE');
    expect(result.reused_evidence?.states.map((state) => state.role)).toEqual(['action', 'result']);
    expect(result.observability.existing_capture_reuses).toBe(1);
  });

  it('requires capture when no existing governed evidence is supplied', () => {
    const result = decideCaptureReuse(square, requirement(), null);
    expect(result.disposition).toBe('CAPTURE_REQUIRED');
    expect(result.reason_codes).toEqual([CAPTURE_REUSE_REASONS.missingEvidence]);
    expect(result.observability.browser_runs_requested).toBe(1);
  });

  it('routes conflicting evidence status to manual review with zero browser invocation', () => {
    const result = decideCaptureReuse(
      square,
      requirement(),
      { ...tutorial0SyntheticCapture, status: 'manual-review-required' },
    );
    expect(result.disposition).toBe('MANUAL_REVIEW_REQUIRED');
    expect(result.reason_codes).toEqual([CAPTURE_REUSE_REASONS.manualReviewStatus]);
    expect(result.observability.browser_runs_requested).toBe(0);
  });

  it('never grants downstream readiness, publication, provider, or external-write authority', () => {
    const result = decideCaptureReuse(square, requirement(), tutorial0SyntheticCapture);
    expect(result.picture_perfect_ready).toBe(false);
    expect(result.classroom_ready).toBe(false);
    expect(result.publication_authorized).toBe(false);
    expect(result.provider_execution_authorized).toBe(false);
    expect(result.external_write_authorized).toBe(false);
  });
});
