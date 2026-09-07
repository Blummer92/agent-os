import { describe, expect, it } from 'vitest';
import {
  composeTutorialSupportOutcome,
  observeProviderExecution,
} from './tutorialAdaptationOutcome';
import type {
  TeacherReviewedEvidenceSummary,
  TutorialAdaptationRecommendation,
  TutorialAdaptationResult,
} from './tutorialAdaptation';

function summary(overrides: Partial<TeacherReviewedEvidenceSummary> = {}): TeacherReviewedEvidenceSummary {
  return {
    recordId: 'eia-1', recordRevision: 1, fingerprint: 'f'.repeat(64), sourceRef: 'teacher-summary:1',
    sourceType: 'teacher-summary', privacyEligible: true, freshness: 'current', measurementQuality: 'sufficient',
    overallDisposition: 'direct-evidence', dimensionResults: [], whatSupported: [], whatRemainsUnmeasured: [],
    confidence: 'high', manualReviewRequired: false, contradictions: [], uncertainties: [],
    authority: {
      gradingAuthorized: false, masteryAuthorized: false, readinessAuthorized: false,
      learnerClassificationAuthorized: false, placementAuthorized: false, routeAssignmentAuthorized: false,
      pacingExecutionAuthorized: false, productionAuthorized: false, publicationAuthorized: false,
      externalWriteAuthorized: false,
    },
    ...overrides,
  };
}

function recommendation(action: TutorialAdaptationRecommendation['action']): TutorialAdaptationRecommendation {
  return {
    recommendationId: 'rec-1', sourceEvidenceRecordId: 'eia-1', sourceEvidenceRevision: 1,
    sourceEvidenceFingerprint: 'f'.repeat(64), tutorialRouteId: 'route-1', tutorialSourceFingerprint: 's'.repeat(64),
    reviewStepId: 'step-1', objectiveRef: 'objective-1', evidenceTargetRef: 'evidence-1', claimId: 'claim-1',
    targetClassification: 'conceptual_understanding', dimension: 'conceptual', evidenceDisposition: 'direct-evidence',
    triggeringDimensions: [], action, reasonCodes: [], mustRemainUnchanged: [], reviewOwner: 'instructional-materials-coach',
    applicationAuthorized: false, masteryAuthorized: false, gradingAuthorized: false, placementAuthorized: false,
    routeAssignmentAuthorized: false, readinessAuthorized: false, classroomUseAuthorized: false,
    productionAuthorized: false, externalWriteAuthorized: false,
  };
}

function adaptation(status: TutorialAdaptationResult['status'], actions: TutorialAdaptationRecommendation['action'][]): TutorialAdaptationResult {
  return { status, recommendations: actions.map(recommendation) };
}

describe('PPUX-H2 adaptation/execution outcome separation', () => {
  it('represents contradictory evidence as diagnostic support without targeted adaptation authority', () => {
    const outcome = composeTutorialSupportOutcome(
      adaptation('insufficient-evidence', ['insufficient-evidence']),
      summary({ contradictions: ['concept and tool evidence conflict'], manualReviewRequired: true }),
      'new-visual',
    );
    expect(outcome.instructional.need).toBe('diagnostic-support-recommended');
    expect(outcome.masteryAuthorized).toBe(false);
    expect(outcome.gradingAuthorized).toBe(false);
    expect(outcome.pathwayAuthorized).toBe(false);
  });

  it('keeps provider unavailability separate when targeted visual support is still needed', () => {
    const outcome = composeTutorialSupportOutcome(
      adaptation('recommended', ['add-concept-model']), summary(), 'new-visual',
      observeProviderExecution('provider-unavailable', null),
    );
    expect(outcome.instructional.need).toBe('targeted-support-recommended');
    expect(outcome.instructional.fulfillmentDisposition).toBe('new-visual');
    expect(outcome.execution.status).toBe('provider-unavailable');
  });

  it('records text-only return as modality mismatch without changing the image support need', () => {
    const outcome = composeTutorialSupportOutcome(
      adaptation('recommended', ['add-comparison']), summary(), 'new-visual',
      observeProviderExecution('modality-mismatch', 'text'),
    );
    expect(outcome.instructional.need).toBe('targeted-support-recommended');
    expect(outcome.execution).toMatchObject({ status: 'modality-mismatch', requestedModality: 'image', returnedModality: 'text' });
  });

  it('preserves explicit no-additional/reuse/resurface decisions independently of provider execution', () => {
    expect(composeTutorialSupportOutcome(adaptation('recommended', ['retain']), summary(), 'no-additional-visual-needed').instructional.need)
      .toBe('no-additional-visual-needed');
    expect(composeTutorialSupportOutcome(adaptation('recommended', ['resurface']), summary(), 'resurface-prior-visual').instructional.need)
      .toBe('reuse-or-resurface-existing-support');
  });

  it('keeps insufficient evidence from becoming targeted support and leaves final artifact form unset', () => {
    const outcome = composeTutorialSupportOutcome(
      adaptation('insufficient-evidence', ['insufficient-evidence']), summary({ overallDisposition: 'not-comparable' }), 'new-visual',
    );
    expect(outcome.instructional.need).toBe('retain-current-coverage');
    expect(outcome.finalArtifactType).toBeNull();
    expect(outcome.productionAuthorized).toBe(false);
    expect(outcome.externalWriteAuthorized).toBe(false);
  });

  it('cannot let provider failure remove COV1-required fulfillment', () => {
    const outcome = composeTutorialSupportOutcome(
      adaptation('recommended', ['retain']), summary(), 'new-visual', observeProviderExecution('provider-unavailable', null),
    );
    expect(outcome.instructional.fulfillmentDisposition).toBe('new-visual');
    expect(outcome.execution.executionAuthorized).toBe(false);
    expect(outcome.execution.productionAuthorized).toBe(false);
    expect(outcome.execution.externalWriteAuthorized).toBe(false);
  });
});
