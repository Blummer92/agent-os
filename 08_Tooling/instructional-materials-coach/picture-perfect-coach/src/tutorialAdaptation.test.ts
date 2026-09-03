import { describe, expect, it } from 'vitest';
import type { TutorialPackage } from './tutorialPackage';
import type { TutorialCoverageBinding } from './tutorialCoverage';
import {
  recommendTutorialAdaptations,
  type EvidenceDimensionResult,
  type TeacherReviewedEvidenceSummary,
} from './tutorialAdaptation';

function pkg(stepCount = 1): TutorialPackage {
  return {
    packageVersion: 'picture-perfect-tutorial-package-v1',
    routeId: 'route-fb1',
    sourceHandoffRef: 'modeling-handoff-1',
    sourceFingerprint: 'sha256:tutorial-current',
    recordingId: 'recording-1',
    recordingSha256: 'sha256:recording',
    objectiveRef: 'objective-hierarchy',
    successCriteriaRef: 'success-purposeful-hierarchy',
    evidenceTargetRef: 'evidence-designed-layout',
    pathwayPlanRef: null,
    steps: Array.from({ length: stepCount }, (_, index) => ({
      reviewStepId: `step-${index + 1}`,
      visualRoleRef: 'teacher-model',
      disposition: 'new-visual' as const,
      authoring: {
        imagePurpose: 'Model the approved tutorial step.',
        imageState: 'action' as const,
        applicationContext: 'Adobe Express layout workflow',
        targetState: `editor/step-${index + 1}`,
        mustShow: ['approved controls'],
        mustNotShow: ['invented controls'],
        annotationSpace: 'right',
        requestedUiDetails: [],
      },
    })),
    cards: [],
    reusedAssetRefs: [],
    resurfacedAssetRefs: [],
    executionAuthorized: false,
    externalWriteAuthorized: false,
    productionAuthorized: false,
  };
}

function binding(
  reviewStepId = 'step-1',
  roles: TutorialCoverageBinding['coverageRoles'] = ['concept-explanation'],
  classification: TutorialCoverageBinding['assessment']['primaryTargetClassification'] = 'conceptual_understanding',
  overrides: Partial<TutorialCoverageBinding> = {},
): TutorialCoverageBinding {
  return {
    reviewStepId,
    modelingHandoffRef: 'modeling-handoff-1',
    modelingMomentRef: `modeling-${reviewStepId}`,
    objectiveRef: 'objective-hierarchy',
    successCriteriaRef: 'success-purposeful-hierarchy',
    evidenceTargetRef: 'evidence-designed-layout',
    visualRoleRef: 'teacher-model',
    fulfillmentDisposition: 'new-visual',
    coverageRoles: roles,
    toolOrProcedureRef: 'procedure://adobe/layout',
    assessment: {
      blueprintId: 'blueprint-1',
      blueprintVersion: '4',
      designRecordId: 'assessment-design-1',
      claimId: 'claim-hierarchy',
      observableEvidenceId: 'evidence-hierarchy',
      approvedTargetRef: 'objective-hierarchy',
      evidenceTargetRef: 'evidence-designed-layout',
      primaryTargetClassification: classification,
      current: true,
    },
    sourceFingerprint: 'sha256:tutorial-current',
    current: true,
    ...overrides,
  };
}

function dimensions(overrides: Partial<Record<EvidenceDimensionResult['dimension'], EvidenceDimensionResult['disposition']>> = {}): EvidenceDimensionResult[] {
  const definitions: Array<[EvidenceDimensionResult['dimension'], EvidenceDimensionResult['evidenceKind']]> = [
    ['objective', 'academic'], ['prerequisite', 'academic'], ['success-criteria', 'academic'], ['depth', 'academic'],
    ['performance-format', 'academic'], ['tool-or-routine', 'context'], ['representation', 'context'], ['work-mode', 'context'],
  ];
  return definitions.map(([dimension, evidenceKind]) => ({
    dimension,
    evidenceKind,
    matchedRefs: overrides[dimension] === 'not-comparable' ? [] : [`ref:${dimension}`],
    disposition: overrides[dimension] ?? (evidenceKind === 'academic' ? 'direct-evidence' : 'not-comparable'),
  }));
}

function evidence(
  dimensionResults = dimensions(),
  overrides: Partial<TeacherReviewedEvidenceSummary> = {},
): TeacherReviewedEvidenceSummary {
  return {
    recordId: 'eia-summary-1',
    recordRevision: 2,
    fingerprint: 'sha256:eia-final',
    sourceRef: 'teacher-summary-1',
    sourceType: 'teacher-summary',
    privacyEligible: true,
    freshness: 'current',
    measurementQuality: 'sufficient',
    overallDisposition: 'direct-evidence',
    dimensionResults,
    whatSupported: dimensionResults.flatMap((item) => item.matchedRefs),
    whatRemainsUnmeasured: dimensionResults.filter((item) => item.disposition === 'not-comparable').map((item) => item.dimension),
    confidence: 'high',
    manualReviewRequired: false,
    contradictions: [],
    uncertainties: [],
    authority: {
      gradingAuthorized: false,
      masteryAuthorized: false,
      readinessAuthorized: false,
      learnerClassificationAuthorized: false,
      placementAuthorized: false,
      routeAssignmentAuthorized: false,
      pacingExecutionAuthorized: false,
      productionAuthorized: false,
      publicationAuthorized: false,
      externalWriteAuthorized: false,
    },
    ...overrides,
  };
}

describe('PPUX-FB1 evidence-to-support recommendations', () => {
  it('preserves concept coverage and recommends tool support when tool evidence is unmeasured', () => {
    const result = recommendTutorialAdaptations(pkg(), [binding()], evidence());
    expect(result.recommendations.map((item) => item.action)).toContain('add-tool-orientation');
    expect(result.recommendations.every((item) => !item.reasonCodes.includes('concept-failed'))).toBe(true);
  });

  it('does not substitute tool familiarity for conceptual evidence', () => {
    const result = recommendTutorialAdaptations(pkg(), [binding()], evidence(dimensions({
      objective: 'partial-evidence',
      'success-criteria': 'not-comparable',
      depth: 'partial-evidence',
      'tool-or-routine': 'context-evidence',
    }), { overallDisposition: 'partial-evidence', confidence: 'medium' }));
    expect(result.recommendations.map((item) => item.action)).toContain('add-concept-model');
    expect(result.recommendations.map((item) => item.action)).not.toContain('resurface');
  });

  it('preserves support for partial evidence and names unmeasured demands', () => {
    const summary = evidence(dimensions({ 'performance-format': 'not-comparable' }), {
      overallDisposition: 'partial-evidence',
      confidence: 'medium',
      whatRemainsUnmeasured: ['performance-format'],
    });
    expect(recommendTutorialAdaptations(pkg(), [binding()], summary).recommendations.map((item) => item.action)).toContain('retain');
  });

  it('keeps context evidence operational and non-authorizing', () => {
    const summary = evidence(dimensions({
      objective: 'not-comparable', prerequisite: 'not-comparable', 'success-criteria': 'not-comparable', depth: 'not-comparable',
      'performance-format': 'not-comparable', 'tool-or-routine': 'context-evidence', representation: 'context-evidence',
    }), { overallDisposition: 'context-evidence', confidence: 'medium' });
    const result = recommendTutorialAdaptations(pkg(), [binding()], summary);
    expect(result.recommendations.some((item) => item.dimension === 'operational')).toBe(true);
    expect(result.recommendations.every((item) => item.masteryAuthorized === false && item.placementAuthorized === false)).toBe(true);
  });

  it('routes procedure-changing misconception treatment to Teacher Modeling', () => {
    const procedure = binding('step-1', ['tool-or-procedure-execution'], 'technical_workflow', { misconceptionRef: 'misconception://wrong-control' });
    const summary = evidence(dimensions(), { misconceptionRefs: ['misconception://wrong-control'] });
    const recommendation = recommendTutorialAdaptations(pkg(), [procedure], summary).recommendations.find((item) => item.dimension === 'misconception');
    expect(recommendation).toMatchObject({ action: 'route-to-teacher-modeling', reviewOwner: 'teacher-modeling-coach' });
  });

  it('keeps operational friction separate from conceptual failure', () => {
    const summary = evidence(dimensions({
      objective: 'not-comparable', prerequisite: 'not-comparable', 'success-criteria': 'not-comparable', depth: 'not-comparable',
      'performance-format': 'not-comparable', 'tool-or-routine': 'context-evidence', 'work-mode': 'context-evidence',
    }), { overallDisposition: 'context-evidence', confidence: 'medium' });
    const result = recommendTutorialAdaptations(pkg(), [binding()], summary);
    expect(result.recommendations.some((item) => item.action === 'add-tool-orientation')).toBe(true);
    expect(result.recommendations.every((item) => !item.reasonCodes.includes('concept-failed'))).toBe(true);
  });

  it.each([
    { privacyEligible: false },
    { freshness: 'stale' as const },
    { measurementQuality: 'limited' as const },
    { manualReviewRequired: true },
    { contradictions: ['conflict'] },
    { uncertainties: ['uncertain'] },
    { overallDisposition: 'uncertain' as const },
  ])('returns insufficient evidence for non-final EIA input %#', (override) => {
    const result = recommendTutorialAdaptations(pkg(), [binding()], evidence(dimensions(), override));
    expect(result.status).toBe('insufficient-evidence');
    expect(result.recommendations).toHaveLength(1);
    expect(result.recommendations[0]!.action).toBe('insufficient-evidence');
  });

  it('rejects repetition reduction when it removes sole COV1 coverage', () => {
    const result = recommendTutorialAdaptations(pkg(), [binding()], evidence(), { proposedAction: 'reduce-repetition', reviewStepId: 'step-1' });
    expect(result.recommendations[0]!.action).toBe('retain');
    expect(result.recommendations[0]!.reasonCodes).toContain('cov1-preserve-sole-required-coverage');
  });

  it('allows repetition reduction only when another active binding preserves COV1 coverage', () => {
    const packageTwo = pkg(2);
    const bindings = [binding('step-1'), binding('step-2')];
    const result = recommendTutorialAdaptations(packageTwo, bindings, evidence(), { proposedAction: 'reduce-repetition', reviewStepId: 'step-1' });
    expect(result.recommendations[0]!.action).toBe('reduce-repetition');
    expect(result.recommendations[0]!.reasonCodes).toContain('cov1-coverage-preserved');
  });

  it('fails closed on stale tutorial/coverage identity', () => {
    const stale = binding('step-1', ['concept-explanation'], 'conceptual_understanding', { sourceFingerprint: 'sha256:old' });
    expect(recommendTutorialAdaptations(pkg(), [stale], evidence()).status).toBe('blocked');
  });

  it('never mutates the tutorial package and keeps all downstream authority false', () => {
    const tutorial = pkg();
    const before = JSON.stringify(tutorial);
    const result = recommendTutorialAdaptations(tutorial, [binding()], evidence());
    expect(JSON.stringify(tutorial)).toBe(before);
    for (const recommendation of result.recommendations) {
      expect(recommendation).toMatchObject({
        applicationAuthorized: false,
        masteryAuthorized: false,
        gradingAuthorized: false,
        placementAuthorized: false,
        routeAssignmentAuthorized: false,
        readinessAuthorized: false,
        classroomUseAuthorized: false,
        productionAuthorized: false,
        externalWriteAuthorized: false,
      });
    }
  });
});
