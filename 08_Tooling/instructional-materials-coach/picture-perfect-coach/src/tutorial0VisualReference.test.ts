import { describe, expect, it } from 'vitest';
import { assertProviderAdapterPreservesIntent, BLOCKER_REASONS } from './promptIntent';
import {
  tutorial0BlockedFinalState,
  tutorial0CurrentReferencePromptCards,
  tutorial0ReconciledCreatePromptCard,
} from './fixtures/tutorial0-prompts';

function card(stepNumber: number) {
  const result = tutorial0CurrentReferencePromptCards.find((item) => item.stepNumber === stepNumber);
  if (!result) throw new Error(`Tutorial 0 card ${stepNumber} is missing`);
  return result;
}

describe('PPUX-VRL2 Tutorial 0 current-reference integration', () => {
  it('selects the exact Your Stuff / Files current state', () => {
    const result = card(1);
    expect(result.currentVisualReference?.context_state).toBe('navigation/your-stuff/files');
    expect(result.currentVisualReference?.visible_ui_claims).toContain('Files');
    expect(result.currentVisualReference?.visible_ui_claims).not.toContain('Create file');
  });

  it('blocks stale historical Create new against current Create / Create file', () => {
    const result = card(2);
    expect(result.status).toBe('blocked');
    expect(result.blockerReasons).toContain(BLOCKER_REASONS.currentRecordedUiConflict);
    expect(result.portablePrompt).toBe('');
  });

  it('emits a current-reference-backed Create / Create file prompt after explicit reconciliation', () => {
    const result = tutorial0ReconciledCreatePromptCard;
    expect(result.status).toBe('ready');
    expect(result.currentVisualReference?.context_state).toBe('navigation/create-menu');
    expect(result.portablePrompt).toContain('Create');
    expect(result.portablePrompt).toContain('Create file');
    expect(result.portablePrompt).toContain('visual-reference://tutorial0-create-menu');
    expect(result.portablePrompt).toContain('Do not redraw, reconstruct, invent, or merge');
  });

  it('requires Landscape and 16:9 from the same Get Started reference', () => {
    const result = card(4);
    expect(result.currentVisualReference?.context_state).toBe('creation/get-started');
    expect(result.currentVisualReference?.visible_ui_claims).toEqual(expect.arrayContaining(['Landscape', '16:9']));
    expect(result.currentVisualReference?.visible_ui_claims).not.toContain('Add content');
  });

  it('keeps missing current references fail closed when current fidelity is required', () => {
    const create = card(2);
    expect(create.currentVisualReference).toBeNull();
    expect(create.status).toBe('blocked');
  });

  it('keeps final filename and arrangement uncertainty blocked', () => {
    expect(tutorial0BlockedFinalState.status).toBe('blocked');
    expect(tutorial0BlockedFinalState.portablePrompt).toBe('');
    expect(tutorial0BlockedFinalState.blockerReasons).toContain(BLOCKER_REASONS.uiClaimUnsupported);
  });

  it('requires provider adapters to preserve current-reference identity and directive', () => {
    const source = tutorial0ReconciledCreatePromptCard;
    expect(source.status).toBe('ready');
    expect(assertProviderAdapterPreservesIntent(source, source.portablePrompt)).toEqual([]);

    const stripped = source.portablePrompt
      .replace('visual-reference://tutorial0-create-menu', 'removed-reference')
      .replace('Do not redraw, reconstruct, invent, or merge controls, labels, geometry, or states from another reference.', '');
    expect(assertProviderAdapterPreservesIntent(source, stripped)).toEqual(expect.arrayContaining([
      'provider adapter removed current visual-reference identity',
      'provider adapter removed current visual-reference non-reconstruction boundary',
    ]));
  });
});
