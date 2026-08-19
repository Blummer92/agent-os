import { describe, expect, it } from 'vitest';
import { tutorial0PromptCards, tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import { createGitHubHandoffPacket, runReadyPreflight, type ReadyContext } from './preflight';

const context: ReadyContext = {
  fixtureId: 'tutorial0-privacy-safe-v1',
  requiredTests: ['typecheck', 'lint', 'unit/component tests', 'build', 'guard', 'repository structural validation'],
  nonGoals: ['no live GitHub mutation', 'no image-provider execution', 'no Adobe/browser execution', 'no Notion/Drive/classroom write'],
  definitionOfDone: ['all deterministic preflight rows pass', 'handoff packet is generated locally', 'execution_authorized remains false'],
  unresolvedArchitectureDecision: false,
};

describe('Picture Perfect Ready preflight', () => {
  it('passes Tutorial 0 deterministically and preserves source/application evidence in the packet', () => {
    const result = runReadyPreflight(tutorial0ReviewedTutorial, tutorial0PromptCards, context);
    expect(result.ready).toBe(true);
    expect(result.rows.every((row) => row.state === 'pass')).toBe(true);

    const packet = createGitHubHandoffPacket(tutorial0ReviewedTutorial, tutorial0PromptCards, context);
    expect(packet).not.toBeNull();
    expect(packet?.recording_id).toBe(tutorial0ReviewedTutorial.recording_id);
    expect(packet?.recording_sha256).toBe(tutorial0ReviewedTutorial.recording_sha256);
    expect(packet?.retained_steps.every((step) => step.modeled_application === 'Adobe Express')).toBe(true);
    expect(packet?.excluded_step_ids).toContain('tutorial0-step-08-incidental-shift');
    expect(packet?.prompt_requirements.every((prompt) => prompt.application === 'Adobe Express')).toBe(true);
    expect(packet?.modeling_source_refs).toContain('Teacher Modeling: Tutorial 0');
    expect(packet?.presentation_evidence_only).toBe(true);
    expect(packet?.execution_authorized).toBe(false);
  });

  it('preserves combined-step provenance in the handoff packet', () => {
    const packet = createGitHubHandoffPacket(tutorial0ReviewedTutorial, tutorial0PromptCards, context);
    const combined = packet?.retained_steps.find((step) => step.source_step_ids.length > 1);
    expect(combined?.source_step_ids).toEqual([
      'tutorial0-step-01-organize-location',
      'tutorial0-step-02-open-tutorial-location',
    ]);
    expect((combined?.semantic_action_ids.length ?? 0) > 1).toBe(true);
    expect((combined?.source_indexes.length ?? 0) > 1).toBe(true);
  });

  it('fails closed when application identity is missing', () => {
    const broken = structuredClone(tutorial0ReviewedTutorial);
    broken.retained_steps[0]!.modeled_application = null;
    const result = runReadyPreflight(broken, tutorial0PromptCards, context);
    expect(result.ready).toBe(false);
    expect(result.rows.find((row) => row.id === 'application')?.state).toBe('fail');
    expect(createGitHubHandoffPacket(broken, tutorial0PromptCards, context)).toBeNull();
  });

  it('fails closed on blocked prompt cards, source mismatch, unresolved architecture, or missing completion evidence', () => {
    const blockedCards = tutorial0PromptCards.map((card, index) => index === 0 ? { ...card, status: 'blocked' as const, blocker: 'test blocker' } : card);
    expect(runReadyPreflight(tutorial0ReviewedTutorial, blockedCards, context).ready).toBe(false);

    const mismatched = structuredClone(tutorial0ReviewedTutorial);
    mismatched.retained_steps[0]!.recording_sha256 = 'different';
    expect(runReadyPreflight(mismatched, tutorial0PromptCards, context).ready).toBe(false);

    expect(runReadyPreflight(tutorial0ReviewedTutorial, tutorial0PromptCards, { ...context, unresolvedArchitectureDecision: true }).ready).toBe(false);
    expect(runReadyPreflight(tutorial0ReviewedTutorial, tutorial0PromptCards, { ...context, requiredTests: [] }).ready).toBe(false);
    expect(runReadyPreflight(tutorial0ReviewedTutorial, tutorial0PromptCards, { ...context, definitionOfDone: [] }).ready).toBe(false);
  });
});
