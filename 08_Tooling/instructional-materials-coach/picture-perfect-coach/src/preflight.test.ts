import { describe, expect, it } from 'vitest';
import { tutorial0PromptCards, tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import { createGitHubHandoffPacket, runReadyPreflight, type ReadyContext } from './preflight';
import { projectReviewedTutorialToPromptCards, type PromptAuthoringInput, type PromptCardModel } from './promptIntent';

/**
 * Tutorial 0's own frames all claim the real interface and therefore block. These
 * non-interface frames keep the Ready/packet path itself under test: they request no
 * interface text and declare no application context, so they are legitimately ready.
 */
const nonInterfaceAuthoring: PromptAuthoringInput = {
  imagePurpose: 'Show the idea of grouping work by purpose.',
  imageState: 'result',
  applicationContext: '',
  targetState: 'related work is grouped together',
  mustShow: ['three labelled groups'],
  mustNotShow: ['student data'],
  annotationSpace: 'beside the groups',
  requestedUiDetails: [],
};

const readyCards: readonly PromptCardModel[] = projectReviewedTutorialToPromptCards(
  tutorial0ReviewedTutorial,
  new Map(tutorial0ReviewedTutorial.retained_steps.map((step) => [step.review_step_id, nonInterfaceAuthoring])),
).map((card) => ({ ...card, provenance: ['Teacher Modeling: Tutorial 0', ...card.provenance] }));

const context: ReadyContext = {
  fixtureId: 'tutorial0-privacy-safe-v1',
  requiredTests: ['typecheck', 'lint', 'unit/component tests', 'build', 'guard', 'repository structural validation'],
  nonGoals: ['no live GitHub mutation', 'no image-provider execution', 'no Adobe/browser execution', 'no Notion/Drive/classroom write'],
  definitionOfDone: ['all deterministic preflight rows pass', 'handoff packet is generated locally', 'execution_authorized remains false'],
  unresolvedArchitectureDecision: false,
};

describe('Picture Perfect Ready preflight', () => {
  it('fails Tutorial 0 closed because its software-interface frames have no screen evidence', () => {
    const result = runReadyPreflight(tutorial0ReviewedTutorial, tutorial0PromptCards, context);
    expect(result.ready).toBe(false);
    expect(result.rows.find((row) => row.id === 'visual-evidence')?.state).toBe('fail');
    expect(result.rows.find((row) => row.id === 'prompt-contract')?.state).toBe('fail');
    expect(createGitHubHandoffPacket(tutorial0ReviewedTutorial, tutorial0PromptCards, context)).toBeNull();
  });

  it('marks the visual-evidence row not-applicable when no frame claims the interface', () => {
    const result = runReadyPreflight(tutorial0ReviewedTutorial, readyCards, context);
    expect(result.rows.find((row) => row.id === 'visual-evidence')?.state).toBe('not-applicable');
  });

  it('passes deterministically and preserves source/application evidence in the packet', () => {
    const result = runReadyPreflight(tutorial0ReviewedTutorial, readyCards, context);
    expect(result.ready).toBe(true);
    expect(result.rows.every((row) => row.state === 'pass' || row.state === 'not-applicable')).toBe(true);

    const packet = createGitHubHandoffPacket(tutorial0ReviewedTutorial, readyCards, context);
    expect(packet).not.toBeNull();
    expect(packet?.prompt_requirements.every((prompt) => prompt.requires_screen_fidelity === false)).toBe(true);
    expect(packet?.prompt_requirements.every((prompt) => prompt.captured_screen_ref === null)).toBe(true);
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
    const packet = createGitHubHandoffPacket(tutorial0ReviewedTutorial, readyCards, context);
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
    const result = runReadyPreflight(broken, readyCards, context);
    expect(result.ready).toBe(false);
    expect(result.rows.find((row) => row.id === 'application')?.state).toBe('fail');
    expect(createGitHubHandoffPacket(broken, readyCards, context)).toBeNull();
  });

  it('fails closed when a frame claims the interface without capture evidence', () => {
    const interfaceCard = { ...readyCards[0]!, requiresScreenFidelity: true };
    const result = runReadyPreflight(tutorial0ReviewedTutorial, [interfaceCard, ...readyCards.slice(1)], context);
    expect(result.ready).toBe(false);
    expect(result.rows.find((row) => row.id === 'visual-evidence')?.state).toBe('fail');
  });

  it('fails closed on blocked prompt cards, source mismatch, unresolved architecture, or missing completion evidence', () => {
    const blockedCards = readyCards.map((card, index) => index === 0 ? { ...card, status: 'blocked' as const, blocker: 'test blocker' } : card);
    expect(runReadyPreflight(tutorial0ReviewedTutorial, blockedCards, context).ready).toBe(false);

    const mismatched = structuredClone(tutorial0ReviewedTutorial);
    mismatched.retained_steps[0]!.recording_sha256 = 'different';
    expect(runReadyPreflight(mismatched, readyCards, context).ready).toBe(false);

    expect(runReadyPreflight(tutorial0ReviewedTutorial, readyCards, { ...context, unresolvedArchitectureDecision: true }).ready).toBe(false);
    expect(runReadyPreflight(tutorial0ReviewedTutorial, readyCards, { ...context, requiredTests: [] }).ready).toBe(false);
    expect(runReadyPreflight(tutorial0ReviewedTutorial, readyCards, { ...context, definitionOfDone: [] }).ready).toBe(false);
  });
});
