import type { PromptCardModel } from './promptIntent';

export const PROMPT_ARTIFACT_BLOCKER_REASONS = {
  missingAuthoring: 'prompt-artifact-missing-authoring',
  sequenceMismatch: 'prompt-artifact-sequence-mismatch',
  duplicateSequence: 'prompt-artifact-duplicate-sequence',
} as const;

export type PromptArtifactBlockerReason =
  (typeof PROMPT_ARTIFACT_BLOCKER_REASONS)[keyof typeof PROMPT_ARTIFACT_BLOCKER_REASONS];

export type PromptArtifactTutorialSequence = Readonly<{
  retained_steps: readonly Readonly<{ sequence: number }>[];
}>;

export type PromptArtifactSequence = Readonly<{
  status: 'ready' | 'blocked';
  cards: readonly PromptCardModel[];
  expectedStepNumbers: readonly number[];
  blockerReasons: readonly PromptArtifactBlockerReason[];
}>;

/**
 * Admit Stage 4 prompt artifacts only when they preserve the reviewed tutorial's
 * exact retained-step sequence. This boundary intentionally consumes only the
 * sequence field it owns instead of coupling sequence validation to the full
 * reviewed-tutorial evidence schema. It never invents an orientation/setup frame
 * and never sorts cards to make a bad projection look valid.
 */
export function admitPromptArtifactSequence(
  tutorial: PromptArtifactTutorialSequence,
  cards: readonly PromptCardModel[],
): PromptArtifactSequence {
  const expectedStepNumbers = tutorial.retained_steps.map((step) => step.sequence);
  const actualStepNumbers = cards.map((card) => card.stepNumber);
  const reasons: PromptArtifactBlockerReason[] = [];

  if (new Set(actualStepNumbers).size !== actualStepNumbers.length) {
    reasons.push(PROMPT_ARTIFACT_BLOCKER_REASONS.duplicateSequence);
  }
  if (cards.length !== tutorial.retained_steps.length) {
    reasons.push(PROMPT_ARTIFACT_BLOCKER_REASONS.missingAuthoring);
  }
  if (
    actualStepNumbers.length !== expectedStepNumbers.length ||
    actualStepNumbers.some((stepNumber, index) => stepNumber !== expectedStepNumbers[index])
  ) {
    reasons.push(PROMPT_ARTIFACT_BLOCKER_REASONS.sequenceMismatch);
  }

  return Object.freeze({
    status: reasons.length === 0 ? 'ready' : 'blocked',
    cards: Object.freeze([...cards]),
    expectedStepNumbers: Object.freeze(expectedStepNumbers),
    blockerReasons: Object.freeze([...new Set(reasons)]),
  });
}

export function canonicalPromptBodies(sequence: PromptArtifactSequence): readonly string[] {
  if (sequence.status !== 'ready') return Object.freeze([]);
  return Object.freeze(sequence.cards.map((card) => card.portablePrompt));
}
