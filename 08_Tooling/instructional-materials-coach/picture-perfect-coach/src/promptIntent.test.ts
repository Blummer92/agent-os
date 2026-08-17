import { describe, expect, it } from 'vitest';
import {
  assertProviderAdapterPreservesIntent,
  buildPortablePrompt,
  validateApplicationFidelity,
  type VisualSpecification,
} from './promptIntent';
import { tutorial0BlockedFinalState, tutorial0PromptCards } from './fixtures/tutorial0-prompts';

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
