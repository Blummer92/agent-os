import type { FidelityEvaluationResult } from './fidelityEvaluation';
import type { PromptCardModel } from './promptIntent';
import type { ProviderExecutionObservation } from './tutorialAdaptationOutcome';
import type { RoutedTutorialStep } from './tutorialPackage';

export type GenerationStrategy =
  | 'semantic-synthetic'
  | 'current-reference-composite'
  | 'reuse-existing-visual'
  | 'resurface-prior-visual'
  | 'no-generation-needed';

export type GenerationStrategyBlocker =
  | 'prompt-card-blocked'
  | 'current-application-reference-insufficient'
  | 'approved-reuse-asset-missing';

export type GenerationStrategyResult = Readonly<{
  status: 'ready' | 'blocked';
  strategy: GenerationStrategy | null;
  blockerReasons: readonly GenerationStrategyBlocker[];
  approvedAssetRef: string | null;
  currentVisualReferenceRef: string | null;
  providerExecution: ProviderExecutionObservation;
  fidelityEvaluation: FidelityEvaluationResult | null;
  executionAuthorized: false;
  productionAuthorized: false;
  externalWriteAuthorized: false;
}>;

function blocked(
  blockerReasons: readonly GenerationStrategyBlocker[],
  providerExecution: ProviderExecutionObservation,
  fidelityEvaluation: FidelityEvaluationResult | null,
): GenerationStrategyResult {
  return Object.freeze({
    status: 'blocked',
    strategy: null,
    blockerReasons: Object.freeze([...new Set(blockerReasons)]),
    approvedAssetRef: null,
    currentVisualReferenceRef: null,
    providerExecution,
    fidelityEvaluation,
    executionAuthorized: false,
    productionAuthorized: false,
    externalWriteAuthorized: false,
  });
}

/**
 * Select the representation execution strategy without executing a provider.
 * Current-application UI generation is allowed only from the exact approved
 * reference already selected by the existing PPUX visual-reference contract.
 */
export function planGenerationStrategy(
  step: RoutedTutorialStep,
  card: PromptCardModel | null,
  providerExecution: ProviderExecutionObservation,
  fidelityEvaluation: FidelityEvaluationResult | null = null,
): GenerationStrategyResult {
  if (step.disposition === 'reuse-existing-visual' || step.disposition === 'resurface-prior-visual') {
    const approvedAssetRef = step.approvedAssetRef?.trim() || null;
    if (!approvedAssetRef) {
      return blocked(['approved-reuse-asset-missing'], providerExecution, fidelityEvaluation);
    }
    return Object.freeze({
      status: 'ready',
      strategy: step.disposition,
      blockerReasons: [],
      approvedAssetRef,
      currentVisualReferenceRef: null,
      providerExecution,
      fidelityEvaluation,
      executionAuthorized: false,
      productionAuthorized: false,
      externalWriteAuthorized: false,
    });
  }

  if (step.disposition === 'no-additional-visual-needed' || step.disposition === 'pathway-compacted') {
    return Object.freeze({
      status: 'ready',
      strategy: 'no-generation-needed',
      blockerReasons: [],
      approvedAssetRef: null,
      currentVisualReferenceRef: null,
      providerExecution,
      fidelityEvaluation,
      executionAuthorized: false,
      productionAuthorized: false,
      externalWriteAuthorized: false,
    });
  }

  if (!card || card.status !== 'ready') {
    return blocked(['prompt-card-blocked'], providerExecution, fidelityEvaluation);
  }

  if (!card.requiresScreenFidelity) {
    return Object.freeze({
      status: 'ready',
      strategy: 'semantic-synthetic',
      blockerReasons: [],
      approvedAssetRef: null,
      currentVisualReferenceRef: null,
      providerExecution,
      fidelityEvaluation,
      executionAuthorized: false,
      productionAuthorized: false,
      externalWriteAuthorized: false,
    });
  }

  const currentReference = card.currentVisualReference ?? null;
  if (!currentReference) {
    return blocked(['current-application-reference-insufficient'], providerExecution, fidelityEvaluation);
  }

  return Object.freeze({
    status: 'ready',
    strategy: 'current-reference-composite',
    blockerReasons: [],
    approvedAssetRef: null,
    currentVisualReferenceRef: currentReference.asset_reference.stable_ref,
    providerExecution,
    fidelityEvaluation,
    executionAuthorized: false,
    productionAuthorized: false,
    externalWriteAuthorized: false,
  });
}
