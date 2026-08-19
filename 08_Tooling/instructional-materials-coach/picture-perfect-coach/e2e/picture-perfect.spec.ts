import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

const tutorialRecording = JSON.parse(
  readFileSync(fileURLToPath(new URL('../src/fixtures/tutorial0-recording.json', import.meta.url)), 'utf8'),
) as { title: string; steps: Array<Record<string, unknown> & { type: string; url?: string }> };

async function openUpload(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Teach the software like you normally would.' })).toBeVisible();
  await page.getByRole('button', { name: 'Continue to Upload' }).click();
  await expect(page.getByRole('heading', { name: 'Upload your Recorder JSON.' })).toBeVisible();
}

async function uploadJson(page: Page, value: unknown, filename = 'recording.json') {
  await page.getByLabel('Choose Recorder JSON').setInputFiles({
    name: filename,
    mimeType: 'application/json',
    buffer: Buffer.from(typeof value === 'string' ? value : JSON.stringify(value)),
  });
}

async function reachReview(page: Page) {
  await openUpload(page);
  await uploadJson(page, tutorialRecording);
  await expect(page.getByRole('heading', { name: 'Recording loaded' })).toBeVisible();
  await page.getByRole('button', { name: 'Continue to Review' }).click();
  await page.getByRole('button', { name: 'Start Review' }).click();
  await expect(page.getByRole('heading', { name: 'Review the instructional steps.' })).toBeVisible();
}

async function approveTutorial(page: Page) {
  const cards = page.locator('article.review-card');
  const count = await cards.count();
  expect(count).toBeGreaterThan(2);
  await cards.nth(0).getByRole('button', { name: 'Keep & Continue' }).click();
  await cards.nth(1).getByRole('button', { name: 'Combine with Previous' }).click();
  for (let index = 2; index < count - 1; index += 1) {
    await cards.nth(index).getByRole('button', { name: 'Keep & Continue' }).click();
  }
  await cards.nth(count - 1).getByRole('button', { name: 'Not Instructional' }).click();
  await expect(page.getByRole('button', { name: 'Approve Tutorial' })).toBeEnabled();
  await page.getByRole('button', { name: 'Approve Tutorial' }).click();
  await expect(page.getByRole('heading', { name: 'Picture Perfect prompts' })).toBeVisible();
}

function currentStage(page: Page, label: string) {
  return page.getByRole('navigation', { name: 'Picture Perfect stages' }).locator('li[aria-current="step"]').filter({ hasText: label });
}

test('Tutorial 0 completes Model -> Upload -> Review -> Prompts -> Ready -> local handoff', async ({ page }) => {
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.hostname !== '127.0.0.1') externalRequests.push(request.url());
  });

  await reachReview(page);
  await expect(page.getByText(/steps look clear/i)).toBeVisible();
  await expect(page.getByText(/things need your attention/i)).toBeVisible();
  await approveTutorial(page);

  await expect(currentStage(page, 'Prompts')).toHaveCount(1);
  const promptCards = page.locator('article.prompt-card');
  expect(await promptCards.count()).toBeGreaterThan(0);
  await expect(promptCards.first().getByText('Application: Adobe Express')).toBeVisible();
  await expect(promptCards.first().getByLabel('Portable prompt')).toContainText('Adobe Express');
  await expect(page.getByText('These prompts are derived presentation guidance. They never become instructional source evidence.')).toBeVisible();

  await page.getByRole('button', { name: 'Open Ready' }).click();
  await expect(page.getByRole('heading', { name: 'Implementation handoff preflight' })).toBeVisible();
  await expect(currentStage(page, 'Ready')).toHaveCount(1);
  expect(await page.getByText(/^Pass ·/).count()).toBeGreaterThan(5);

  const createHandoff = page.getByRole('button', { name: 'Create GitHub Handoff' });
  await expect(createHandoff).toBeEnabled();
  await createHandoff.click();
  const packet = page.getByLabel('GitHub handoff packet');
  await expect(packet).toContainText('"execution_authorized": false');
  await expect(packet).toContainText('"presentation_evidence_only": true');
  await expect(packet).toContainText('"modeled_application": "Adobe Express"');
  await expect(packet).toContainText('tutorial0-step-08-incidental-shift');
  await expect(page.getByText(/No GitHub write occurred/i)).toBeVisible();
  expect(externalRequests).toEqual([]);
});

test('malformed Recorder JSON fails closed with one bounded recovery action', async ({ page }) => {
  await openUpload(page);
  await uploadJson(page, '{ definitely not json');
  await expect(page.getByRole('heading', { name: 'Picture Perfect stopped safely.' })).toBeVisible();
  await expect(page.getByText(/not valid Recorder JSON/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose another file' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continue to Review' })).toHaveCount(0);
});

test('off-approved-origin Recorder navigation is surfaced and cannot become instructional evidence', async ({ page }) => {
  const unsafe = structuredClone(tutorialRecording);
  const navigate = unsafe.steps.find((step) => step.type === 'navigate');
  if (!navigate) throw new Error('fixture navigate step missing');
  navigate.url = 'https://example.invalid/not-approved';
  await openUpload(page);
  await uploadJson(page, unsafe, 'off-origin.json');
  await expect(page.getByRole('heading', { name: 'Picture Perfect stopped safely.' })).toBeVisible();
  await expect(page.getByText(/outside the approved Adobe Express modeling origin/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continue to Review' })).toHaveCount(0);
});

test('Recorder without approved Teacher Modeling source evidence cannot reach Ready', async ({ page }) => {
  const unmatched = structuredClone(tutorialRecording);
  unmatched.title = 'Synthetic recording without modeling projection';
  await openUpload(page);
  await uploadJson(page, unmatched, 'missing-modeling-source.json');
  await expect(page.getByText(/no Teacher Modeling evidence for it yet/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Continue to Review' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Create GitHub Handoff' })).toHaveCount(0);
});

test('source identity/fingerprint mismatch cannot reach the approved prompt or Ready path', async ({ page }) => {
  const mismatched = structuredClone(tutorialRecording);
  mismatched.steps[mismatched.steps.length - 1] = { type: 'keyDown', key: 'Control' };
  await openUpload(page);
  await uploadJson(page, mismatched, 'source-mismatch.json');
  await expect(page.getByText(/no Teacher Modeling evidence for it yet/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Picture Perfect prompts' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Create GitHub Handoff' })).toHaveCount(0);
});

test('unresolved Review keeps approval and downstream handoff disabled', async ({ page }) => {
  await reachReview(page);
  await expect(page.getByRole('button', { name: 'Approve Tutorial' })).toBeDisabled();
  await expect(page.getByText(/Every modeled step needs an explicit review decision/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open Ready' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Create GitHub Handoff' })).toHaveCount(0);
});

test('provider-neutral prompt UI preserves application identity and exposes no meaning-changing provider control', async ({ page }) => {
  await reachReview(page);
  await approveTutorial(page);
  const promptCards = page.locator('article.prompt-card');
  await expect(promptCards.first().getByText('Application: Adobe Express')).toBeVisible();
  await expect(promptCards.first().getByLabel('Portable prompt')).not.toContainText(/--ar|midjourney|firefly parameter/i);
  await expect(page.getByRole('combobox')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /provider/i })).toHaveCount(0);
});

test('prompt/image presentation evidence never grants execution authority', async ({ page }) => {
  await reachReview(page);
  await approveTutorial(page);
  await expect(page.getByText('These prompts are derived presentation guidance. They never become instructional source evidence.')).toBeVisible();
  await page.getByRole('button', { name: 'Open Ready' }).click();
  await page.getByRole('button', { name: 'Create GitHub Handoff' }).click();
  await expect(page.getByLabel('GitHub handoff packet')).toContainText('"execution_authorized": false');
  await expect(page.getByRole('button', { name: /start implementation/i })).toHaveCount(0);
});