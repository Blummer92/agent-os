import { decideCaptureReuse, type CaptureReuseDecision, type CaptureReuseRequirement } from './captureReuse';
import type { CaptureEvidenceBundle } from './captureEvidence';
import type { ExactCompositeExecutionOutput, ExactCompositeExecutionRequest, ExactCompositeExecutor } from './executorContract';
import { planGenerationStrategy, type GenerationStrategyResult } from './generationStrategy';
import type { PromptCardModel } from './promptIntent';
import { observeProviderExecution } from './tutorialAdaptationOutcome';
import type { RoutedTutorialStep } from './tutorialPackage';
import type { ReviewedStepProjection } from './types';

export type CaptureReceiptEvidence = Readonly<{
  transport_status: 'succeeded' | 'deduplicated' | 'failed' | 'not-invoked';
  capture_status: 'valid' | 'blocked';
  capture_ref: string | null;
  reason_codes: readonly string[];
  side_effects_performed: boolean;
}>;

export type CaptureRequestAdapter = (
  requirement: CaptureReuseRequirement,
) => CaptureReceiptEvidence;

export type TutorialVisualDisposition =
  | 'reuse-existing-visual'
  | 'resurface-prior-visual'
  | 'no-generation-needed'
  | 'capture-required'
  | 'manual-review-required'
  | 'exact-composite-ready'
  | 'exact-composite-rendered'
  | 'semantic-synthetic-ready'
  | 'blocked';

export type TutorialVisualOrchestrationResult = Readonly<{
  disposition: TutorialVisualDisposition;
  capture_reuse: CaptureReuseDecision | null;
  capture_receipt: CaptureReceiptEvidence | null;
  generation_strategy: GenerationStrategyResult;
  exact_composite_output: ExactCompositeExecutionOutput | null;
  browser_runs_launched: 0 | 1;
  duplicate_runs_avoided: 0 | 1;
  execution_authorized: false;
  classroom_ready: false;
  publication_authorized: false;
  external_write_authorized: false;
}>;

function result(
  disposition: TutorialVisualDisposition,
  generationStrategy: GenerationStrategyResult,
  captureReuse: CaptureReuseDecision | null = null,
  captureReceipt: CaptureReceiptEvidence | null = null,
  exactCompositeOutput: ExactCompositeExecutionOutput | null = null,
): TutorialVisualOrchestrationResult {
  return Object.freeze({
    disposition,
    capture_reuse: captureReuse,
    capture_receipt: captureReceipt,
    generation_strategy: generationStrategy,
    exact_composite_output: exactCompositeOutput,
    browser_runs_launched: captureReceipt?.side_effects_performed === true ? 1 : 0,
    duplicate_runs_avoided: captureReceipt?.transport_status === 'deduplicated' ? 1 : 0,
    execution_authorized: false,
    classroom_ready: false,
    publication_authorized: false,
    external_write_authorized: false,
  });
}

/**
 * #2101 composition owner.
 *
 * This is deliberately a composition seam, not another evidence, idempotency,
 * capture, strategy, or compositor owner. Existing route dispositions are
 * consumed first. A new current-application visual evaluates #2109 reuse before
 * crossing #2100. Exact-composite execution is possible only from an already
 * resolved #2075 request supplied by the caller; this function never invents
 * geometry, source pixels, assets, or provider authority.
 */
export async function orchestrateTutorialVisual(input: Readonly<{
  routed_step: RoutedTutorialStep;
  reviewed_step: ReviewedStepProjection;
  prompt_card: PromptCardModel | null;
  capture_requirement: CaptureReuseRequirement | null;
  capture_bundle: CaptureEvidenceBundle | null;
  capture_request_adapter: CaptureRequestAdapter;
  exact_composite_request?: ExactCompositeExecutionRequest | null;
  exact_composite_executor?: ExactCompositeExecutor | null;
}>): Promise<TutorialVisualOrchestrationResult> {
  const providerExecution = observeProviderExecution('not-attempted', null);
  const strategy = planGenerationStrategy(input.routed_step, input.prompt_card, providerExecution);

  if (strategy.status !== 'ready' || strategy.strategy === null) {
    return result('blocked', strategy);
  }

  if (strategy.strategy === 'reuse-existing-visual' || strategy.strategy === 'resurface-prior-visual') {
    return result(strategy.strategy, strategy);
  }

  if (strategy.strategy === 'no-generation-needed') {
    return result('no-generation-needed', strategy);
  }

  if (strategy.strategy === 'semantic-synthetic') {
    return result('semantic-synthetic-ready', strategy);
  }

  if (!input.capture_requirement) {
    return result('blocked', strategy);
  }

  const reuse = decideCaptureReuse(input.reviewed_step, input.capture_requirement, input.capture_bundle);
  if (reuse.disposition === 'MANUAL_REVIEW_REQUIRED') {
    return result('manual-review-required', strategy, reuse);
  }

  if (reuse.disposition === 'CAPTURE_REQUIRED') {
    const receipt = input.capture_request_adapter(input.capture_requirement);
    return result('capture-required', strategy, reuse, receipt);
  }

  if (!input.exact_composite_request) {
    return result('exact-composite-ready', strategy, reuse);
  }
  if (!input.exact_composite_executor) {
    return result('blocked', strategy, reuse);
  }

  const output = await input.exact_composite_executor.execute(input.exact_composite_request);
  return result('exact-composite-rendered', strategy, reuse, null, output);
}
