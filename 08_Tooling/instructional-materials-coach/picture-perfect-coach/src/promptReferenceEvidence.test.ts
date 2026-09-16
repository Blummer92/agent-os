import { describe, expect, it } from 'vitest';
import { tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import type { PromptAuthoringInput } from './promptIntent';
import { buildTutorialPackage, type RoutedTutorialNeed } from './tutorialPackage';

const historicalPromptReference = 'prompt-test://tutorial0/adobe-express/f2';

const authoring: PromptAuthoringInput = {
  imagePurpose: 'Show the modeled result without reconstructing unsupported interface details.',
  imageState: 'result',
  applicationContext: 'Adobe Express workspace',
  targetState: 'the modeled result is visible',
  mustShow: ['Adobe Express', 'modeled result'],
  mustNotShow: ['invented Adobe controls'],
  annotationSpace: 'right side',
  requestedUiDetails: [],
};

function route(): RoutedTutorialNeed {
  return {
    routeId: 'route-tutorial0-prompt-reference',
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
      ...(index === 0
        ? { authoring, promptReferenceEvidenceRefs: [historicalPromptReference] }
        : { reasonRef: 'route-reason://core/no-extra-frame' }),
    })),
  };
}

describe('PPUX #2512 prompt-testing reference evidence', () => {
  it('preserves intentionally selected prompt-testing evidence as provenance for future generated prompts', () => {
    const result = buildTutorialPackage(tutorial0ReviewedTutorial, route());

    expect(result.status).toBe('valid');
    expect(result.package?.cards[0].provenance).toContain(
      `prompt_reference_evidence:${historicalPromptReference}`,
    );
  });

  it('does not convert prompt-reference evidence into application identity authority', () => {
    const canvaTutorial = {
      ...tutorial0ReviewedTutorial,
      retained_steps: tutorial0ReviewedTutorial.retained_steps.map((step) => ({
        ...step,
        modeled_application: 'Canva',
        source_steps: step.source_steps.map((sourceStep) => ({
          ...sourceStep,
          source: { ...sourceStep.source, modeled_application: 'Canva' },
        })),
      })),
    };

    const result = buildTutorialPackage(canvaTutorial, route());

    expect(result.status).toBe('blocked');
    expect(result.blockers).toContain('application-identity-conflict');
    expect(result.package).toBeNull();
  });
});
