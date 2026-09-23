import type { TutorialFulfillmentDisposition, TutorialPackage } from './tutorialPackage';

/** #837-owned target classifications consumed by reference, never inferred here. */
export type AssessmentTargetClassification =
  | 'recall'
  | 'conceptual_understanding'
  | 'procedural_skill'
  | 'technical_workflow'
  | 'judgment'
  | 'critique'
  | 'revision'
  | 'creative_production'
  | 'performance'
  | 'reflection_metacognition'
  | 'collaboration';

export type TutorialCoverageRole =
  | 'recall-or-definition'
  | 'concept-explanation'
  | 'relationship-reasoning'
  | 'decision-reasoning'
  | 'tool-or-procedure-execution'
  | 'criteria-and-evidence-use'
  | 'revision-prior-state'
  | 'revision-feedback-or-evidence'
  | 'revision-change'
  | 'revision-revised-state'
  | 'creator-choice-and-rationale'
  | 'performance-model';

export type AssessmentCoverageReference = Readonly<{
  blueprintId: string;
  blueprintVersion: string;
  designRecordId: string;
  claimId: string;
  observableEvidenceId: string;
  approvedTargetRef: string;
  evidenceTargetRef: string;
  primaryTargetClassification: AssessmentTargetClassification;
  current: boolean;
}>;

export type TutorialCoverageBinding = Readonly<{
  reviewStepId: string;
  modelingHandoffRef: string;
  modelingMomentRef: string;
  objectiveRef: string;
  successCriteriaRef: string;
  evidenceTargetRef: string;
  visualRoleRef: string;
  fulfillmentDisposition: TutorialFulfillmentDisposition;
  coverageRoles: readonly TutorialCoverageRole[];
  toolOrProcedureRef?: string;
  pathwayPlanRef?: string;
  misconceptionRef?: string;
  assessment: AssessmentCoverageReference;
  sourceFingerprint: string;
  current: boolean;
}>;

export type TutorialCoverageFinding =
  | 'coverage-complete'
  | 'execution-model-missing'
  | 'concept-reasoning-model-missing'
  | 'criteria-use-model-missing'
  | 'revision-cycle-model-missing'
  | 'creator-decision-model-missing'
  | 'assessment-reference-missing-or-stale'
  | 'modeling-reference-missing-or-stale'
  | 'coverage-unproven';

export type TutorialCoverageResult = Readonly<{
  status: 'valid' | 'blocked';
  findings: readonly TutorialCoverageFinding[];
  coveredReviewStepIds: readonly string[];
  assessmentBlueprintRef: string | null;
  assessmentBlueprintVersion: string | null;
  masteryAuthorized: false;
  gradingAuthorized: false;
  readinessAuthorized: false;
  classroomUseAuthorized: false;
  productionAuthorized: false;
  externalWriteAuthorized: false;
}>;

const ACTIVE_DISPOSITIONS = new Set<TutorialFulfillmentDisposition>([
  'new-visual',
  'reuse-existing-visual',
  'resurface-prior-visual',
]);

function hasAnyRole(bindings: readonly TutorialCoverageBinding[], roles: readonly TutorialCoverageRole[]): boolean {
  return bindings.some((binding) => binding.coverageRoles.some((role) => roles.includes(role)));
}

function completeResult(
  status: TutorialCoverageResult['status'],
  findings: readonly TutorialCoverageFinding[],
  coveredReviewStepIds: readonly string[],
  assessment: AssessmentCoverageReference | null,
): TutorialCoverageResult {
  return {
    status,
    findings,
    coveredReviewStepIds,
    assessmentBlueprintRef: assessment?.blueprintId ?? null,
    assessmentBlueprintVersion: assessment?.blueprintVersion ?? null,
    masteryAuthorized: false,
    gradingAuthorized: false,
    readinessAuthorized: false,
    classroomUseAuthorized: false,
    productionAuthorized: false,
    externalWriteAuthorized: false,
  };
}

/**
 * Validate tutorial coverage against already-owned assessment/modeling semantics.
 *
 * This function never reads prompt prose to infer a target, never evaluates a
 * student's work, and never reclassifies #837/#838 assessment evidence. It only
 * checks that current, identity-bound coverage references contain the support
 * roles required by the supplied upstream target classification.
 */
export function validateTutorialCoverage(
  tutorialPackage: TutorialPackage,
  bindings: readonly TutorialCoverageBinding[],
): TutorialCoverageResult {
  if (bindings.length === 0) {
    return completeResult('blocked', ['coverage-unproven'], [], null);
  }

  const assessment = bindings[0]!.assessment;
  const packageSteps = new Map(tutorialPackage.steps.map((step) => [step.reviewStepId, step]));
  const findings: TutorialCoverageFinding[] = [];

  const assessmentMismatch = bindings.some((binding) =>
    !binding.current
    || !binding.assessment.current
    || !binding.assessment.blueprintId.trim()
    || !binding.assessment.blueprintVersion.trim()
    || !binding.assessment.designRecordId.trim()
    || !binding.assessment.claimId.trim()
    || !binding.assessment.observableEvidenceId.trim()
    || binding.assessment.blueprintId !== assessment.blueprintId
    || binding.assessment.blueprintVersion !== assessment.blueprintVersion
    || binding.assessment.designRecordId !== assessment.designRecordId
    || binding.assessment.claimId !== assessment.claimId
    || binding.assessment.observableEvidenceId !== assessment.observableEvidenceId
    || binding.assessment.primaryTargetClassification !== assessment.primaryTargetClassification
    || binding.assessment.approvedTargetRef !== tutorialPackage.objectiveRef
    || binding.assessment.evidenceTargetRef !== tutorialPackage.evidenceTargetRef
    || binding.objectiveRef !== tutorialPackage.objectiveRef
    || binding.successCriteriaRef !== tutorialPackage.successCriteriaRef
    || binding.evidenceTargetRef !== tutorialPackage.evidenceTargetRef
    || binding.sourceFingerprint !== tutorialPackage.sourceFingerprint
  );
  if (assessmentMismatch) findings.push('assessment-reference-missing-or-stale');

  const modelingMismatch = bindings.some((binding) => {
    const step = packageSteps.get(binding.reviewStepId);
    return !step
      || !binding.modelingHandoffRef.trim()
      || binding.modelingHandoffRef !== tutorialPackage.sourceHandoffRef
      || !binding.modelingMomentRef.trim()
      || binding.visualRoleRef !== step.visualRoleRef
      || binding.fulfillmentDisposition !== step.disposition
      || (binding.pathwayPlanRef ?? null) !== tutorialPackage.pathwayPlanRef;
  });
  if (modelingMismatch) findings.push('modeling-reference-missing-or-stale');

  if (findings.length > 0) return completeResult('blocked', findings, [], assessment);

  // Compacted/no-additional occurrences remain canonical bindings but cannot be
  // the sole proof of modeled support. Reused/resurfaced support remains valid.
  const active = bindings.filter((binding) => ACTIVE_DISPOSITIONS.has(binding.fulfillmentDisposition));
  const classification = assessment.primaryTargetClassification;

  if (classification === 'procedural_skill' || classification === 'technical_workflow' || classification === 'performance') {
    const role = classification === 'performance' ? 'performance-model' : 'tool-or-procedure-execution';
    const covered = active.some((binding) => binding.coverageRoles.includes(role)
      && (classification === 'performance' || Boolean(binding.toolOrProcedureRef?.trim())));
    if (!covered) findings.push('execution-model-missing');
  } else if (classification === 'conceptual_understanding' || classification === 'judgment') {
    const required = classification === 'judgment'
      ? ['decision-reasoning'] as const
      : ['concept-explanation', 'relationship-reasoning'] as const;
    if (!hasAnyRole(active, required)) findings.push('concept-reasoning-model-missing');
  } else if (classification === 'critique') {
    if (!hasAnyRole(active, ['criteria-and-evidence-use'])) findings.push('criteria-use-model-missing');
  } else if (classification === 'revision') {
    const required: readonly TutorialCoverageRole[] = [
      'revision-prior-state',
      'revision-feedback-or-evidence',
      'revision-change',
      'revision-revised-state',
    ];
    if (!required.every((role) => hasAnyRole(active, [role]))) findings.push('revision-cycle-model-missing');
  } else if (classification === 'creative_production') {
    if (!hasAnyRole(active, ['creator-choice-and-rationale'])) findings.push('creator-decision-model-missing');
  } else if (!hasAnyRole(active, ['recall-or-definition', 'concept-explanation', 'relationship-reasoning', 'decision-reasoning', 'tool-or-procedure-execution', 'criteria-and-evidence-use', 'creator-choice-and-rationale', 'performance-model'])) {
    findings.push('coverage-unproven');
  }

  if (findings.length > 0) return completeResult('blocked', findings, [], assessment);
  return completeResult('valid', ['coverage-complete'], active.map((binding) => binding.reviewStepId), assessment);
}
