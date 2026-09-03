import { fireEvent, render, screen, within } from '@testing-library/react';
import tutorialRecording from './fixtures/tutorial0-recording.json';
import { tutorial0SyntheticCapture } from './fixtures/tutorial0-capture';
import { tutorial0RoutedTutorialNeed } from './fixtures/tutorial0-prompts';
import { App, type TutorialRuntimeInput } from './App';

const readyContext = {
  fixtureId: 'tutorial0-privacy-safe-v1',
  requiredTests: ['typecheck', 'lint', 'unit/component tests', 'build', 'guard', 'Playwright', 'repository structural validation'],
  nonGoals: ['no live GitHub mutation', 'no image-provider execution', 'no live Adobe/browser replay', 'no Notion/Drive/classroom write'],
  definitionOfDone: ['all deterministic preflight rows pass', 'handoff packet is generated locally', 'execution_authorized remains false'],
  unresolvedArchitectureDecision: false,
} as const;

const runtimeInput: TutorialRuntimeInput = {
  route: tutorial0RoutedTutorialNeed,
  captureBundle: tutorial0SyntheticCapture,
  readyContext,
};

function renderCoach(withRoute = true) {
  render(<App resolveTutorialInput={withRoute ? () => runtimeInput : undefined} />);
}

async function reachReview(withRoute = true) {
  renderCoach(withRoute);
  fireEvent.click(screen.getByRole('button', { name: 'Continue to Upload' }));
  fireEvent.change(screen.getByLabelText('Choose Recorder JSON'), { target: { files: [new File([JSON.stringify(tutorialRecording)], 'recording.json')] } });
  await screen.findByRole('heading', { name: 'Recording loaded' });
  fireEvent.click(screen.getByRole('button', { name: 'Continue to Review' }));
  fireEvent.click(screen.getByRole('button', { name: 'Start Review' }));
}

async function approveTutorial(withRoute = true) {
  await reachReview(withRoute);
  const cards = screen.getAllByRole('article');
  fireEvent.click(within(cards[0]!).getByRole('button', { name: 'Keep & Continue' }));
  fireEvent.click(within(cards[1]!).getByRole('button', { name: 'Combine with Previous' }));
  for (let index = 2; index < cards.length - 1; index += 1) fireEvent.click(within(cards[index]!).getByRole('button', { name: 'Keep & Continue' }));
  fireEvent.click(within(cards[cards.length - 1]!).getByRole('button', { name: 'Not Instructional' }));
  fireEvent.click(screen.getByRole('button', { name: 'Approve Tutorial' }));
}

async function reachPrompts() {
  await approveTutorial();
  fireEvent.click(await screen.findByRole('button', { name: 'Generate Prompts' }));
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

  it('fails closed when no upstream tutorial/process route is supplied', async () => {
    await approveTutorial(false);
    fireEvent.click(screen.getByRole('button', { name: 'Generate Prompts' }));
    expect(await screen.findByText(/blocked until an upstream tutorial\/process route is supplied/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Picture Perfect prompts' })).toBeNull();
  });

  it('reaches Prompts through the generic routed Tutorial Package with approved synthetic screen evidence', async () => {
    await reachPrompts();
    expect(screen.getAllByText('Application: Adobe Express').length).toBe(3);
    expect(screen.getByText('Prompts').closest('li')?.getAttribute('aria-current')).toBe('step');
    expect(screen.getAllByText('Software interface — approved screen capture bound').length).toBe(3);
    expect(screen.getAllByLabelText('Portable prompt').length).toBe(3);
    expect(screen.getAllByRole('button', { name: 'Copy Prompt' }).length).toBe(3);
    expect(screen.queryByRole('button', { name: /generate image|submit prompt|run provider/i })).toBeNull();
    expect(screen.queryByText('Prompt blocked')).toBeNull();
    expect(screen.getAllByText(/Approved captured screen evidence is the base visual/i).length).toBe(3);
    expect(screen.getByText(/0 approved tutorial assets reused · 0 resurfaced/)).toBeTruthy();
  });

  it('passes Ready over the exact Stage-4 card set and produces only a local non-authorizing handoff packet', async () => {
    await reachPrompts();
    fireEvent.click(screen.getByRole('button', { name: 'Open Ready' }));
    expect(await screen.findByRole('heading', { name: 'Implementation handoff preflight' })).toBeTruthy();
    expect(screen.getByText('Ready').closest('li')?.getAttribute('aria-current')).toBe('step');
    expect(screen.getByText(/^Pass · Captured screen evidence bound where required$/)).toBeTruthy();

    const create = screen.getByRole('button', { name: 'Create GitHub Handoff' });
    expect(create.hasAttribute('disabled')).toBe(false);
    fireEvent.click(create);
    const packet = screen.getByLabelText('GitHub handoff packet') as HTMLTextAreaElement;
    expect(packet.value).toContain('"captured_screen_evidence"');
    expect(packet.value).toContain('"execution_authorized": false');
    expect(packet.value).toContain('curriculum-workflow-handoff://tutorial0/modeling');
    expect(screen.getByText(/No GitHub write occurred/i)).toBeTruthy();
  });
});
