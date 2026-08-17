import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PromptCards } from './PromptCards';
import { tutorial0BlockedFinalState, tutorial0PromptCards } from './fixtures/tutorial0-prompts';

describe('PromptCards', () => {
  it('shows application identity, image state, portable prompt, and progressive evidence', () => {
    render(<PromptCards cards={[tutorial0PromptCards[0]]} />);
    expect(screen.getByRole('heading', { name: 'Picture Perfect prompts' })).toBeTruthy();
    expect(screen.getByText('Application: Adobe Express')).toBeTruthy();
    expect(screen.getByText('result')).toBeTruthy();
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
});
