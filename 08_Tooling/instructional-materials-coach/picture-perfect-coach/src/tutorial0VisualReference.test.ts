import { describe, expect, it } from 'vitest';
import {
  BLOCKER_REASONS,
  assertProviderAdapterPreservesIntent,
  projectReviewedTutorialToPromptCards,
  validateApplicationFidelity,
} from './promptIntent';
import {
  tutorial0BlockedFinalState,
  tutorial0CapturedPromptCards,
  tutorial0CurrentReferencePromptCards,
  tutorial0CurrentVisualReferences,
  tutorial0ReconciledCreateCard,
  tutorial0ReviewedTutorial,
} from './fixtures/tutorial0-prompts';
import { tutorial0SyntheticCapture } from './fixtures/tutorial0-capture';
import type { PromptAuthoringInput } from './promptIntent';
import { buildSyntheticApprovedVisualReference } from './visualReference';

describe('PPUX-VRL2 Tutorial 0 current-reference integration', () => {
  it('selects only navigation/your-stuff/files for the Your Stuff frame', () => {
    const card = tutorial0CurrentReferencePromptCards.find(
      (item) => item.currentVisualReference?.context_state === 'navigation/your-stuff/files',
    );
    expect(card).toBeDefined();
    expect(card?.status).toBe('ready');
    expect(card?.portablePrompt).toContain('visual-reference://navigation-your-stuff-files');
    expect(card?.portablePrompt).not.toContain('Create file');
    expect(card?.portablePrompt).not.toContain('creation/get-started');
    expect(validateApplicationFidelity(card!)).toEqual([]);
  });

  it('does not let historical Create new become Ready against current Create file evidence', () => {
    const card = tutorial0CurrentReferencePromptCards.find(
      (item) => item.blockerReasons.includes(BLOCKER_REASONS.visualReferenceCurrentRecordedUiConflict),
    );
    expect(card).toBeDefined();
    expect(card?.status).toBe('blocked');
    expect(card?.portablePrompt).toBe('');
  });

  it('emits reconciled Create -> Create file from the exact current create-menu reference', () => {
    expect(tutorial0ReconciledCreateCard.status).toBe('ready');
    expect(tutorial0ReconciledCreateCard.currentVisualReference?.context_state).toBe('navigation/create-menu');
    expect(tutorial0ReconciledCreateCard.portablePrompt).toContain('Create');
    expect(tutorial0ReconciledCreateCard.portablePrompt).toContain('Create file');
    expect(tutorial0ReconciledCreateCard.portablePrompt).toContain('visual-reference://navigation-create-menu');
    expect(tutorial0ReconciledCreateCard.provenance.some((item) => item.startsWith('recording:'))).toBe(true);
    expect(validateApplicationFidelity(tutorial0ReconciledCreateCard)).toEqual([]);
  });

  it('selects creation/get-started only when Landscape and 16:9 are co-visible there', () => {
    const card = tutorial0CurrentReferencePromptCards.find(
      (item) => item.currentVisualReference?.context_state === 'creation/get-started',
    );
    expect(card).toBeDefined();
    expect(card?.status).toBe('ready');
    expect(card?.currentVisualReference?.visible_ui_claims).toEqual(expect.arrayContaining(['Landscape', '16:9']));
    expect(card?.portablePrompt).not.toContain('editor/');
    expect(validateApplicationFidelity(card!)).toEqual([]);
  });

  it('cannot union claims across two current visual references', () => {
    const splitLibrary = {
      references: [
        buildSyntheticApprovedVisualReference('creation/get-started', ['Adobe Express', 'Landscape']),
        buildSyntheticApprovedVisualReference('creation/get-started', ['Adobe Express', '16:9'], { reference_id: 'second-get-started' }),
      ],
    };
    const authoring = new Map<string, PromptAuthoringInput>([[
      'tutorial0-step-05-landscape-file',
      {
        imagePurpose: 'p', imageState: 'action+result', applicationContext: 'current get started',
        targetState: 'Landscape 16:9', mustShow: ['Adobe Express', 'Landscape', '16:9'], mustNotShow: [],
        annotationSpace: 'a', requestedUiDetails: ['Landscape'], applicationVariant: 'Education',
        currentVisualReferenceContextState: 'creation/get-started',
        currentVisualReferenceRequiredUiDetails: ['Landscape', '16:9'],
      },
    ]]);
    const card = projectReviewedTutorialToPromptCards(
      tutorial0ReviewedTutorial,
      authoring,
      tutorial0SyntheticCapture,
      splitLibrary,
    )[0];
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.visualReferenceClaimsNotCoVisible);
  });

  it('fails closed when current-reference fidelity is required but the state is missing', () => {
    const authoring = new Map<string, PromptAuthoringInput>([[
      'tutorial0-step-01-organize-location',
      {
        imagePurpose: 'p', imageState: 'result', applicationContext: 'current files', targetState: 'files',
        mustShow: ['Adobe Express', 'Your stuff'], mustNotShow: [], annotationSpace: 'a', requestedUiDetails: ['Your stuff'],
        applicationVariant: 'Education', currentVisualReferenceContextState: 'navigation/missing-state',
        currentVisualReferenceRequiredUiDetails: ['Your stuff'],
      },
    ]]);
    const card = projectReviewedTutorialToPromptCards(
      tutorial0ReviewedTutorial,
      authoring,
      tutorial0SyntheticCapture,
      tutorial0CurrentVisualReferences,
    )[0];
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.visualReferenceMissing);
  });

  it('does not weaken the existing final filename/arrangement uncertainty', () => {
    expect(tutorial0BlockedFinalState.status).toBe('blocked');
    expect(tutorial0BlockedFinalState.portablePrompt).toBe('');
    expect(tutorial0BlockedFinalState.blockerReasons).toContain(BLOCKER_REASONS.uiClaimUnsupported);
  });

  it('keeps historical capture-only Tutorial 0 frames blocked when current reference is required', () => {
    for (const card of tutorial0CapturedPromptCards) {
      expect(card.status).toBe('blocked');
      expect(card.blockerReasons).toContain(BLOCKER_REASONS.visualReferenceMissing);
    }
  });

  it('provider adapters must preserve current-reference boundary and identity', () => {
    const source = tutorial0ReconciledCreateCard;
    expect(source.status).toBe('ready');
    const withoutBoundary = source.portablePrompt.replace(
      'Use only the selected approved current application-state reference. Do not redraw, reconstruct, invent, or merge controls, labels, geometry, or states from another reference.',
      '',
    );
    expect(assertProviderAdapterPreservesIntent(source, withoutBoundary)).toContain(
      'provider adapter removed current-reference non-reconstruction boundary',
    );
    const withoutIdentity = source.portablePrompt.replace(source.currentVisualReference!.reference_id, 'reference-redacted');
    expect(assertProviderAdapterPreservesIntent(source, withoutIdentity)).toContain(
      'provider adapter removed current-reference identity',
    );
  });
});
