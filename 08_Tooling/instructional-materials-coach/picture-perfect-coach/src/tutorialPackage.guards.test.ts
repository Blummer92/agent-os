import { describe, expect, it } from 'vitest';
import { tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import type { PromptAuthoringInput } from './promptIntent';
import type { ReviewedTutorialProjection } from './types';
import { buildTutorialPackage, type RoutedTutorialNeed } from './tutorialPackage';

/**
 * Nov 3 mutation evidence PP2/PP3. The routed Tutorial Package builder is the
 * production consumer behind App.tsx and promptProjectionEntrypoint.ts. Two guards
 * protect it from conflicting route entries: the duplicate-disposition blocker and
 * the projected-card-count tripwire. Each shadowed the other, so removing either
 * (or both) left every test green. Each case changes exactly one input and asserts
 * the exact blocker list and that no partial package is returned.
 */
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

const retained = tutorial0ReviewedTutorial.retained_steps;

function route(overrides: Partial<RoutedTutorialNeed> = {}): RoutedTutorialNeed {
  return {
    routeId: 'route-tutorial0-guards',
    representation: 'tutorial-process',
    sourceHandoffRef: 'curriculum-workflow-handoff://unit0/modeling',
    sourceFingerprint: 'handoff-fingerprint-v1',
    objectiveRef: 'objective://unit0/files',
    successCriteriaRef: 'criteria://unit0/files',
    evidenceTargetRef: 'evidence://unit0/files',
    steps: retained.map((step, index) => ({
      reviewStepId: step.review_step_id,
      visualRoleRef: index === 0 ? 'visual-role://teacher-model' : 'visual-role://process-sequence',
      disposition: index === 0 ? 'new-visual' : 'no-additional-visual-needed',
      ...(index === 0 ? { authoring } : { reasonRef: 'route-reason://core/no-extra-frame' }),
    })),
    ...overrides,
  } as RoutedTutorialNeed;
}

function assertNoPartialPackage(result: ReturnType<typeof buildTutorialPackage>) {
  expect(result.status).toBe('blocked');
  expect(result.package).toBeNull();
}

describe('PPUX routed Tutorial Package: conflicting route entries never yield a package', () => {
  it('positive control: one disposition per retained step builds the package', () => {
    const result = buildTutorialPackage(tutorial0ReviewedTutorial, route());
    expect(result.status).toBe('valid');
    expect(result.blockers).toEqual([]);
    expect(result.package?.cards).toHaveLength(1);
    expect(result.package?.steps).toHaveLength(retained.length);
    expect(result.package?.productionAuthorized).toBe(false);
  });

  it('blocks a repeated identical disposition for one retained step with exactly the duplicate blocker', () => {
    const base = route();
    const result = buildTutorialPackage(
      tutorial0ReviewedTutorial,
      route({ steps: [base.steps[0], base.steps[0], ...base.steps.slice(1)] }),
    );
    assertNoPartialPackage(result);
    expect(result.blockers).toEqual(['step-disposition-duplicate']);
  });

  it('blocks conflicting dispositions for one retained step instead of silently picking one', () => {
    const base = route();
    const conflicting = {
      reviewStepId: base.steps[0].reviewStepId,
      visualRoleRef: 'visual-role://process-sequence',
      disposition: 'no-additional-visual-needed',
      reasonRef: 'route-reason://core/no-extra-frame',
    } as RoutedTutorialNeed['steps'][number];
    const result = buildTutorialPackage(
      tutorial0ReviewedTutorial,
      route({ steps: [base.steps[0], conflicting, ...base.steps.slice(1)] }),
    );
    // Without the duplicate guard the new-visual card count still matches (1), so
    // the only thing between this route and a "valid" package is that guard.
    assertNoPartialPackage(result);
    expect(result.blockers).toEqual(['step-disposition-duplicate']);
  });

  it('trips the card-count consistency check when the reviewed tutorial repeats a retained step', () => {
    const malformed: ReviewedTutorialProjection = {
      ...tutorial0ReviewedTutorial,
      retained_steps: [retained[0], ...retained],
    };
    // The route is well formed (one disposition per distinct step), so no earlier
    // blocker fires; the projection would emit two cards for one new visual.
    const result = buildTutorialPackage(malformed, route());
    assertNoPartialPackage(result);
    expect(result.blockers).toEqual(['new-visual-authoring-missing']);
  });
});
