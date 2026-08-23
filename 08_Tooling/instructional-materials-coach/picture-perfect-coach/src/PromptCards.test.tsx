import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PromptCards } from './PromptCards';
import { buildPortablePrompt, type PromptCardModel } from './promptIntent';
import { tutorial0BlockedFinalState, tutorial0PromptCards } from './fixtures/tutorial0-prompts';

/** A non-interface frame is the only kind that can render a prompt in PPUX-F1. */
const readyCard: PromptCardModel = buildPortablePrompt({
  stepNumber: 1,
  imagePurpose: 'Show the idea of grouping work by purpose.',
  imageState: 'result',
  application: 'Adobe Express',
  applicationContext: '',
  targetState: 'related work is grouped together',
  mustShow: ['three labelled groups'],
  mustNotShow: ['student data'],
  annotationSpace: 'beside the groups',
  provenance: ['approved Teacher Modeling'],
  requestedUiDetails: [],
  requiresScreenFidelity: false,
  capturedScreenRef: null,
  evidence: { sourceIndexes: [], actionIdentity: [], stateLocalClaims: [], recordingClaimTexts: [] },
});

describe('PromptCards', () => {
  it('shows application identity, image state, portable prompt, and progressive evidence for a non-interface frame', () => {
    render(<PromptCards cards={[readyCard]} />);
    expect(screen.getByRole('heading', { name: 'Picture Perfect prompts' })).toBeTruthy();
    expect(screen.getByText('Application: Adobe Express')).toBeTruthy();
    expect(screen.getByText('result')).toBeTruthy();
    expect(screen.getByText('Non-interface visual')).toBeTruthy();
    const prompt = screen.getByLabelText('Portable prompt') as HTMLTextAreaElement;
    expect(prompt.value).toContain('Adobe Express');
    expect(screen.getByRole('button', { name: 'Copy Prompt' })).toBeTruthy();
    expect(screen.getByText('View prompt evidence')).toBeTruthy();
  });

  it('shows a blocked state instead of a fabricated prompt', () => {
    render(<PromptCards cards={[tutorial0BlockedFinalState]} />);
    expect(screen.getByText('Prompt blocked')).toBeTruthy();
    expect(screen.queryByLabelText('Portable prompt')).toBeNull();
    expect(screen.getByText(/Exact favorite-food filenames/)).toBeTruthy();
  });

  it('offers no copyable prompt and names the machine-readable reasons on a blocked interface frame', () => {
    const blocked = tutorial0PromptCards.filter((card) => card.status === 'blocked');
    expect(blocked.length).toBeGreaterThan(0);
    render(<PromptCards cards={blocked} />);
    expect(screen.queryByLabelText('Portable prompt')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Copy Prompt' })).toBeNull();
    expect(screen.getAllByText('Software interface — needs screen capture').length).toBe(blocked.length);
    expect(screen.getAllByText('visual-evidence-missing').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/will not generate a\s+stand-in for the real software interface/i).length).toBeGreaterThan(0);
  });
});
