import type {
  TeacherReviewedEvidenceSummary,
  TutorialAdaptationAction,
  TutorialAdaptationResult,
} from './tutorialAdaptation';
import type { TutorialFulfillmentDisposition } from './tutorialPackage';

export type InstructionalSupportNeed =
  | 'targeted-support-recommended'
  | 'diagnostic-support-recommended'
  | 'retain-current-coverage'
  | 'reuse-or-resurface-existing-support'
  | 'no-additional-visual-needed';

export type ProviderExecutionStatus =
  | 'not-attempted'
  | 'image-returned'
  | 'provider-unavailable'
  | 'modality-mismatch';

export type ProviderExecutionObservation = Readonly<{
  status: ProviderExecutionStatus;
  requestedModality: 'image';
  returnedModality: 'image' | 'text' | null;
  executionAuthorized: false;
  productionAuthorized: false;
  externalWriteAuthorized: false;
}>;

export type TutorialSupportOutcome = Readonly<{
  instructional: Readonly<{
    need: InstructionalSupportNeed;
    fulfillmentDisposition: TutorialFulfillmentDisposition;
    adaptationStatus: TutorialAdaptationResult['status'];
    adaptationActions: readonly TutorialAdaptationAction[];
  }>;
  execution: ProviderExecutionObservation;
  finalArtifactType: null;
  masteryAuthorized: false;
  gradingAuthorized: false;
  pathwayAuthorized: false;
  readinessAuthorized: false;
  productionAuthorized: false;
  externalWriteAuthorized: false;
}>;

const TARGETED_ACTIONS = new Set<TutorialAdaptationAction>([
  'add-worked-example',
  'add-concept-model',
  'add-tool-orientation',
  'add-comparison',
  'add-non-example',
  'add-criteria-use-model',
  'add-revision-cycle',
  'change-representation',
  'route-to-teacher-modeling',
]);

function instructionalNeed(
  adaptation: TutorialAdaptationResult,
  summary: TeacherReviewedEvidenceSummary,
  fulfillmentDisposition: TutorialFulfillmentDisposition,
): InstructionalSupportNeed {
  if (
    summary.contradictions.length > 0
    || summary.uncertainties.length > 0
    || summary.manualReviewRequired
    || summary.overallDisposition === 'uncertain'
  ) {
    return 'diagnostic-support-recommended';
  }
  if (adaptation.status === 'insufficient-evidence' || adaptation.status === 'blocked') {
    return 'retain-current-coverage';
  }
  const actions = adaptation.recommendations.map((recommendation) => recommendation.action);
  if (actions.some((action) => TARGETED_ACTIONS.has(action))) return 'targeted-support-recommended';
  if (fulfillmentDisposition === 'no-additional-visual-needed' || fulfillmentDisposition === 'pathway-compacted') {
    return 'no-additional-visual-needed';
  }
  if (fulfillmentDisposition === 'reuse-existing-visual' || fulfillmentDisposition === 'resurface-prior-visual') {
    return 'reuse-or-resurface-existing-support';
  }
  return 'retain-current-coverage';
}

export function observeProviderExecution(
  status: ProviderExecutionStatus,
  returnedModality: 'image' | 'text' | null,
): ProviderExecutionObservation {
  return Object.freeze({
    status,
    requestedModality: 'image',
    returnedModality,
    executionAuthorized: false,
    productionAuthorized: false,
    externalWriteAuthorized: false,
  });
}

/** Provider execution evidence is deliberately composed beside, never into, instructional truth. */
export function composeTutorialSupportOutcome(
  adaptation: TutorialAdaptationResult,
  summary: TeacherReviewedEvidenceSummary,
  fulfillmentDisposition: TutorialFulfillmentDisposition,
  execution: ProviderExecutionObservation = observeProviderExecution('not-attempted', null),
): TutorialSupportOutcome {
  return Object.freeze({
    instructional: Object.freeze({
      need: instructionalNeed(adaptation, summary, fulfillmentDisposition),
      fulfillmentDisposition,
      adaptationStatus: adaptation.status,
      adaptationActions: Object.freeze(adaptation.recommendations.map((recommendation) => recommendation.action)),
    }),
    execution,
    finalArtifactType: null,
    masteryAuthorized: false,
    gradingAuthorized: false,
    pathwayAuthorized: false,
    readinessAuthorized: false,
    productionAuthorized: false,
    externalWriteAuthorized: false,
  });
}
