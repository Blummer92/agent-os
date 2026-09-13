import { describe, expect, it, vi } from 'vitest';
import { tutorial0SyntheticCapture } from './fixtures/tutorial0-capture';
import {
  tutorial0CapturedPromptCards,
  tutorial0ReviewedTutorial,
} from './fixtures/tutorial0-prompts';
import type { CaptureReuseRequirement } from './captureReuse';
import type { PromptCardModel } from './promptIntent';
import type { RoutedTutorialStep } from './tutorialPackage';
import { orchestrateTutorialVisual } from './tutorialVisualOrchestration';

function reviewedStep(id: string) {
  const step = tutorial0ReviewedTutorial.retained_steps.find((item) => item.review_step_id === id);
  if (!step) throw new Error(`missing reviewed step: ${id}`);
  return step;
}

const square = reviewedStep('tutorial0-step-03-square-file');
const squareCard = tutorial0CapturedPromptCards.find((card) => card.stepNumber === square.sequence)!;

function captureRequirement(): CaptureReuseRequirement {
  return {
    logical_request_id: 'capture-request:tutorial0:square:action',
    expected_application: 'Adobe Express',
    image_state: 'action',
    requested_ui_claims: ['Create new'],
    require_target_geometry: true,
  };
}

function routedStep(overrides: Partial<RoutedTutorialStep> = {}): RoutedTutorialStep {
  return {
    reviewStepId: square.review_step_id,
    visualRoleRef: 'visual-role://tutorial-frame',
    disposition: 'new-visual',
    ...overrides,
  };
}

function currentReferenceCard(): PromptCardModel {
  const state = squareCard.capturedScreenEvidence?.action;
  if (!state) throw new Error('fixture missing action evidence');
  return {
    ...squareCard,
    currentVisualReference: {
      reference_id: 'tutorial0-square-current',
      application: 'Adobe Express',
      application_variant: 'Education',
      context_state: 'create-new',
      captured_at: '2026-09-08T12:00:00Z',
      verified_at: '2026-09-08T12:05:00Z',
      sanitized_derivative_reference: state.screenshot_reference,
      source_reference: state.screenshot_reference,
      provenance: ['capture-evidence'],
      visible_ui_claims: ['Create new'],
      manifest_reference: state.manifest_reference,
      asset_reference: state.asset_reference,
    },
  };
}

const unusedCaptureAdapter = vi.fn(() => ({
  transport_status: 'failed' as const,
  capture_status: 'blocked' as const,
  capture_ref: null,
  reason_codes: ['unexpected'],
  side_effects_performed: false,
}));

describe('#2101 tutorial visual orchestration', () => {
  it('honors an approved existing visual before capture or generation', async () => {
    const capture = vi.fn(unusedCaptureAdapter);
    const result = await orchestrateTutorialVisual({
      routed_step: routedStep({ disposition: 'reuse-existing-visual', approvedAssetRef: 'asset://approved' }),
      reviewed_step: square,
      prompt_card: null,
      capture_requirement: null,
      capture_bundle: null,
      capture_request_adapter: capture,
    });
    expect(result.disposition).toBe('reuse-existing-visual');
    expect(result.generation_strategy.approvedAssetRef).toBe('asset://approved');
    expect(capture).not.toHaveBeenCalled();
  });

  it('reuses exact current capture evidence before crossing #2100', async () => {
    const capture = vi.fn(unusedCaptureAdapter);
    const result = await orchestrateTutorialVisual({
      routed_step: routedStep(),
      reviewed_step: square,
      prompt_card: currentReferenceCard(),
      capture_requirement: captureRequirement(),
      capture_bundle: tutorial0SyntheticCapture,
      capture_request_adapter: capture,
    });
    expect(result.generation_strategy.strategy).toBe('current-reference-composite');
    expect(result.capture_reuse?.disposition).toBe('REUSE_EXISTING_CAPTURE');
    expect(result.disposition).toBe('exact-composite-ready');
    expect(capture).not.toHaveBeenCalled();
  });

  it('crosses #2100 exactly once only when capture is required', async () => {
    const capture = vi.fn(() => ({
      transport_status: 'succeeded' as const,
      capture_status: 'valid' as const,
      capture_ref: 'capture://fresh',
      reason_codes: [] as string[],
      side_effects_performed: true,
    }));
    const result = await orchestrateTutorialVisual({
      routed_step: routedStep(),
      reviewed_step: square,
      prompt_card: currentReferenceCard(),
      capture_requirement: captureRequirement(),
      capture_bundle: null,
      capture_request_adapter: capture,
    });
    expect(result.capture_reuse?.disposition).toBe('CAPTURE_REQUIRED');
    expect(result.disposition).toBe('capture-required');
    expect(capture).toHaveBeenCalledTimes(1);
    expect(result.browser_runs_launched).toBe(1);
  });

  it('derives duplicate-run observability from the #2100 receipt', async () => {
    const capture = vi.fn(() => ({
      transport_status: 'deduplicated' as const,
      capture_status: 'valid' as const,
      capture_ref: 'capture://existing',
      reason_codes: ['duplicate-request-reused'],
      side_effects_performed: false,
    }));
    const result = await orchestrateTutorialVisual({
      routed_step: routedStep(),
      reviewed_step: square,
      prompt_card: currentReferenceCard(),
      capture_requirement: captureRequirement(),
      capture_bundle: null,
      capture_request_adapter: capture,
    });
    expect(capture).toHaveBeenCalledTimes(1);
    expect(result.duplicate_runs_avoided).toBe(1);
    expect(result.browser_runs_launched).toBe(0);
  });

  it('fails closed on manual review without capture or render execution', async () => {
    const capture = vi.fn(unusedCaptureAdapter);
    const executor = { execute: vi.fn() };
    const result = await orchestrateTutorialVisual({
      routed_step: routedStep(),
      reviewed_step: square,
      prompt_card: currentReferenceCard(),
      capture_requirement: captureRequirement(),
      capture_bundle: { ...tutorial0SyntheticCapture, status: 'manual-review-required' },
      capture_request_adapter: capture,
      exact_composite_executor: executor,
    });
    expect(result.disposition).toBe('manual-review-required');
    expect(capture).not.toHaveBeenCalled();
    expect(executor.execute).not.toHaveBeenCalled();
  });

  it('never turns orchestration success into classroom, publication, or external-write authority', async () => {
    const result = await orchestrateTutorialVisual({
      routed_step: routedStep({ disposition: 'reuse-existing-visual', approvedAssetRef: 'asset://approved' }),
      reviewed_step: square,
      prompt_card: null,
      capture_requirement: null,
      capture_bundle: null,
      capture_request_adapter: unusedCaptureAdapter,
    });
    expect(result.execution_authorized).toBe(false);
    expect(result.classroom_ready).toBe(false);
    expect(result.publication_authorized).toBe(false);
    expect(result.external_write_authorized).toBe(false);
  });
});
