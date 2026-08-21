import { fireEvent, render, screen, within } from '@testing-library/react';
import tutorialRecording from './fixtures/tutorial0-recording.json';
import { App } from './App';

async function reachReview() {
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue to Upload' }));
  fireEvent.change(screen.getByLabelText('Choose Recorder JSON'), { target: { files: [new File([JSON.stringify(tutorialRecording)], 'recording.json')] } });
  await screen.findByRole('heading', { name: 'Recording loaded' });
  fireEvent.click(screen.getByRole('button', { name: 'Continue to Review' }));
  fireEvent.click(screen.getByRole('button', { name: 'Start Review' }));
}

async function reachPrompts() {
  await reachReview();
  const cards = screen.getAllByRole('article');
  fireEvent.click(within(cards[0]!).getByRole('button', { name: 'Keep & Continue' }));
  fireEvent.click(within(cards[1]!).getByRole('button', { name: 'Combine with Previous' }));
  for (let index = 2; index < cards.length - 1; index += 1) fireEvent.click(within(cards[index]!).getByRole('button', { name: 'Keep & Continue' }));
  fireEvent.click(within(cards[cards.length - 1]!).getByRole('button', { name: 'Not Instructional' }));
  fireEvent.click(screen.getByRole('button', { name: 'Approve Tutorial' }));
  await screen.findByRole('heading', { name: 'Picture Perfect prompts' });
}

describe('Picture Perfect Coach review and Ready UX', () => {
  it('shows five stages and activates Review', async () => {
    await reachReview();
    expect(screen.getByText('Review').closest('li')?.getAttribute('aria-current')).toBe('step');
  });

  it('renders exception-first review cards with explicit teacher decisions', async () => {
    await reachReview();
    expect(screen.getByText(/steps look clear/i)).toBeTruthy();
    expect(screen.getByText(/things need your attention/i)).toBeTruthy();
    const review = screen.getByLabelText('Review steps');
    expect(within(review).getAllByRole('article').length).toBeGreaterThan(1);
    expect(screen.getAllByRole('button', { name: 'Combine with Previous' })[0]?.hasAttribute('disabled')).toBe(true);
  });

  it('keeps source details collapsed and does not expose raw Recorder fields', async () => {
    await reachReview();
    const details = screen.getAllByText('View source details')[0]?.closest('details');
    expect(details?.hasAttribute('open')).toBe(false);
    expect(document.body.textContent).not.toMatch(/new\.express\.adobe\.test/i);
    expect(document.body.textContent).not.toMatch(/data-testid/i);
  });

  it('blocks approval until every modeled step has an explicit decision', async () => {
    await reachReview();
    expect(screen.getByRole('button', { name: 'Approve Tutorial' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByText(/Every modeled step needs an explicit review decision/i)).toBeTruthy();
  });

  it('reaches Prompts and blocks every software-interface frame that has no screen evidence', async () => {
    await reachPrompts();
    expect(screen.getAllByText('Application: Adobe Express').length).toBeGreaterThan(0);
    expect(screen.getByText('Prompts').closest('li')?.getAttribute('aria-current')).toBe('step');

    // Tutorial 0 frames all claim the real Adobe Express interface, and no capture
    // evidence is bound yet, so none may offer a generated stand-in prompt.
    expect(screen.getAllByText('Prompt blocked').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Software interface — needs screen capture').length).toBeGreaterThan(0);
    expect(screen.queryByLabelText('Portable prompt')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Copy Prompt' })).toBeNull();
    expect(screen.getAllByText('visual-evidence-missing').length).toBeGreaterThan(0);
  });

  it('keeps Ready fail-closed and the handoff packet ungenerated while evidence is missing', async () => {
    await reachPrompts();
    fireEvent.click(screen.getByRole('button', { name: 'Open Ready' }));
    expect(await screen.findByRole('heading', { name: 'Implementation handoff preflight' })).toBeTruthy();
    expect(screen.getByText('Ready').closest('li')?.getAttribute('aria-current')).toBe('step');

    expect(screen.getByText(/^Blocked · Captured screen evidence bound where required$/)).toBeTruthy();

    const create = screen.getByRole('button', { name: 'Create GitHub Handoff' });
    expect(create.hasAttribute('disabled')).toBe(true);
    expect(screen.queryByLabelText('GitHub handoff packet')).toBeNull();
    expect(screen.getByText(/Create GitHub Handoff stays disabled until every required preflight row passes/i)).toBeTruthy();
  });
});
