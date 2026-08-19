import tutorialEvidence from './fixtures/tutorial0-evidence.json';
import { deriveReviewedTutorial, needsAttention } from './review';
import type { ReviewDecision, UploadEvidenceProjection } from './types';

const evidence = tutorialEvidence as unknown as UploadEvidenceProjection;
const keepAll: ReviewDecision[] = evidence.modeling_steps.map((step) => ({ step_id: step.step_id, choice: 'keep' }));

describe('Picture Perfect review derivation', () => {
  it('requires explicit decisions and never treats upstream disposition or RJ evidence as approval', () => {
    expect(deriveReviewedTutorial(evidence, [])).toEqual({ ok: false, reason: 'Every modeled step needs an explicit review decision.' });
  });

  it('derives a deterministic authority-false retained projection', () => {
    const first = deriveReviewedTutorial(evidence, keepAll);
    const second = deriveReviewedTutorial(evidence, keepAll);
    expect(first).toEqual(second);
    expect(first.ok).toBe(true);
    if (first.ok) {
      expect(first.tutorial.execution_authorized).toBe(false);
      expect(first.tutorial.retained_steps.every((step) => step.execution_authorized === false)).toBe(true);
    }
  });

  it('combines only with the previous retained step and preserves both provenance chains', () => {
    const decisions = keepAll.map((decision, index) => index === 1 ? { ...decision, choice: 'combine-with-previous' as const } : decision);
    const result = deriveReviewedTutorial(evidence, decisions);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.tutorial.retained_steps[0]?.source_step_ids).toEqual([
        evidence.modeling_steps[0]?.step_id,
        evidence.modeling_steps[1]?.step_id,
      ]);
      expect(result.tutorial.retained_steps[0]?.semantic_action_ids).toEqual([
        ...evidence.modeling_steps[0]!.semantic_action_ids,
        ...evidence.modeling_steps[1]!.semantic_action_ids,
      ]);
    }
  });

  it('fails closed when the first retained step tries to combine', () => {
    const decisions = keepAll.map((decision, index) => index === 0 ? { ...decision, choice: 'combine-with-previous' as const } : decision);
    expect(deriveReviewedTutorial(evidence, decisions)).toEqual({ ok: false, reason: 'The first retained step cannot combine with a previous step.' });
  });

  it('keeps Not Instructional in review evidence while excluding it downstream', () => {
    const lastId = evidence.modeling_steps.at(-1)!.step_id;
    const decisions = keepAll.map((decision) => decision.step_id === lastId ? { ...decision, choice: 'not-instructional' as const } : decision);
    const result = deriveReviewedTutorial(evidence, decisions);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.tutorial.excluded_step_ids).toContain(lastId);
      expect(result.tutorial.review_decisions).toContainEqual({ step_id: lastId, choice: 'not-instructional' });
      expect(result.tutorial.retained_steps.flatMap((step) => step.source_step_ids)).not.toContain(lastId);
    }
  });

  it('surfaces supplied attention evidence without converting it into a teacher decision', () => {
    expect(evidence.modeling_steps.some((step) => needsAttention(step))).toBe(true);
    expect(deriveReviewedTutorial(evidence, [])).toMatchObject({ ok: false });
  });

  it('carries modeled_application forward from approved evidence into the reviewed step', () => {
    const result = deriveReviewedTutorial(evidence, keepAll);
    expect(result.ok).toBe(true);
    if (result.ok) {
      for (const step of result.tutorial.retained_steps) {
        if (step.source_step_ids.includes('tutorial0-step-08-incidental-shift')) continue;
        expect(step.modeled_application).toBe('Adobe Express');
      }
    }
  });

  it('blocks combine when contributing steps report contradictory modeled application identity', () => {
    const mismatched = structuredClone(evidence);
    mismatched.modeling_steps[1]!.source.modeled_application = 'Canva';
    const decisions = keepAll.map((decision, index) => index === 1 ? { ...decision, choice: 'combine-with-previous' as const } : decision);
    expect(deriveReviewedTutorial(mismatched, decisions)).toEqual({
      ok: false,
      reason: 'Combined steps report contradictory modeled application identity.',
    });
  });

  it('fails closed on duplicate identity and contradictory recording provenance', () => {
    const duplicate = structuredClone(evidence);
    duplicate.modeling_steps[1]!.step_id = duplicate.modeling_steps[0]!.step_id;
    expect(deriveReviewedTutorial(duplicate, keepAll)).toMatchObject({ ok: false });

    const mixed = structuredClone(evidence);
    mixed.modeling_steps[0]!.source.recording_id = 'other-recording';
    expect(deriveReviewedTutorial(mixed, keepAll)).toEqual({ ok: false, reason: 'Modeled steps contain contradictory recording identity.' });
  });
});
