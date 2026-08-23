import { describe, expect, it } from 'vitest';
import {
  CAPTURE_BLOCKER_REASONS,
  bindCaptureEvidence,
  type CaptureEvidenceBundle,
} from './captureEvidence';
import { buildPortablePrompt, projectReviewedStepToVisualSpecification, type PromptAuthoringInput } from './promptIntent';
import { tutorial0SyntheticCapture } from './fixtures/tutorial0-capture';
import {
  tutorial0BlockedFinalState,
  tutorial0CapturedPromptCards,
  tutorial0ReviewedTutorial,
} from './fixtures/tutorial0-prompts';

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
const combinedLocation = reviewedStep('tutorial0-step-01-organize-location');

const squareAuthoring: PromptAuthoringInput = {
  imagePurpose: 'Show where a student starts a new reference file.',
  imageState: 'action',
  applicationContext: 'Adobe Express workspace',
  targetState: 'Create new is the clear next action',
  mustShow: ['Adobe Express', 'Create new'],
  mustNotShow: ['student data'],
  annotationSpace: 'beside Create new',
  requestedUiDetails: ['Create new'],
};

describe('PPUX-F2 capture evidence binding', () => {
  it('binds action to before-state, result to after-state, and action+result to both without flattening', () => {
    const action = bindCaptureEvidence(square, 'action', ['Create new'], tutorial0SyntheticCapture);
    expect(action.blocker_reasons).toEqual([]);
    expect(action.evidence?.action?.role).toBe('action');
    expect(action.evidence?.action?.source_index).toBe(13);
    expect(action.evidence?.result).toBeNull();

    const result = bindCaptureEvidence(
      combinedLocation,
      'result',
      ['Your stuff', 'Digital Media', 'Tutorial 0 - Organize My Files'],
      tutorial0SyntheticCapture,
    );
    expect(result.blocker_reasons).toEqual([]);
    expect(result.evidence?.action).toBeNull();
    expect(result.evidence?.result?.role).toBe('result');
    expect(result.evidence?.result?.source_index).toBe(12);

    const both = bindCaptureEvidence(landscape, 'action+result', ['Landscape'], tutorial0SyntheticCapture);
    expect(both.blocker_reasons).toEqual([]);
    expect(both.evidence?.action?.source_index).toBe(20);
    expect(both.evidence?.result?.source_index).toBe(20);
    expect(both.evidence?.action?.screenshot_reference).toBe('020-before.png');
    expect(both.evidence?.result?.screenshot_reference).toBe('020-after.png');
  });

  it('fails closed when source_index matches but source_fingerprint differs', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      capture: value.capture && {
        ...value.capture,
        actions: value.capture.actions.map((action) =>
          action.source_index === 13 ? { ...action, source_fingerprint: 'f'.repeat(64) } : action),
      },
    }));
    expect(bindCaptureEvidence(square, 'action', ['Create new'], bundle).blocker_reasons)
      .toContain(CAPTURE_BLOCKER_REASONS.captureActionIdentityMismatch);
  });

  it('fails closed as stale on recording identity mismatch and never rebinds by index', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      capture: value.capture && { ...value.capture, source: { recording_sha256: 'e'.repeat(64) } },
    }));
    expect(bindCaptureEvidence(square, 'action', ['Create new'], bundle).blocker_reasons)
      .toEqual([CAPTURE_BLOCKER_REASONS.captureRecordingMismatch]);
  });

  it.each(['invalid', 'blocked', 'stale', 'manual-review-required'] as const)(
    'refuses capture preflight status %s entirely',
    (status) => {
      const bundle = { ...tutorial0SyntheticCapture, status };
      expect(bindCaptureEvidence(square, 'action', ['Create new'], bundle).blocker_reasons)
        .toEqual([CAPTURE_BLOCKER_REASONS.captureStatusInvalid]);
    },
  );

  it('requires both roles for action+result and never substitutes before-state for result-state', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.filter(
        (approval) => !(approval.source_index === 20 && approval.screenshot_role === 'after'),
      ),
    }));
    const result = bindCaptureEvidence(landscape, 'action+result', ['Landscape'], bundle);
    expect(result.evidence).toBeNull();
    expect(result.blocker_reasons).toContain(CAPTURE_BLOCKER_REASONS.captureScreenStateMissing);
  });

  it('keeps target geometry local to the exact action supplying the screenshot', () => {
    const result = bindCaptureEvidence(
      combinedLocation,
      'result',
      ['Your stuff', 'Digital Media', 'Tutorial 0 - Organize My Files'],
      tutorial0SyntheticCapture,
    );
    expect(result.evidence?.result?.source_index).toBe(12);
    expect(result.evidence?.result?.target_geometry).toEqual({
      target_x: 52,
      target_y: 72,
      target_width: 180,
      target_height: 44,
    });
  });

  it('does not union claims across screenshots or combined reviewed actions', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 12 && approval.screenshot_role === 'after'
          ? { ...approval, visible_ui_claims: ['Your stuff', 'Digital Media'] }
          : approval),
    }));
    const result = bindCaptureEvidence(
      combinedLocation,
      'result',
      ['Your stuff', 'Digital Media', 'Tutorial 0 - Organize My Files'],
      bundle,
    );
    expect(result.evidence).toBeNull();
    expect(result.blocker_reasons).toContain(CAPTURE_BLOCKER_REASONS.captureClaimsNotCoVisible);
  });

  it('keeps stale capture evidence out of Ready', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 13 ? { ...approval, compatibility: { ...approval.compatibility, stale: true } } : approval),
    }));
    expect(bindCaptureEvidence(square, 'action', ['Create new'], bundle).blocker_reasons)
      .toContain(CAPTURE_BLOCKER_REASONS.captureStale);
  });

  it('keeps unresolved privacy out of Ready and does not treat a stored crop/reference as clearance', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 13
          ? { ...approval, artifact_manifest: { ...approval.artifact_manifest, privacy_resolved: false } }
          : approval),
    }));
    expect(bindCaptureEvidence(square, 'action', ['Create new'], bundle).blocker_reasons)
      .toContain(CAPTURE_BLOCKER_REASONS.capturePrivacyUnresolved);
  });

  it('reuses the canonical interface-capture/screen-capture eligibility result instead of accepting another medium', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 13
          ? { ...approval, compatibility: { ...approval.compatibility, medium: 'digital' } }
          : approval),
    }));
    expect(bindCaptureEvidence(square, 'action', ['Create new'], bundle).blocker_reasons)
      .toContain(CAPTURE_BLOCKER_REASONS.captureAssetIneligible);
  });

  it('keeps missing capture fail-closed and ignores the legacy opaque capturedScreenRef escape hatch', () => {
    const spec = projectReviewedStepToVisualSpecification(
      square,
      squareAuthoring,
      tutorial0ReviewedTutorial,
    );
    const card = buildPortablePrompt({ ...spec, capturedScreenRef: 'legacy-opaque-reference' });
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(CAPTURE_BLOCKER_REASONS.captureScreenStateMissing);
    expect(card.portablePrompt).toBe('');
  });

  it('proves the synthetic ready path without making any live Adobe fidelity claim', () => {
    expect(tutorial0CapturedPromptCards).toHaveLength(3);
    for (const card of tutorial0CapturedPromptCards) {
      expect(card.status).toBe('ready');
      expect(card.requiresScreenFidelity).toBe(true);
      expect(card.capturedScreenEvidence).not.toBeNull();
      expect(card.portablePrompt).toContain('approved captured screen evidence');
      expect(card.portablePrompt).toContain('Do not redraw, imitate, reconstruct, or invent');
      expect(card.portablePrompt).not.toMatch(/live Adobe|screen-accurate|selector stability/i);
    }
    expect(tutorial0BlockedFinalState.status).toBe('blocked');
  });
});
