import { describe, expect, it } from 'vitest';
import { tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import type { PromptAuthoringInput } from './promptIntent';
import { buildTutorialPackage, type RoutedTutorialNeed } from './tutorialPackage';

const authoring: PromptAuthoringInput = {
  imagePurpose: 'Show the modeled result without reconstructing unsupported interface details.',
  imageState: 'result',
  applicationContext: '',
  targetState: 'the modeled result is visible',
  mustShow: ['modeled result'],
  mustNotShow: ['invented controls'],
  annotationSpace: 'right side',
  requestedUiDetails: [],
};

function route(overrides: Partial<RoutedTutorialNeed> = {}): RoutedTutorialNeed {
  return {
    routeId: 'route-tutorial0-core',
    representation: 'tutorial-process',
    sourceHandoffRef: 'curriculum-workflow-handoff://unit0/modeling',
    sourceFingerprint: 'handoff-fingerprint-v1',
    objectiveRef: 'objective://unit0/files',
    successCriteriaRef: 'criteria://unit0/files',
    evidenceTargetRef: 'evidence://unit0/files',
    steps: tutorial0ReviewedTutorial.retained_steps.map((step, index) => ({
      reviewStepId: step.review_step_id,
      visualRoleRef: index === 0 ? 'visual-role://teacher-model' : 'visual-role://process-sequence',
      disposition: index === 0 ? 'new-visual' : 'no-additional-visual-needed',
      ...(index === 0 ? { authoring } : { reasonRef: 'route-reason://core/no-extra-frame' }),
    })),
    ...overrides,
  };
}

describe('PPUX #1776 routed Tutorial Package', () => {
  it('builds a reusable package only for an explicit tutorial-process route', () => {
    const result = buildTutorialPackage(tutorial0ReviewedTutorial, route());
    expect(result.status).toBe('valid');
    expect(result.package?.packageVersion).toBe('picture-perfect-tutorial-package-v1');
    expect(result.package?.cards).toHaveLength(1);
    expect(result.package?.steps).toHaveLength(tutorial0ReviewedTutorial.retained_steps.length);
    expect(result.package?.productionAuthorized).toBe(false);
    expect(result.package?.externalWriteAuthorized).toBe(false);
  });

  it('blocks when routing evidence is absent rather than inferring that every reviewed tutorial needs PPUX', () => {
    expect(buildTutorialPackage(tutorial0ReviewedTutorial, null)).toEqual({
      status: 'blocked', package: null, blockers: ['route-missing'],
    });
  });

  it('blocks a missing retained-step disposition instead of silently skipping the step', () => {
    const incomplete = route({ steps: route().steps.slice(0, -1) });
    expect(buildTutorialPackage(tutorial0ReviewedTutorial, incomplete).blockers).toContain('step-disposition-missing');
  });

  it('allows explicit reuse and resurfacing without creating phantom prompt cards', () => {
    const steps = route().steps.map((step, index) => index === 0
      ? { ...step, disposition: 'reuse-existing-visual' as const, authoring: undefined, approvedAssetRef: 'visual-asset://approved/tutorial-frame-1' }
      : index === 1
        ? { ...step, disposition: 'resurface-prior-visual' as const, approvedAssetRef: 'visual-asset://approved/tutorial-frame-1', reasonRef: undefined }
        : step);
    const result = buildTutorialPackage(tutorial0ReviewedTutorial, route({ steps }));
    expect(result.status).toBe('valid');
    expect(result.package?.cards).toHaveLength(0);
    expect(result.package?.reusedAssetRefs).toEqual(['visual-asset://approved/tutorial-frame-1']);
    expect(result.package?.resurfacedAssetRefs).toEqual(['visual-asset://approved/tutorial-frame-1']);
  });

  it('requires reason evidence for intentional no-additional and compacted dispositions', () => {
    const steps = route().steps.map((step, index) => index === 2 ? { ...step, reasonRef: undefined } : step);
    expect(buildTutorialPackage(tutorial0ReviewedTutorial, route({ steps })).blockers).toContain('reason-evidence-missing');
  });

  it('rejects a route entry for a non-retained/raw step', () => {
    const steps = [...route().steps, {
      reviewStepId: 'raw-recorder-step-not-retained',
      visualRoleRef: 'visual-role://process-sequence',
      disposition: 'no-additional-visual-needed' as const,
      reasonRef: 'route-reason://not-needed',
    }];
    expect(buildTutorialPackage(tutorial0ReviewedTutorial, route({ steps })).blockers).toContain('step-not-retained');
  });
});
