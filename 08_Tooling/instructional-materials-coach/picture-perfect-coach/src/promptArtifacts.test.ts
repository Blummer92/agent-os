import { describe, expect, it } from 'vitest';
import { admitPromptArtifactSequence, canonicalPromptBodies, PROMPT_ARTIFACT_BLOCKER_REASONS } from './promptArtifacts';
import type { PromptCardModel } from './promptIntent';
import type { ReviewedTutorialProjection } from './types';

function tutorial(sequences: readonly number[]): ReviewedTutorialProjection {
  return {
    recording_id: 'tutorial-1',
    recording_sha256: 'a'.repeat(64),
    retained_steps: sequences.map((sequence) => ({
      review_step_id: `step-${sequence}`,
      sequence,
      source_step_ids: [`source-${sequence}`],
      semantic_action_ids: [`action-${sequence}`],
      source_indexes: [sequence],
      recording_id: 'tutorial-1',
      recording_sha256: 'a'.repeat(64),
      modeled_application: 'Adobe Express',
    })),
    excluded_step_ids: [],
    review_decisions: [],
    recording_evidence: { recordingSha256: 'a'.repeat(64), actionIdentity: [], stateLocalClaims: [], recordingClaimTexts: [] },
    execution_authorized: false,
  };
}

function card(stepNumber: number, purpose: string): PromptCardModel {
  return {
    stepNumber,
    imagePurpose: purpose,
    imageState: 'result',
    application: 'Adobe Express',
    applicationContext: '',
    targetState: purpose,
    mustShow: [purpose],
    mustNotShow: [],
    annotationSpace: 'none',
    provenance: [`recording:tutorial-1`, `source_step:source-${stepNumber}`],
    requestedUiDetails: [],
    requiresScreenFidelity: false,
    evidence: { sourceIndexes: [], actionIdentity: [], stateLocalClaims: [], recordingClaimTexts: [] },
    portablePrompt: `Create the approved instructional visual. Purpose: ${purpose}`,
    status: 'ready',
    blockerReasons: [],
  };
}

const tutorial1Cards = [
  card(1, 'Start with the bun construction'),
  card(2, 'Show the next taught construction state'),
  card(3, 'Show the cheese operation'),
  card(4, 'Show the lettuce manual-linework state'),
  card(5, 'Show the final result and verification state'),
] as const;

describe('Stage 4 prompt artifact sequence', () => {
  it('admits exactly five Tutorial 1 artifacts in evidence order with the bun first', () => {
    const result = admitPromptArtifactSequence(tutorial([1, 2, 3, 4, 5]), tutorial1Cards);
    expect(result.status).toBe('ready');
    expect(result.cards).toHaveLength(5);
    expect(result.cards[0]?.imagePurpose).toContain('bun');
    expect(result.cards.map((item) => item.stepNumber)).toEqual([1, 2, 3, 4, 5]);
    expect(canonicalPromptBodies(result)).toEqual(tutorial1Cards.map((item) => item.portablePrompt));
  });

  it('does not prepend an inferred workspace/setup artifact', () => {
    const withInventedSetup = [card(0, 'Generic workspace setup'), ...tutorial1Cards];
    const result = admitPromptArtifactSequence(tutorial([1, 2, 3, 4, 5]), withInventedSetup);
    expect(result.status).toBe('blocked');
    expect(result.blockerReasons).toContain(PROMPT_ARTIFACT_BLOCKER_REASONS.sequenceMismatch);
  });

  it('blocks missing authoring instead of silently shortening the artifact sequence', () => {
    const result = admitPromptArtifactSequence(tutorial([1, 2, 3, 4, 5]), tutorial1Cards.slice(0, 4));
    expect(result.status).toBe('blocked');
    expect(result.blockerReasons).toContain(PROMPT_ARTIFACT_BLOCKER_REASONS.missingAuthoring);
    expect(canonicalPromptBodies(result)).toEqual([]);
  });

  it('blocks reordered and duplicate image numbers instead of sorting or guessing', () => {
    const reordered = [tutorial1Cards[1], tutorial1Cards[0], ...tutorial1Cards.slice(2)];
    expect(admitPromptArtifactSequence(tutorial([1, 2, 3, 4, 5]), reordered).blockerReasons)
      .toContain(PROMPT_ARTIFACT_BLOCKER_REASONS.sequenceMismatch);

    const duplicate = [tutorial1Cards[0], tutorial1Cards[0], ...tutorial1Cards.slice(2)];
    expect(admitPromptArtifactSequence(tutorial([1, 2, 3, 4, 5]), duplicate).blockerReasons)
      .toContain(PROMPT_ARTIFACT_BLOCKER_REASONS.duplicateSequence);
  });
});
