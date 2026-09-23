import type { TutorialPackage, TutorialFulfillmentDisposition } from './tutorialPackage';
import {
  validateTutorialCoverage,
  type AssessmentTargetClassification,
  type TutorialCoverageBinding,
  type TutorialCoverageRole,
} from './tutorialCoverage';

export type EvidenceDisposition =
  | 'direct-evidence'
  | 'partial-evidence'
  | 'context-evidence'
  | 'not-comparable'
  | 'uncertain';

export type EvidenceDimension =
  | 'objective'
  | 'prerequisite'
  | 'success-criteria'
  | 'depth'
  | 'performance-format'
  | 'tool-or-routine'
  | 'representation'
  | 'work-mode';

export type EvidenceDimensionResult = Readonly<{
  dimension: EvidenceDimension;
  evidenceKind: 'academic' | 'context';
  matchedRefs: readonly string[];
  disposition: EvidenceDisposition;
}>;

/** Thin consumer projection of finalized EIA3 output; not a competing EIA schema. */
export type TeacherReviewedEvidenceSummary = Readonly<{
  recordId: string;
  recordRevision: number;
  fingerprint: string;
  sourceRef: string;
  sourceType: 'teacher-summary' | 'structured-artifact-summary';
  privacyEligible: boolean;
  freshness: 'current' | 'stale' | 'unknown';
  measurementQuality: 'sufficient' | 'limited' | 'unknown';
  overallDisposition: EvidenceDisposition;
  dimensionResults: readonly EvidenceDimensionResult[];
  whatSupported: readonly string[];
  whatRemainsUnmeasured: readonly string[];
  confidence: 'high' | 'medium' | 'low';
  manualReviewRequired: boolean;
  contradictions: readonly string[];
  uncertainties: readonly string[];
  misconceptionRefs?: readonly string[];
  authority: Readonly<{
    gradingAuthorized: false;
    masteryAuthorized: false;
    readinessAuthorized: false;
    learnerClassificationAuthorized: false;
    placementAuthorized: false;
    routeAssignmentAuthorized: false;
    pacingExecutionAuthorized: false;
    productionAuthorized: false;
    publicationAuthorized: false;
    externalWriteAuthorized: false;
  }>;
}>;

export type TutorialAdaptationAction =
  | 'retain'
  | 'resurface'
  | 'add-worked-example'
  | 'add-concept-model'
  | 'add-tool-orientation'
  | 'add-comparison'
  | 'add-non-example'
  | 'add-criteria-use-model'
  | 'add-revision-cycle'
  | 'reduce-repetition'
  | 'change-representation'
  | 'route-to-teacher-modeling'
  | 'insufficient-evidence';

export type AdaptationDimension =
  | 'conceptual'
  | 'procedural-tool'
  | 'representational'
  | 'operational'
  | 'misconception'
  | 'uncertain';

export type AdaptationReviewOwner = 'instructional-materials-coach' | 'teacher-modeling-coach';

export type TutorialAdaptationRecommendation = Readonly<{
  recommendationId: string;
  sourceEvidenceRecordId: string;
  sourceEvidenceRevision: number;
  sourceEvidenceFingerprint: string;
  tutorialRouteId: string;
  tutorialSourceFingerprint: string;
  reviewStepId: string | null;
  objectiveRef: string;
  evidenceTargetRef: string;
  claimId: string | null;
  targetClassification: AssessmentTargetClassification | null;
  dimension: AdaptationDimension;
  evidenceDisposition: EvidenceDisposition;
  triggeringDimensions: readonly EvidenceDimension[];
  action: TutorialAdaptationAction;
  reasonCodes: readonly string[];
  mustRemainUnchanged: readonly string[];
  reviewOwner: AdaptationReviewOwner;
  applicationAuthorized: false;
  masteryAuthorized: false;
  gradingAuthorized: false;
  placementAuthorized: false;
  routeAssignmentAuthorized: false;
  readinessAuthorized: false;
  classroomUseAuthorized: false;
  productionAuthorized: false;
  externalWriteAuthorized: false;
}>;

export type AdaptationRequest = Readonly<{
  proposedAction?: 'reduce-repetition';
  reviewStepId?: string;
}>;

export type TutorialAdaptationResult = Readonly<{
  status: 'recommended' | 'insufficient-evidence' | 'blocked';
  recommendations: readonly TutorialAdaptationRecommendation[];
}>;

const ACTIVE_DISPOSITIONS = new Set<TutorialFulfillmentDisposition>([
  'new-visual',
  'reuse-existing-visual',
  'resurface-prior-visual',
]);

const ACADEMIC_DIMENSIONS = new Set<EvidenceDimension>([
  'objective', 'prerequisite', 'success-criteria', 'depth', 'performance-format',
]);

function sortedUnique<T extends string>(items: readonly T[]): T[] {
  return [...new Set(items)].sort();
}

function evidenceIsFinal(summary: TeacherReviewedEvidenceSummary): boolean {
  return Boolean(summary.recordId.trim())
    && Number.isInteger(summary.recordRevision)
    && summary.recordRevision > 0
    && Boolean(summary.fingerprint.trim())
    && summary.privacyEligible
    && summary.freshness === 'current'
    && summary.measurementQuality === 'sufficient'
    && !summary.manualReviewRequired
    && summary.contradictions.length === 0
    && summary.uncertainties.length === 0
    && summary.overallDisposition !== 'uncertain';
}

function activeBindings(bindings: readonly TutorialCoverageBinding[]): TutorialCoverageBinding[] {
  return bindings.filter((binding) => ACTIVE_DISPOSITIONS.has(binding.fulfillmentDisposition));
}

function dimensionsWith(
  summary: TeacherReviewedEvidenceSummary,
  disposition: EvidenceDisposition,
): EvidenceDimensionResult[] {
  return summary.dimensionResults.filter((result) => result.disposition === disposition);
}

function baseRecommendation(
  tutorialPackage: TutorialPackage,
  summary: TeacherReviewedEvidenceSummary,
  binding: TutorialCoverageBinding | null,
  index: number,
  action: TutorialAdaptationAction,
  dimension: AdaptationDimension,
  reasonCodes: readonly string[],
  triggeringDimensions: readonly EvidenceDimension[],
  reviewOwner: AdaptationReviewOwner = 'instructional-materials-coach',
): TutorialAdaptationRecommendation {
  return {
    recommendationId: `ppux-fb1:${summary.recordId}:${summary.recordRevision}:${index}`,
    sourceEvidenceRecordId: summary.recordId,
    sourceEvidenceRevision: summary.recordRevision,
    sourceEvidenceFingerprint: summary.fingerprint,
    tutorialRouteId: tutorialPackage.routeId,
    tutorialSourceFingerprint: tutorialPackage.sourceFingerprint,
    reviewStepId: binding?.reviewStepId ?? null,
    objectiveRef: tutorialPackage.objectiveRef,
    evidenceTargetRef: tutorialPackage.evidenceTargetRef,
    claimId: binding?.assessment.claimId ?? null,
    targetClassification: binding?.assessment.primaryTargetClassification ?? null,
    dimension,
    evidenceDisposition: summary.overallDisposition,
    triggeringDimensions: sortedUnique(triggeringDimensions),
    action,
    reasonCodes: sortedUnique(reasonCodes),
    mustRemainUnchanged: [
      `objective:${tutorialPackage.objectiveRef}`,
      `success-criteria:${tutorialPackage.successCriteriaRef}`,
      `evidence-target:${tutorialPackage.evidenceTargetRef}`,
      `modeling-handoff:${tutorialPackage.sourceHandoffRef}`,
      'canonical-modeled-sequence',
    ],
    reviewOwner,
    applicationAuthorized: false,
    masteryAuthorized: false,
    gradingAuthorized: false,
    placementAuthorized: false,
    routeAssignmentAuthorized: false,
    readinessAuthorized: false,
    classroomUseAuthorized: false,
    productionAuthorized: false,
    externalWriteAuthorized: false,
  };
}

function identityMismatch(
  tutorialPackage: TutorialPackage,
  bindings: readonly TutorialCoverageBinding[],
): boolean {
  return bindings.length === 0 || bindings.some((binding) =>
    !binding.current
    || binding.sourceFingerprint !== tutorialPackage.sourceFingerprint
    || binding.objectiveRef !== tutorialPackage.objectiveRef
    || binding.successCriteriaRef !== tutorialPackage.successCriteriaRef
    || binding.evidenceTargetRef !== tutorialPackage.evidenceTargetRef
    || binding.modelingHandoffRef !== tutorialPackage.sourceHandoffRef
    || !binding.assessment.current
    || binding.assessment.approvedTargetRef !== tutorialPackage.objectiveRef
    || binding.assessment.evidenceTargetRef !== tutorialPackage.evidenceTargetRef
  );
}

function rolesForClassification(classification: AssessmentTargetClassification): readonly TutorialCoverageRole[] {
  switch (classification) {
    case 'procedural_skill':
    case 'technical_workflow': return ['tool-or-procedure-execution'];
    case 'performance': return ['performance-model'];
    case 'conceptual_understanding': return ['concept-explanation', 'relationship-reasoning'];
    case 'judgment': return ['decision-reasoning'];
    case 'critique': return ['criteria-and-evidence-use'];
    case 'revision': return ['revision-prior-state', 'revision-feedback-or-evidence', 'revision-change', 'revision-revised-state'];
    case 'creative_production': return ['creator-choice-and-rationale'];
    default: return ['recall-or-definition'];
  }
}

function bindingForClassification(
  bindings: readonly TutorialCoverageBinding[],
  classification: AssessmentTargetClassification,
): TutorialCoverageBinding | null {
  const required = rolesForClassification(classification);
  return activeBindings(bindings).find((binding) => binding.coverageRoles.some((role) => required.includes(role))) ?? activeBindings(bindings)[0] ?? null;
}

function compactedPackage(
  tutorialPackage: TutorialPackage,
  reviewStepId: string,
): TutorialPackage | null {
  const target = tutorialPackage.steps.find((step) => step.reviewStepId === reviewStepId);
  if (!target) return null;
  const steps = tutorialPackage.steps.map((step) => step.reviewStepId === reviewStepId
    ? { ...step, disposition: 'pathway-compacted' as const, reasonRef: 'ppux-fb1:proposed-reduce-repetition' }
    : step);
  return { ...tutorialPackage, steps };
}

function compactedBindings(
  bindings: readonly TutorialCoverageBinding[],
  reviewStepId: string,
): TutorialCoverageBinding[] {
  return bindings.map((binding) => binding.reviewStepId === reviewStepId
    ? { ...binding, fulfillmentDisposition: 'pathway-compacted' as const }
    : binding);
}

/**
 * Convert finalized EIA3 class-level evidence into non-mutating PPUX support advice.
 * Evidence meaning stays with EIA; required instructional coverage stays with COV1.
 */
export function recommendTutorialAdaptations(
  tutorialPackage: TutorialPackage,
  bindings: readonly TutorialCoverageBinding[],
  summary: TeacherReviewedEvidenceSummary,
  request: AdaptationRequest = {},
): TutorialAdaptationResult {
  if (identityMismatch(tutorialPackage, bindings)) {
    return { status: 'blocked', recommendations: [baseRecommendation(
      tutorialPackage, summary, null, 0, 'insufficient-evidence', 'uncertain',
      ['coverage-identity-mismatch'], [],
    )] };
  }

  if (!evidenceIsFinal(summary)) {
    return { status: 'insufficient-evidence', recommendations: [baseRecommendation(
      tutorialPackage, summary, bindings[0] ?? null, 0, 'insufficient-evidence', 'uncertain',
      ['eia-evidence-not-final'], summary.dimensionResults.map((result) => result.dimension),
    )] };
  }

  if (request.proposedAction === 'reduce-repetition' && request.reviewStepId) {
    const candidatePackage = compactedPackage(tutorialPackage, request.reviewStepId);
    const candidateBindings = compactedBindings(bindings, request.reviewStepId);
    const binding = bindings.find((item) => item.reviewStepId === request.reviewStepId) ?? null;
    if (!candidatePackage || validateTutorialCoverage(candidatePackage, candidateBindings).status !== 'valid') {
      return { status: 'recommended', recommendations: [baseRecommendation(
        tutorialPackage, summary, binding, 0, 'retain', 'conceptual',
        ['cov1-preserve-sole-required-coverage'], [],
      )] };
    }
    return { status: 'recommended', recommendations: [baseRecommendation(
      tutorialPackage, summary, binding, 0, 'reduce-repetition', 'representational',
      ['cov1-coverage-preserved'], [],
    )] };
  }

  if (summary.overallDisposition === 'not-comparable') {
    return { status: 'insufficient-evidence', recommendations: [baseRecommendation(
      tutorialPackage, summary, bindings[0] ?? null, 0, 'insufficient-evidence', 'uncertain',
      ['eia-not-comparable'], summary.dimensionResults.map((result) => result.dimension),
    )] };
  }

  const classification = bindings[0]!.assessment.primaryTargetClassification;
  const binding = bindingForClassification(bindings, classification);
  const recommendations: TutorialAdaptationRecommendation[] = [];
  let index = 0;

  const academicDirect = summary.dimensionResults.filter((result) => ACADEMIC_DIMENSIONS.has(result.dimension) && result.disposition === 'direct-evidence');
  const academicGaps = summary.dimensionResults.filter((result) => ACADEMIC_DIMENSIONS.has(result.dimension) && result.disposition !== 'direct-evidence');
  const tool = summary.dimensionResults.find((result) => result.dimension === 'tool-or-routine');
  const representation = summary.dimensionResults.find((result) => result.dimension === 'representation');
  const workMode = summary.dimensionResults.find((result) => result.dimension === 'work-mode');

  if (academicDirect.length > 0 && (!tool || tool.disposition === 'not-comparable')) {
    recommendations.push(baseRecommendation(
      tutorialPackage, summary, binding, index++, binding?.fulfillmentDisposition === 'reuse-existing-visual' || binding?.fulfillmentDisposition === 'resurface-prior-visual'
        ? 'resurface' : 'add-tool-orientation',
      'procedural-tool', ['academic-evidence-supported', 'tool-or-routine-unmeasured'], ['tool-or-routine'],
    ));
  }

  if (tool?.disposition === 'context-evidence' && academicGaps.length > 0) {
    const action: TutorialAdaptationAction = classification === 'creative_production' || classification === 'judgment'
      ? 'add-comparison' : 'add-concept-model';
    recommendations.push(baseRecommendation(
      tutorialPackage, summary, binding, index++, action, 'conceptual',
      ['tool-context-does-not-prove-concept', 'academic-demand-unmeasured'], academicGaps.map((result) => result.dimension),
    ));
  }

  if (summary.overallDisposition === 'partial-evidence' && summary.whatRemainsUnmeasured.length > 0) {
    recommendations.push(baseRecommendation(
      tutorialPackage, summary, binding, index++, 'retain',
      classification === 'procedural_skill' || classification === 'technical_workflow' || classification === 'performance'
        ? 'procedural-tool' : 'conceptual',
      ['partial-evidence-preserve-unmeasured-support'], academicGaps.map((result) => result.dimension),
    ));
  }

  const misconception = bindings.find((item) => item.misconceptionRef && summary.misconceptionRefs?.includes(item.misconceptionRef));
  if (misconception) {
    const needsModeling = misconception.coverageRoles.includes('tool-or-procedure-execution')
      && (classification === 'procedural_skill' || classification === 'technical_workflow' || classification === 'performance');
    recommendations.push(baseRecommendation(
      tutorialPackage, summary, misconception, index++, needsModeling ? 'route-to-teacher-modeling' : 'add-non-example',
      'misconception', ['teacher-confirmed-misconception-mapped'], [], needsModeling ? 'teacher-modeling-coach' : 'instructional-materials-coach',
    ));
  }

  const operationalContext = [tool, representation, workMode].filter((result): result is EvidenceDimensionResult => Boolean(result));
  if (academicDirect.length === 0 && operationalContext.some((result) => result.disposition === 'context-evidence')) {
    const action: TutorialAdaptationAction = representation?.disposition === 'context-evidence'
      ? 'change-representation' : 'add-tool-orientation';
    recommendations.push(baseRecommendation(
      tutorialPackage, summary, binding, index++, action, 'operational',
      ['context-evidence-operational-only'], operationalContext.map((result) => result.dimension),
    ));
  }

  if (recommendations.length === 0) {
    recommendations.push(baseRecommendation(
      tutorialPackage, summary, binding, index, 'retain', 'conceptual',
      ['no-bounded-adaptation-supported'], dimensionsWith(summary, summary.overallDisposition).map((result) => result.dimension),
    ));
  }

  return { status: 'recommended', recommendations };
}
