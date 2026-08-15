import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import tutorialRecording from './fixtures/tutorial0-recording.json';
import tutorialEvidence from './fixtures/tutorial0-evidence.json';
import { App } from './App';
import { summarizeEvidence } from './evidence';
import type { UploadEvidenceProjection } from './types';

describe('Picture Perfect Coach shell and upload', () => {
  it('renders Model first with all five stages visible and later stages disabled', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: /Teach the software like you normally would/i })).toBeTruthy();
    for (const stage of ['Model', 'Upload', 'Review', 'Prompts', 'Ready']) {
      expect(screen.getByText(stage)).toBeTruthy();
    }
    const reviewStage = screen.getByText('Review').closest('li');
    expect(reviewStage?.getAttribute('aria-disabled')).toBe('true');
  });

  it('moves legally from Model to Upload and supports accessible file selection', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Upload' }));
    expect(screen.getByRole('heading', { name: 'Upload your Recorder JSON.' })).toBeTruthy();
    expect(screen.getByLabelText('Choose Recorder JSON')).toBeTruthy();
  });

  it('fails closed on malformed JSON with one bounded retry action', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Upload' }));
    const input = screen.getByLabelText('Choose Recorder JSON');
    fireEvent.change(input, { target: { files: [new File(['{not-json'], 'bad.json', { type: 'application/json' })] } });
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText(/not valid Recorder JSON/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Choose another file' })).toBeTruthy();
  });

  it('accepts only the bounded synthetic fixture and derives teacher-facing counts from evidence', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Upload' }));
    const input = screen.getByLabelText('Choose Recorder JSON');
    const file = new File([JSON.stringify(tutorialRecording)], 'recording.json', { type: 'application/json' });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByRole('heading', { name: 'Recording loaded' })).toBeTruthy();
    const expected = summarizeEvidence(tutorialEvidence as unknown as UploadEvidenceProjection);
    const summary = screen.getByLabelText('Recording summary');
    const cards = within(summary).getAllByRole('article');
    expect(cards[0]?.textContent).toContain(String(expected.actionsFound));
    expect(cards[1]?.textContent).toContain(String(expected.instructionalCandidates));
    expect(cards[2]?.textContent).toContain(String(expected.likelyNoiseRecovery));
    expect(cards[3]?.textContent).toContain(String(expected.needsReview));
  });

  it('keeps technical evidence collapsed, sanitized, and explicit about pending RJ3/RJ4 state', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Upload' }));
    const input = screen.getByLabelText('Choose Recorder JSON');
    fireEvent.change(input, { target: { files: [new File([JSON.stringify(tutorialRecording)], 'recording.json')] } });
    await screen.findByRole('heading', { name: 'Recording loaded' });

    const details = screen.getByText('View technical details').closest('details');
    expect(details?.hasAttribute('open')).toBe(false);
    expect(screen.queryByText(/new\.express\.adobe\.test/i)).toBeNull();
    expect(screen.queryByText(/data-testid/i)).toBeNull();

    fireEvent.click(screen.getByText('View technical details'));
    const pendingLabels = screen.getAllByText('Pending — not proven');
    expect(pendingLabels.length).toBe(2);
    expect(screen.queryByText('Passed evidence supplied')).toBeNull();
  });

  it('stops unknown Recorder input instead of inventing instructional evidence', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Upload' }));
    const input = screen.getByLabelText('Choose Recorder JSON');
    const unknown = { title: 'Unknown synthetic recording', steps: [{ type: 'click' }] };
    fireEvent.change(input, { target: { files: [new File([JSON.stringify(unknown)], 'unknown.json')] } });
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText(/No instructional counts were guessed/i)).toBeTruthy();
  });

  it('reaches only the Review boundary and exposes no review decision controls', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Upload' }));
    fireEvent.change(screen.getByLabelText('Choose Recorder JSON'), {
      target: { files: [new File([JSON.stringify(tutorialRecording)], 'recording.json')] },
    });
    await screen.findByRole('heading', { name: 'Recording loaded' });
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Review boundary' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Ready for the Review slice.' })).toBeTruthy());
    expect(screen.queryByRole('button', { name: /Keep/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Combine/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Not Instructional/i })).toBeNull();
  });
});
