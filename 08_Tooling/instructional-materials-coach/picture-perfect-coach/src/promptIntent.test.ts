import { describe, expect, it } from 'vitest';
import {
  assertProviderAdapterPreservesIntent,
  buildPortablePrompt,
  projectReviewedStepToVisualSpecification,
  projectReviewedTutorialToPromptCards,
  validateApplicationFidelity,
  type PromptAuthoringInput,
  type VisualSpecification,
} from './promptIntent';
import { tutorial0BlockedFinalState, tutorial0PromptCards, tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import type { ReviewedStepProjection, ReviewedTutorialProjection } from './types';

const adobeSpec: VisualSpecification = {
  stepNumber: 1,
  imagePurpose: 'Show where to create a file.',
  imageState: 'action',
  application: 'Adobe Express',
  applicationContext: 'Adobe Express workspace navigation',
  targetState: 'Create new file is visible',
  mustShow: ['Adobe Express', 'Create new file'],
  mustNotShow: ['invented controls'],
  annotationSpace: 'beside Create new file',
  provenance: ['approved Teacher Modeling', 'approved Recorder evidence'],
  evidenceSupportedUiDetails: ['Create new file'],
  requestedUiDetails: ['Create new file'],
};

describe('PPUX-C application identity fidelity', () => {
  it('preserves Adobe Express identity in Tutorial 0 portable prompts', () => {
    expect(tutorial0PromptCards).toHaveLength(3);
    for (const card of tutorial0PromptCards) {
      expect(card.status).toBe('ready');
      expect(card.application).toBe('Adobe Express');
      expect(card.portablePrompt).toContain('visibly and unmistakably depict Adobe Express');
      expect(validateApplicationFidelity(card)).toEqual([]);
    }
  });

  it('rejects an application-neutral prompt', () => {
    const card = buildPortablePrompt(adobeSpec);
    const generic = { ...card, portablePrompt: card.portablePrompt.replaceAll('Adobe Express', 'generic creative application') };
    expect(validateApplicationFidelity(generic)).toContain('portable prompt lost modeled application identity');
  });

  it('rejects a wrong-app substitution', () => {
    const card = buildPortablePrompt(adobeSpec);
    const wrong = { ...card, portablePrompt: card.portablePrompt.replace('depict Adobe Express', 'depict Canva') };
    expect(validateApplicationFidelity(wrong)).toContain('portable prompt substituted wrong application: Canva');
  });

  it('rejects a generic diagram that drops required software-interface context', () => {
    const card = buildPortablePrompt(adobeSpec);
    const diagram = { ...card, portablePrompt: `Diagram for ${card.application}: ${card.targetState}. Must show Adobe Express and Create new file.` };
    expect(validateApplicationFidelity(diagram)).toContain('portable prompt lost software-interface requirement');
    expect(validateApplicationFidelity(diagram)).toContain('portable prompt lost application context');
  });

  it('rejects provider-specific canonical syntax', () => {
    const card = buildPortablePrompt(adobeSpec);
    const providerSpecific = { ...card, portablePrompt: `${card.portablePrompt} --ar 16:9` };
    expect(validateApplicationFidelity(providerSpecific)).toContain('canonical prompt contains provider-specific syntax: --ar ');
  });

  it('fails closed when requested UI detail is not supported by evidence', () => {
    const card = buildPortablePrompt({ ...adobeSpec, requestedUiDetails: ['Create new file', 'Magic unsupported button'] });
    expect(card.status).toBe('blocked');
    expect(card.blocker).toContain('unsupported UI detail: Magic unsupported button');
  });

  it('blocks complete software-UI output when application identity is missing', () => {
    const card = buildPortablePrompt({ ...adobeSpec, application: '' });
    expect(card.status).toBe('blocked');
    expect(card.blocker).toContain('application identity is required');
  });

  it('requires recognizable application context', () => {
    const card = buildPortablePrompt({ ...adobeSpec, applicationContext: '' });
    expect(card.status).toBe('blocked');
    expect(card.blocker).toContain('recognizable application context is required');
  });

  it('prevents provider adapters from dropping application identity or must-show evidence', () => {
    const card = buildPortablePrompt(adobeSpec);
    expect(assertProviderAdapterPreservesIntent(card, 'Create new file is visible')).toContain('provider adapter removed application identity');
    expect(assertProviderAdapterPreservesIntent(card, 'Adobe Express Create new file is visible')).toEqual([]);
  });

  it('keeps the unsupported Tutorial 0 final state blocked rather than inventing filenames', () => {
    expect(tutorial0BlockedFinalState.status).toBe('blocked');
    expect(tutorial0BlockedFinalState.blocker).toContain('unsupported UI detail: exact favorite-food filenames');
  });
});

const authoring: PromptAuthoringInput = {
  imagePurpose: 'Show the target action.',
  imageState: 'action',
  applicationContext: 'workspace navigation',
  targetState: 'Create new file is visible',
  mustShow: ['Create new file'],
  mustNotShow: [],
  annotationSpace: 'beside Create new file',
  evidenceSupportedUiDetails: ['Create new file'],
  requestedUiDetails: ['Create new file'],
};

function reviewedStep(overrides: Partial<ReviewedStepProjection>): ReviewedStepProjection {
  return {
    review_step_id: 'step-1',
    sequence: 1,
    source_step_ids: ['step-1'],
    source_steps: [],
    semantic_action_ids: ['action-1'],
    source_indexes: [1],
    recording_id: 'rec-1',
    recording_sha256: 'a'.repeat(64),
    modeled_application: 'Adobe Express',
    execution_authorized: false,
    ...overrides,
  };
}

describe('PPUX-C Stage 4 reviewed-projection consumption', () => {
  it('feeds a ReviewedTutorialProjection into Stage 4 and preserves retained order', () => {
    const tutorial: ReviewedTutorialProjection = {
      recording_id: 'rec-1',
      recording_sha256: 'a'.repeat(64),
      retained_steps: [
        reviewedStep({ review_step_id: 'a', sequence: 1 }),
        reviewedStep({ review_step_id: 'b', sequence: 2 }),
      ],
      excluded_step_ids: [],
      review_decisions: [],
      execution_authorized: false,
    };
    const authoringByStepId = new Map([
      ['a', authoring],
      ['b', authoring],
    ]);
    const cards = projectReviewedTutorialToPromptCards(tutorial, authoringByStepId);
    expect(cards.map((card) => card.stepNumber)).toEqual([1, 2]);
  });

  it('excludes Not Instructional steps from Stage 4 because they never enter retained_steps', () => {
    const tutorial: ReviewedTutorialProjection = {
      recording_id: 'rec-1',
      recording_sha256: 'a'.repeat(64),
      retained_steps: [reviewedStep({ review_step_id: 'a', sequence: 1 })],
      excluded_step_ids: ['not-instructional-step'],
      review_decisions: [{ step_id: 'not-instructional-step', choice: 'not-instructional' }],
      execution_authorized: false,
    };
    const cards = projectReviewedTutorialToPromptCards(tutorial, new Map([['a', authoring]]));
    expect(cards).toHaveLength(1);
    expect(tutorial.excluded_step_ids).not.toContain('a');
  });

  it('preserves combined-step provenance (source steps and semantic actions) into the prompt card', () => {
    const combined = reviewedStep({
      review_step_id: 'combined',
      source_step_ids: ['step-1', 'step-2'],
      semantic_action_ids: ['action-1', 'action-2'],
    });
    const spec = projectReviewedStepToVisualSpecification(combined, authoring);
    expect(spec.provenance).toEqual(expect.arrayContaining(['source_step:step-1', 'source_step:step-2', 'semantic_action:action-1', 'semantic_action:action-2']));
  });

  it('keeps execution_authorized false throughout prompt generation', () => {
    const card = buildPortablePrompt(projectReviewedStepToVisualSpecification(reviewedStep({}), authoring));
    expect(tutorial0ReviewedTutorial.execution_authorized).toBe(false);
    expect(tutorial0ReviewedTutorial.retained_steps.every((step) => step.execution_authorized === false)).toBe(true);
    expect('execution_authorized' in card).toBe(false);
  });

  it('carries modeled application identity from the reviewed step into the portable prompt', () => {
    const spec = projectReviewedStepToVisualSpecification(reviewedStep({ modeled_application: 'Adobe Express' }), authoring);
    const card = buildPortablePrompt(spec);
    expect(card.status).toBe('ready');
    expect(card.portablePrompt).toContain('Adobe Express');
  });

  it('blocks a software-UI prompt when the reviewed step has no approved application identity', () => {
    const spec = projectReviewedStepToVisualSpecification(reviewedStep({ modeled_application: null }), authoring);
    const card = buildPortablePrompt(spec);
    expect(card.status).toBe('blocked');
    expect(card.blocker).toContain('application identity is required');
  });

  it('does not infer application identity from step title or tutorial branding text alone', () => {
    const step = reviewedStep({
      modeled_application: null,
      source_steps: [{
        step_id: 'step-1',
        sequence: 1,
        disposition: 'keep',
        title: 'Organize your Adobe Express location',
        semantic_action_ids: ['action-1'],
        source: {
          candidate_id: 'c1',
          recording_id: 'rec-1',
          recording_sha256: 'a'.repeat(64),
          source_indexes: [1],
          rj3_state: 'pending',
          rj4_state: 'pending',
          modeled_application: null,
        },
        execution_authorized: false,
      }],
    });
    const spec = projectReviewedStepToVisualSpecification(step, authoring);
    expect(spec.application).toBe('');
    expect(buildPortablePrompt(spec).status).toBe('blocked');
  });

  it('Tutorial 0 happy-path cards preserve Adobe Express identity end to end from reviewed evidence', () => {
    expect(tutorial0ReviewedTutorial.retained_steps.length).toBeGreaterThan(0);
    expect(tutorial0PromptCards.length).toBeGreaterThan(0);
    for (const card of tutorial0PromptCards) {
      expect(card.application).toBe('Adobe Express');
    }
  });
});
