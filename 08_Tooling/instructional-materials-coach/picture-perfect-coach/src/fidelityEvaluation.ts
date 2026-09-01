export type FidelityOutcome = 'pass' | 'warn' | 'fail' | 'manual-review';
export type ConstraintOutcome = 'pass' | 'fail' | 'manual-review';
export type ExecutionCompletion = 'pass' | 'fail' | 'manual-review';

export type FidelityEvaluationInput = Readonly<{
  provider: string;
  model: string;
  prompt_strategy?: string | null;
  instructional_state: FidelityOutcome;
  interface_fidelity: FidelityOutcome;
  artifact_state_fidelity: FidelityOutcome;
  negative_constraints: ConstraintOutcome;
  execution_completion: ExecutionCompletion;
  reasons: readonly string[];
  ambiguous?: boolean;
}>;

export type FidelityEvaluationResult = Readonly<{
  status: 'evaluated' | 'manual-review-required';
  provider: string;
  model: string;
  prompt_strategy: string | null;
  instructional_state: FidelityOutcome;
  interface_fidelity: FidelityOutcome;
  artifact_state_fidelity: FidelityOutcome;
  negative_constraints: ConstraintOutcome;
  execution_completion: ExecutionCompletion;
  reasons: readonly string[];
  generated_output_is_source_evidence: false;
}>;

function normalized(value: string): string {
  return value.trim();
}

function uniqueReasons(values: readonly string[]): string[] {
  return [...new Set(values.map(normalized).filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

/**
 * Evaluate already-observed provider output without executing a provider or
 * rewriting canonical ImageIntent. Each fidelity axis remains independent so a
 * polished or instructionally useful image cannot hide a stricter failure.
 */
export function evaluateFidelity(input: FidelityEvaluationInput): FidelityEvaluationResult {
  const provider = normalized(input.provider);
  const model = normalized(input.model);
  if (!provider || !model) throw new Error('provider and model are required evaluation evidence');

  const reasons = uniqueReasons(input.reasons);
  const manualReview = Boolean(input.ambiguous) ||
    input.instructional_state === 'manual-review' ||
    input.interface_fidelity === 'manual-review' ||
    input.artifact_state_fidelity === 'manual-review' ||
    input.negative_constraints === 'manual-review' ||
    input.execution_completion === 'manual-review';

  return {
    status: manualReview ? 'manual-review-required' : 'evaluated',
    provider,
    model,
    prompt_strategy: input.prompt_strategy?.trim() || null,
    instructional_state: input.instructional_state,
    interface_fidelity: input.interface_fidelity,
    artifact_state_fidelity: input.artifact_state_fidelity,
    negative_constraints: input.negative_constraints,
    execution_completion: input.execution_completion,
    reasons,
    generated_output_is_source_evidence: false,
  };
}
