import { describe, expect, it } from 'vitest';
import { tutorial0SyntheticCapture } from './fixtures/tutorial0-capture';
import {
  tutorial0ReviewedTutorial,
  tutorial0RoutedTutorialNeed,
} from './fixtures/tutorial0-prompts';
import {
  PROMPT_PROJECTION_INPUT_VERSION,
  projectTutorialPromptCards,
  serializePromptProjectionResult,
  type PromptProjectionInput,
} from './promptProjectionEntrypoint';
import { buildTutorialPackage, type RoutedTutorialNeed } from './tutorialPackage';

function tutorial0Input(route: RoutedTutorialNeed = tutorial0RoutedTutorialNeed): PromptProjectionInput {
  return {
    formatVersion: PROMPT_PROJECTION_INPUT_VERSION,
    tutorial: tutorial0ReviewedTutorial,
    route,
  };
}

describe('prompt projection entrypoint', () => {
  it('projects Tutorial 0 outside the UI through the canonical tutorial-package owner', () => {
    const input = tutorial0Input();
    const result = projectTutorialPromptCards(input);
    const expected = buildTutorialPackage(tutorial0ReviewedTutorial, tutorial0RoutedTutorialNeed);

    expect(result.status).toBe('valid');
    expect(result.tutorialPackage).toEqual(expected.package);
    expect(result.routeId).toBe(tutorial0RoutedTutorialNeed.routeId);
    expect(result.sourceHandoffRef).toBe(tutorial0RoutedTutorialNeed.sourceHandoffRef);
    expect(result.sourceFingerprint).toBe(tutorial0RoutedTutorialNeed.sourceFingerprint);
    expect(result.recordingId).toBe(tutorial0ReviewedTutorial.recording_id);
    expect(result.recordingSha256).toBe(tutorial0ReviewedTutorial.recording_sha256);
    expect(result.applications).toEqual(['Adobe Express']);
    expect(result.executionAuthorized).toBe(false);
    expect(result.externalWriteAuthorized).toBe(false);
    expect(result.productionAuthorized).toBe(false);
  });

  it('is deterministic and serializes the same structured result for the same resolved input', () => {
    const first = projectTutorialPromptCards(tutorial0Input());
    const second = projectTutorialPromptCards(tutorial0Input());

    expect(second).toEqual(first);
    expect(serializePromptProjectionResult(second)).toBe(serializePromptProjectionResult(first));
  });

  it('preserves ready and blocked prompt cards without rewriting either state', () => {
    let converted = false;
    const mixedRoute: RoutedTutorialNeed = {
      ...tutorial0RoutedTutorialNeed,
      steps: tutorial0RoutedTutorialNeed.steps.map((step) => {
        if (converted || step.disposition !== 'new-visual' || !step.authoring) return step;
        converted = true;
        return {
          ...step,
          authoring: {
            ...step.authoring,
            applicationContext: '',
            mustShow: ['conceptual folder grouping'],
            requestedUiDetails: [],
          },
        };
      }),
    };

    const expected = buildTutorialPackage(tutorial0ReviewedTutorial, mixedRoute);
    const result = projectTutorialPromptCards(tutorial0Input(mixedRoute));

    expect(result.tutorialPackage).toEqual(expected.package);
    expect(result.tutorialPackage?.cards.some((card) => card.status === 'ready')).toBe(true);
    expect(result.tutorialPackage?.cards.some((card) => card.status === 'blocked')).toBe(true);
    for (const card of result.tutorialPackage?.cards ?? []) {
      if (card.status === 'blocked') expect(card.portablePrompt).toBe('');
    }
  });

  it('preserves capture identity mismatch as a canonical blocked-card reason', () => {
    const mismatchedCapture = {
      ...tutorial0SyntheticCapture,
      capture: tutorial0SyntheticCapture.capture
        ? {
            ...tutorial0SyntheticCapture.capture,
            source: { recording_sha256: '0'.repeat(64) },
          }
        : null,
    };
    const result = projectTutorialPromptCards({
      ...tutorial0Input(),
      captureBundle: mismatchedCapture,
    });

    expect(result.status).toBe('valid');
    expect(
      result.tutorialPackage?.cards.some((card) => card.blockerReasons.includes('capture-recording-mismatch')),
    ).toBe(true);
  });

  it('fails closed on malformed or unsupported input without throwing', () => {
    expect(projectTutorialPromptCards(null)).toMatchObject({
      status: 'blocked',
      blockers: ['invalid-input'],
      tutorialPackage: null,
    });
    expect(projectTutorialPromptCards({
      ...tutorial0Input(),
      formatVersion: 'picture-perfect-prompt-projection-input-v999',
    })).toMatchObject({
      status: 'blocked',
      blockers: ['unsupported-input-version'],
      tutorialPackage: null,
    });
    expect(projectTutorialPromptCards({
      ...tutorial0Input(),
      unexpected: 'not-admitted',
    })).toMatchObject({
      status: 'blocked',
      blockers: ['invalid-input'],
      tutorialPackage: null,
    });
  });

  it('keeps source/application provenance provider-neutral and non-authorizing', () => {
    const result = projectTutorialPromptCards(tutorial0Input());

    expect(result.applications).toEqual(['Adobe Express']);
    expect(result.sourceHandoffRef).toBe('curriculum-workflow-handoff://tutorial0/modeling');
    expect(result.sourceFingerprint).toBe('tutorial0-handoff-fingerprint-v1');
    expect(result.executionAuthorized).toBe(false);
    expect(result.externalWriteAuthorized).toBe(false);
    expect(result.productionAuthorized).toBe(false);
    for (const card of result.tutorialPackage?.cards ?? []) {
      expect(card.application).toBe('Adobe Express');
      expect(card.portablePrompt).not.toMatch(/\b(?:Midjourney|Gemini|Firefly|Canva provider)\b/);
    }
  });
});
