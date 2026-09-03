import { describe, expect, it } from 'vitest';
import type { TutorialPackage } from './tutorialPackage';
import {
  validateTutorialCoverage,
  type AssessmentTargetClassification,
  type TutorialCoverageBinding,
  type TutorialCoverageRole,
} from './tutorialCoverage';

function packageWith(disposition: TutorialPackage['steps'][number]['disposition'] = 'new-visual'): TutorialPackage {
  return {
    packageVersion: 'picture-perfect-tutorial-package-v1',
    routeId: 'route-coverage-1',
    sourceHandoffRef: 'modeling-handoff-1',
    sourceFingerprint: 'sha256:handoff-current',
    recordingId: 'recording-1',
    recordingSha256: 'sha256:recording',
    objectiveRef: 'objective-layout-hierarchy',
    successCriteriaRef: 'success-hierarchy-purpose',
    evidenceTargetRef: 'evidence-layout-product',
    pathwayPlanRef: null,
    steps: [{
      reviewStepId: 'step-1',
      visualRoleRef: 'teacher-model',
      disposition,
      ...(disposition === 'new-visual' ? { authoring: {
        imagePurpose: 'Model the approved step.',
        imageState: 'action' as const,
        applicationContext: 'Adobe Express editor layout workflow',
        targetState: 'editor/layout',
        mustShow: ['Layout controls'],
        mustNotShow: ['invented controls'],
        annotationSpace: 'right side',
        requestedUiDetails: [],
      } } : {}),
      ...(disposition === 'reuse-existing-visual' || disposition === 'resurface-prior-visual'
        ? { approvedAssetRef: 'asset://tutorial/step-1' } : {}),
      ...(disposition === 'no-additional-visual-needed' || disposition === 'pathway-compacted'
        ? { reasonRef: 'lp://reason/1' } : {}),
    }],
    cards: [],
    reusedAssetRefs: disposition === 'reuse-existing-visual' ? ['asset://tutorial/step-1'] : [],
    resurfacedAssetRefs: disposition === 'resurface-prior-visual' ? ['asset://tutorial/step-1'] : [],
    executionAuthorized: false,
    externalWriteAuthorized: false,
    productionAuthorized: false,
  };
}

function binding(
  classification: AssessmentTargetClassification,
  roles: readonly TutorialCoverageRole[],
  overrides: Partial<TutorialCoverageBinding> = {},
): TutorialCoverageBinding {
  return {
    reviewStepId: 'step-1',
    modelingHandoffRef: 'modeling-handoff-1',
    modelingMomentRef: 'modeling-moment-1',
    objectiveRef: 'objective-layout-hierarchy',
    successCriteriaRef: 'success-hierarchy-purpose',
    evidenceTargetRef: 'evidence-layout-product',
    visualRoleRef: 'teacher-model',
    fulfillmentDisposition: 'new-visual',
    coverageRoles: roles,
    toolOrProcedureRef: 'procedure://adobe/layout',
    assessment: {
      blueprintId: 'blueprint-1',
      blueprintVersion: '3',
      designRecordId: 'assessment-design-1',
      claimId: 'claim-1',
      observableEvidenceId: 'evidence-1',
      approvedTargetRef: 'objective-layout-hierarchy',
      evidenceTargetRef: 'evidence-layout-product',
      primaryTargetClassification: classification,
      current: true,
    },
    sourceFingerprint: 'sha256:handoff-current',
    current: true,
    ...overrides,
  };
}

describe('classification-specific tutorial coverage', () => {
  it('accepts technical workflow only with modeled tool/procedure execution', () => {
    expect(validateTutorialCoverage(packageWith(), [binding('technical_workflow', ['tool-or-procedure-execution'])]).status).toBe('valid');
    expect(validateTutorialCoverage(packageWith(), [binding('technical_workflow', ['recall-or-definition'])]).findings)
      .toContain('execution-model-missing');
  });

  it('does not substitute tool clicks for conceptual reasoning', () => {
    expect(validateTutorialCoverage(packageWith(), [binding('conceptual_understanding', ['concept-explanation'])]).status).toBe('valid');
    expect(validateTutorialCoverage(packageWith(), [binding('conceptual_understanding', ['tool-or-procedure-execution'])]).findings)
      .toContain('concept-reasoning-model-missing');
  });

  it('requires criteria/evidence use for critique', () => {
    expect(validateTutorialCoverage(packageWith(), [binding('critique', ['recall-or-definition'])]).findings)
      .toContain('criteria-use-model-missing');
  });

  it('requires the complete revision cycle', () => {
    expect(validateTutorialCoverage(packageWith(), [binding('revision', ['revision-prior-state', 'revision-change'])]).findings)
      .toContain('revision-cycle-model-missing');
    expect(validateTutorialCoverage(packageWith(), [binding('revision', [
      'revision-prior-state', 'revision-feedback-or-evidence', 'revision-change', 'revision-revised-state',
    ])]).status).toBe('valid');
  });

  it('does not treat mechanical completion as creative-production judgment', () => {
    expect(validateTutorialCoverage(packageWith(), [binding('creative_production', ['tool-or-procedure-execution'])]).findings)
      .toContain('creator-decision-model-missing');
    expect(validateTutorialCoverage(packageWith(), [binding('creative_production', ['creator-choice-and-rationale'])]).status).toBe('valid');
  });
});

describe('identity, reuse, and compacting boundaries', () => {
  it('fails closed on stale assessment or source identity', () => {
    expect(validateTutorialCoverage(packageWith(), [binding('technical_workflow', ['tool-or-procedure-execution'], {
      sourceFingerprint: 'sha256:old-handoff',
    })]).findings).toContain('assessment-reference-missing-or-stale');

    expect(validateTutorialCoverage(packageWith(), [binding('technical_workflow', ['tool-or-procedure-execution'], {
      assessment: { ...binding('technical_workflow', []).assessment, current: false },
    })]).findings).toContain('assessment-reference-missing-or-stale');
  });

  it('fails closed when the modeling moment is missing', () => {
    expect(validateTutorialCoverage(packageWith(), [binding('technical_workflow', ['tool-or-procedure-execution'], {
      modelingMomentRef: '',
    })]).findings).toContain('modeling-reference-missing-or-stale');
  });

  it('allows reused and resurfaced canonical support to satisfy coverage', () => {
    for (const disposition of ['reuse-existing-visual', 'resurface-prior-visual'] as const) {
      const pkg = packageWith(disposition);
      const result = validateTutorialCoverage(pkg, [binding('technical_workflow', ['tool-or-procedure-execution'], {
        fulfillmentDisposition: disposition,
      })]);
      expect(result.status).toBe('valid');
    }
  });

  it('does not let compacting become the only proof of required capability coverage', () => {
    const pkg = packageWith('pathway-compacted');
    const result = validateTutorialCoverage(pkg, [binding('technical_workflow', ['tool-or-procedure-execution'], {
      fulfillmentDisposition: 'pathway-compacted',
    })]);
    expect(result.findings).toContain('execution-model-missing');
  });

  it('keeps every downstream authority false', () => {
    const result = validateTutorialCoverage(packageWith(), [binding('technical_workflow', ['tool-or-procedure-execution'])]);
    expect(result).toMatchObject({
      masteryAuthorized: false,
      gradingAuthorized: false,
      readinessAuthorized: false,
      classroomUseAuthorized: false,
      productionAuthorized: false,
      externalWriteAuthorized: false,
    });
  });
});
