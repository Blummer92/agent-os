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

describe('Picture Perfect Coach review UX', () => {
  it('shows five stages and activates Review while Prompts and Ready remain later slices', async () => {
    await reachReview();
    expect(screen.getByText('Review').closest('li')?.getAttribute('aria-current')).toBe('step');
    expect(screen.getByText('Prompts').closest('li')?.getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByText('Ready').closest('li')?.getAttribute('aria-disabled')).toBe('true');
  });

  it('renders exception-first review cards with explicit teacher decisions', async () => {
    await reachReview();
    expect(screen.getByText(/steps look clear/i)).toBeTruthy();
    expect(screen.getByText(/things need your attention/i)).toBeTruthy();
    const review = screen.getByLabelText('Review steps');
    expect(within(review).getAllByRole('article').length).toBeGreaterThan(1);
    expect(screen.getAllByRole('button', { name: 'Keep & Continue' }).length).toBeGreaterThan(1);
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

  it('supports Keep, Combine, and Not Instructional then reaches only the Prompts boundary', async () => {
    await reachReview();
    const cards = screen.getAllByRole('article');
    fireEvent.click(within(cards[0]!).getByRole('button', { name: 'Keep & Continue' }));
    fireEvent.click(within(cards[1]!).getByRole('button', { name: 'Combine with Previous' }));
    for (let index = 2; index < cards.length - 1; index += 1) {
      fireEvent.click(within(cards[index]!).getByRole('button', { name: 'Keep & Continue' }));
    }
    fireEvent.click(within(cards[cards.length - 1]!).getByRole('button', { name: 'Not Instructional' }));
    const approve = screen.getByRole('button', { name: 'Approve Tutorial' });
    expect(approve.hasAttribute('disabled')).toBe(false);
    fireEvent.click(approve);
    expect(await screen.findByRole('heading', { name: 'Tutorial review approved.' })).toBeTruthy();
    expect(screen.getByText(/No prompts or images were generated here/i)).toBeTruthy();
  });
});
