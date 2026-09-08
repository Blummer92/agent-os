import { describe, expect, it } from 'vitest';
import type { FidelityEvaluationResult } from './fidelityEvaluation';
import { planGenerationStrategy } from './generationStrategy';
import { observeProviderExecution } from './tutorialAdaptationOutcome';
import type { PromptCardModel } from './promptIntent';
import type { RoutedTutorialStep } from './tutorialPackage';
import type { ApprovedVisualReference } from './visualReference';

const execution = observeProviderExecution('not-attempted', null);

function step(overrides: Partial<RoutedTutorialStep> = {}): RoutedTutorialStep {
  return {
    reviewStepId: 'step-1',
    visualRoleRef: 'visual-role:1',
    disposition: 'new-visual',
    ...overrides,
  };
}

const reference: ApprovedVisualReference = {
  reference_id: 'adobe-editor-add-content',
  application: 'Adobe Express',
  application_variant: 'Education',
  context_state: 'editor/add-content',
  captured_at: '2026-09-07T12:00:00Z',
  verified_at: '2026-09-07T12:05:00Z',
  sanitized_derivative_reference: 'sanitized://editor-add-content',
  source_reference: 'teacher-upload://editor-add-content',
  provenance: ['owner-approved-current-reference'],
  visible_ui_claims: ['Adobe Express', 'Add content'],
  manifest_reference: {
    manifest_id: 'manifest-current-ui',
    record_revision: 1,
    fingerprint: 'manifest-fingerprint',
    verified_at: '2026-09-07T12:05:00Z',
    external_file_id: 'sanitized-current-ui',
  },
  asset_reference: {
    asset_id: 'asset-current-ui',
    stable_ref: 'visual-reference://editor-add-content',
    content_fingerprint: 'current-ui-fingerprint',
  },
};

function card(overrides: Partial<PromptCardModel> = {}): PromptCardModel {
  return {
    stepNumber: 1,
    imagePurpose: 'Show the instructional state.',
    imageState: 'action',
    application: 'Adobe Express',
    applicationContext: '',
    targetState: 'understand hierarchy',
    mustShow: ['primary and secondary emphasis'],
    mustNotShow: [],
    annotationSpace: 'beside the example',
    provenance: ['Teacher Modeling'],
    requestedUiDetails: [],
    requiresScreenFidelity: false,
    capturedScreenEvidence: null,
    capturedScreenRef: null,
    currentVisualReference: null,
    evidence: { recordingClaimTexts: [], stateLocalClaims: [], actionIdentity: [] },
    portablePrompt: 'semantic prompt',
    status: 'ready',
    blockerReasons: [],
    ...overrides,
  };
}

const fidelity: FidelityEvaluationResult = {
  status: 'evaluated',
  provider: 'experiment-provider',
  model: 'experiment-model',
  prompt_strategy: 'reference-composite',
  instructional_state: 'pass',
  interface_fidelity: 'pass',
  artifact_state_fidelity: 'pass',
  negative_constraints: 'pass',
  execution_completion: 'pass',
  reasons: [],
  generated_output_is_source_evidence: false,
};

describe('PPUX #2014 generation strategy', () => {
  it('keeps conceptual visuals on the semantic synthetic path without a UI reference', () => {
    const result = planGenerationStrategy(step(), card(), execution);
    expect(result.status).toBe('ready');
    expect(result.strategy).toBe('semantic-synthetic');
    expect(result.currentVisualReferenceRef).toBeNull();
  });

  it('permits current-application generation only with the selected approved exact-state reference', () => {
    const result = planGenerationStrategy(step(), card({
      requiresScreenFidelity: true,
      applicationContext: 'Adobe Express Add content panel',
      requestedUiDetails: ['Add content'],
      currentVisualReference: reference,
    }), execution);
    expect(result.status).toBe('ready');
    expect(result.strategy).toBe('current-reference-composite');
    expect(result.currentVisualReferenceRef).toBe('visual-reference://editor-add-content');
  });

  it('fails closed when a screen-fidelity card has no sufficient current application reference', () => {
    const result = planGenerationStrategy(step(), card({
      requiresScreenFidelity: true,
      applicationContext: 'Adobe Express Add content panel',
      requestedUiDetails: ['Add content'],
      currentVisualReference: null,
    }), execution);
    expect(result.status).toBe('blocked');
    expect(result.strategy).toBeNull();
    expect(result.blockerReasons).toEqual(['current-application-reference-insufficient']);
  });

  it('does not expose a generation strategy for a prompt card already blocked by reference sufficiency', () => {
    const result = planGenerationStrategy(step(), card({
      status: 'blocked',
      portablePrompt: '',
      requiresScreenFidelity: true,
      blocker: 'The exact current state is unsupported.',
      blockerReasons: ['visual-reference-claims-not-co-visible'],
    }), execution);
    expect(result.status).toBe('blocked');
    expect(result.blockerReasons).toEqual(['prompt-card-blocked']);
  });

  it.each([
    ['reuse-existing-visual', 'asset://approved-existing', 'reuse-existing-visual'],
    ['resurface-prior-visual', 'asset://approved-prior', 'resurface-prior-visual'],
  ] as const)('uses approved %s evidence without requesting equivalent generation', (disposition, asset, strategy) => {
    const result = planGenerationStrategy(step({ disposition, approvedAssetRef: asset }), null, execution);
    expect(result.status).toBe('ready');
    expect(result.strategy).toBe(strategy);
    expect(result.approvedAssetRef).toBe(asset);
  });

  it('preserves provider execution and fidelity as separate non-authoritative evidence', () => {
    const unavailable = observeProviderExecution('provider-unavailable', null);
    const result = planGenerationStrategy(step(), card(), unavailable, fidelity);
    expect(result.status).toBe('ready');
    expect(result.strategy).toBe('semantic-synthetic');
    expect(result.providerExecution.status).toBe('provider-unavailable');
    expect(result.fidelityEvaluation?.provider).toBe('experiment-provider');
    expect(result.executionAuthorized).toBe(false);
    expect(result.productionAuthorized).toBe(false);
    expect(result.externalWriteAuthorized).toBe(false);
  });

  it('never converts provider failure into no-additional-visual-needed', () => {
    const unavailable = observeProviderExecution('provider-unavailable', null);
    const needed = planGenerationStrategy(step(), card(), unavailable);
    const notNeeded = planGenerationStrategy(step({
      disposition: 'no-additional-visual-needed',
      reasonRef: 'Teacher Modeling:no-new-visual',
    }), null, unavailable);
    expect(needed.strategy).toBe('semantic-synthetic');
    expect(notNeeded.strategy).toBe('no-generation-needed');
    expect(needed.providerExecution.status).toBe(notNeeded.providerExecution.status);
  });
});
