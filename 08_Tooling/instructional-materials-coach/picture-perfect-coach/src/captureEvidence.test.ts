import { describe, expect, it } from 'vitest';
import {
  CAPTURE_BLOCKER_REASONS,
  bindCaptureEvidence,
  type CaptureEvidenceBundle,
  type TargetStyleEvidence,
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
    expect(action.status).toBe('valid');
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
    expect(result.status).toBe('valid');
    expect(result.blocker_reasons).toEqual([]);
    expect(result.evidence?.action).toBeNull();
    expect(result.evidence?.result?.role).toBe('result');
    expect(result.evidence?.result?.source_index).toBe(12);

    const both = bindCaptureEvidence(landscape, 'action+result', ['Landscape'], tutorial0SyntheticCapture);
    expect(both.status).toBe('valid');
    expect(both.blocker_reasons).toEqual([]);
    expect(both.evidence?.action?.source_index).toBe(20);
    expect(both.evidence?.result?.source_index).toBe(20);
    expect(both.evidence?.action?.screenshot_reference).toBe('020-before.png');
    expect(both.evidence?.result?.screenshot_reference).toBe('020-after.png');
  });

  it('fails stale when source_index matches but source_fingerprint differs', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      capture: value.capture && {
        ...value.capture,
        actions: value.capture.actions.map((action) =>
          action.source_index === 13 ? { ...action, source_fingerprint: 'f'.repeat(64) } : action),
      },
    }));
    const result = bindCaptureEvidence(square, 'action', ['Create new'], bundle);
    expect(result.status).toBe('stale');
    expect(result.blocker_reasons).toContain(CAPTURE_BLOCKER_REASONS.captureActionIdentityMismatch);
  });

  it('fails stale on recording identity mismatch and never rebinds by index', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      capture: value.capture && { ...value.capture, source: { recording_sha256: 'e'.repeat(64) } },
    }));
    const result = bindCaptureEvidence(square, 'action', ['Create new'], bundle);
    expect(result.status).toBe('stale');
    expect(result.blocker_reasons).toEqual([CAPTURE_BLOCKER_REASONS.captureRecordingMismatch]);
  });

  it.each(['invalid', 'blocked', 'stale', 'manual-review-required'] as const)(
    'refuses capture preflight status %s entirely',
    (status) => {
      const result = bindCaptureEvidence(square, 'action', ['Create new'], { ...tutorial0SyntheticCapture, status });
      expect(result.status).toBe(status);
      expect(result.blocker_reasons).toEqual([CAPTURE_BLOCKER_REASONS.captureStatusInvalid]);
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
    expect(result.status).toBe('blocked');
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
    expect(result.status).toBe('blocked');
    expect(result.evidence).toBeNull();
    expect(result.blocker_reasons).toContain(CAPTURE_BLOCKER_REASONS.captureClaimsNotCoVisible);
  });

  it('keeps stale compatibility evidence out of Ready', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 13
          ? { ...approval, compatibility: { ...approval.compatibility, freshness: { stale: true } } }
          : approval),
    }));
    const result = bindCaptureEvidence(square, 'action', ['Create new'], bundle);
    expect(result.status).toBe('stale');
    expect(result.blocker_reasons).toContain(CAPTURE_BLOCKER_REASONS.captureStale);
  });

  it('keeps unresolved privacy out of Ready and proves cropping alone cannot establish clearance', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 13
          ? {
              ...approval,
              artifact_manifest: {
                ...approval.artifact_manifest,
                asset: {
                  ...approval.artifact_manifest.asset,
                  privacy_resolved: false,
                  transformations: ['crop'],
                },
              },
            }
          : approval),
    }));
    const result = bindCaptureEvidence(square, 'action', ['Create new'], bundle);
    expect(result.status).toBe('manual-review-required');
    expect(result.blocker_reasons).toContain(CAPTURE_BLOCKER_REASONS.capturePrivacyUnresolved);
  });

  it('reuses the canonical interface-capture/screen-capture eligibility result instead of accepting another medium', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      approved_screenshots: value.approved_screenshots.map((approval) =>
        approval.source_index === 13
          ? {
              ...approval,
              compatibility: {
                ...approval.compatibility,
                cohesion_profile: { ...approval.compatibility.cohesion_profile, medium: 'digital' },
              },
            }
          : approval),
    }));
    const result = bindCaptureEvidence(square, 'action', ['Create new'], bundle);
    expect(result.status).toBe('blocked');
    expect(result.blocker_reasons).toContain(CAPTURE_BLOCKER_REASONS.captureAssetIneligible);
  });

  it('keeps missing capture fail-closed and ignores the legacy opaque capturedScreenRef escape hatch', () => {
    const spec = projectReviewedStepToVisualSpecification(square, squareAuthoring, tutorial0ReviewedTutorial);
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

describe('PPUX-VRL6 capture v1/v2 coexistence (#1485)', () => {
  const sampleTargetStyle: TargetStyleEvidence = {
    rect_normalized: [0.1, 0.2, 0.3, 0.4],
    color_rgba: [0, 0, 0, 1],
    background_rgba: null,
    opacity: 1,
    font_family: 'Arial',
    font_size_px: 16,
    font_weight: 400,
    font_style: 'normal',
    line_height: '24px',
    letter_spacing: 'normal',
    border_radius: '4px',
    background_image: null,
    box_shadow: 'none',
    text_shadow: 'none',
    transform: 'none',
  };

  function v2BundleWithStyle(sourceIndex: number, targetStyle: TargetStyleEvidence | null): CaptureEvidenceBundle {
    const bundle = structuredClone(tutorial0SyntheticCapture);
    return {
      ...bundle,
      capture: bundle.capture && {
        ...bundle.capture,
        format_version: 'software-tutorial-capture-v2',
        actions: bundle.capture.actions.map((action) =>
          action.source_index === sourceIndex ? { ...action, target_style: targetStyle } : action),
      },
    };
  }

  it('binds capture v1 exactly as before v2 support existed', () => {
    const result = bindCaptureEvidence(square, 'action', ['Create new'], tutorial0SyntheticCapture);
    expect(result.status).toBe('valid');
    expect(result.evidence?.action?.target_style).toBeNull();
  });

  it('binds capture v2 and carries optional target_style through to bound evidence', () => {
    const bundle = v2BundleWithStyle(13, sampleTargetStyle);
    const result = bindCaptureEvidence(square, 'action', ['Create new'], bundle);
    expect(result.status).toBe('valid');
    expect(result.evidence?.action?.target_style).toEqual(sampleTargetStyle);
    expect(result.evidence?.action?.target_geometry).toEqual({
      target_x: 53,
      target_y: 73,
      target_width: 180,
      target_height: 44,
    });
  });

  it('binds capture v2 with a missing/null target_style without fabricating one', () => {
    const bundle = v2BundleWithStyle(13, null);
    const result = bindCaptureEvidence(square, 'action', ['Create new'], bundle);
    expect(result.status).toBe('valid');
    expect(result.evidence?.action?.target_style).toBeNull();
  });

  it('leaves the action fingerprint and recording identity byte-identical whether or not target_style is present', () => {
    const withStyle = v2BundleWithStyle(13, sampleTargetStyle);
    const withoutStyle = v2BundleWithStyle(13, null);
    const boundWithStyle = bindCaptureEvidence(square, 'action', ['Create new'], withStyle);
    const boundWithoutStyle = bindCaptureEvidence(square, 'action', ['Create new'], withoutStyle);
    expect(boundWithStyle.evidence?.action?.source_fingerprint).toBe(boundWithoutStyle.evidence?.action?.source_fingerprint);
    expect(withStyle.capture?.source.recording_sha256).toBe(withoutStyle.capture?.source.recording_sha256);
    expect(boundWithStyle.evidence?.action?.target_geometry).toEqual(boundWithoutStyle.evidence?.action?.target_geometry);
  });

  it('fails closed on an unknown capture format version rather than guessing at its shape', () => {
    const bundle = mutateBundle((value) => ({
      ...value,
      capture: value.capture && { ...value.capture, format_version: 'software-tutorial-capture-v3' as never },
    }));
    const result = bindCaptureEvidence(square, 'action', ['Create new'], bundle);
    expect(result.status).toBe('invalid');
    expect(result.blocker_reasons).toEqual([CAPTURE_BLOCKER_REASONS.captureStatusInvalid]);
  });
});
