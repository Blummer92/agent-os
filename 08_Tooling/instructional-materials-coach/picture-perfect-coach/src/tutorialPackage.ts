import type { PromptAuthoringInput, PromptCardModel } from './promptIntent';
import { projectReviewedTutorialToPromptCards } from './promptIntent';
import type { CaptureEvidenceBundle } from './captureEvidence';
import type { VisualReferenceLibrary } from './visualReference';
import type { ReviewedTutorialProjection } from './types';

export type TutorialFulfillmentDisposition =
  | 'new-visual'
  | 'reuse-existing-visual'
  | 'resurface-prior-visual'
  | 'no-additional-visual-needed'
  | 'pathway-compacted';

export type RoutedTutorialStep = Readonly<{
  reviewStepId: string;
  visualRoleRef: string;
  disposition: TutorialFulfillmentDisposition;
  authoring?: PromptAuthoringInput;
  approvedAssetRef?: string;
  reasonRef?: string;
}>;

export type RoutedTutorialNeed = Readonly<{
  routeId: string;
  representation: 'tutorial-process';
  sourceHandoffRef: string;
  sourceFingerprint: string;
  objectiveRef: string;
  successCriteriaRef: string;
  evidenceTargetRef: string;
  pathwayPlanRef?: string;
  steps: readonly RoutedTutorialStep[];
}>;

export type TutorialPackageBlocker =
  | 'route-missing'
  | 'route-not-tutorial-process'
  | 'route-source-missing'
  | 'step-disposition-missing'
  | 'step-disposition-duplicate'
  | 'step-not-retained'
  | 'new-visual-authoring-missing'
  | 'reuse-asset-missing'
  | 'resurface-asset-missing'
  | 'reason-evidence-missing';

export type TutorialPackage = Readonly<{
  packageVersion: 'picture-perfect-tutorial-package-v1';
  routeId: string;
  sourceHandoffRef: string;
  sourceFingerprint: string;
  recordingId: string;
  recordingSha256: string;
  objectiveRef: string;
  successCriteriaRef: string;
  evidenceTargetRef: string;
  pathwayPlanRef: string | null;
  steps: readonly RoutedTutorialStep[];
  cards: readonly PromptCardModel[];
  reusedAssetRefs: readonly string[];
  resurfacedAssetRefs: readonly string[];
  executionAuthorized: false;
  externalWriteAuthorized: false;
  productionAuthorized: false;
}>;

export type TutorialPackageResult = Readonly<{
  status: 'valid' | 'blocked';
  package: TutorialPackage | null;
  blockers: readonly TutorialPackageBlocker[];
}>;

function unique<T>(items: readonly T[]): T[] {
  return [...new Set(items)];
}

export function buildTutorialPackage(
  tutorial: ReviewedTutorialProjection,
  route: RoutedTutorialNeed | null,
  captureBundle: CaptureEvidenceBundle | null = null,
  visualReferenceLibrary: VisualReferenceLibrary | null = null,
): TutorialPackageResult {
  if (!route) return { status: 'blocked', package: null, blockers: ['route-missing'] };
  if (route.representation !== 'tutorial-process') {
    return { status: 'blocked', package: null, blockers: ['route-not-tutorial-process'] };
  }
  if (!route.routeId.trim() || !route.sourceHandoffRef.trim() || !route.sourceFingerprint.trim()
    || !route.objectiveRef.trim() || !route.successCriteriaRef.trim() || !route.evidenceTargetRef.trim()) {
    return { status: 'blocked', package: null, blockers: ['route-source-missing'] };
  }

  const retained = new Set(tutorial.retained_steps.map((step) => step.review_step_id));
  const routeIds = route.steps.map((step) => step.reviewStepId);
  const blockers: TutorialPackageBlocker[] = [];

  for (const reviewStepId of retained) {
    const matches = route.steps.filter((step) => step.reviewStepId === reviewStepId);
    if (matches.length === 0) blockers.push('step-disposition-missing');
    if (matches.length > 1) blockers.push('step-disposition-duplicate');
  }
  if (routeIds.some((id) => !retained.has(id))) blockers.push('step-not-retained');

  for (const step of route.steps) {
    if (!step.visualRoleRef.trim()) blockers.push('route-source-missing');
    if (step.disposition === 'new-visual' && !step.authoring) blockers.push('new-visual-authoring-missing');
    if (step.disposition === 'reuse-existing-visual' && !step.approvedAssetRef?.trim()) blockers.push('reuse-asset-missing');
    if (step.disposition === 'resurface-prior-visual' && !step.approvedAssetRef?.trim()) blockers.push('resurface-asset-missing');
    if ((step.disposition === 'no-additional-visual-needed' || step.disposition === 'pathway-compacted') && !step.reasonRef?.trim()) {
      blockers.push('reason-evidence-missing');
    }
  }

  if (blockers.length > 0) return { status: 'blocked', package: null, blockers: unique(blockers) };

  const authoring = new Map<string, PromptAuthoringInput>();
  for (const step of route.steps) {
    if (step.disposition === 'new-visual' && step.authoring) authoring.set(step.reviewStepId, step.authoring);
  }
  const projectedCards = projectReviewedTutorialToPromptCards(tutorial, authoring, captureBundle, visualReferenceLibrary);
  const expectedNewVisuals = route.steps.filter((step) => step.disposition === 'new-visual').length;
  if (projectedCards.length !== expectedNewVisuals) {
    return { status: 'blocked', package: null, blockers: ['new-visual-authoring-missing'] };
  }
  const cards = projectedCards.map((card) => ({
    ...card,
    provenance: [`Teacher Modeling: ${route.sourceHandoffRef}`, `tutorial_route:${route.routeId}`, `tutorial_route_fingerprint:${route.sourceFingerprint}`, ...card.provenance],
  }));

  return {
    status: 'valid',
    blockers: [],
    package: Object.freeze({
      packageVersion: 'picture-perfect-tutorial-package-v1',
      routeId: route.routeId,
      sourceHandoffRef: route.sourceHandoffRef,
      sourceFingerprint: route.sourceFingerprint,
      recordingId: tutorial.recording_id,
      recordingSha256: tutorial.recording_sha256,
      objectiveRef: route.objectiveRef,
      successCriteriaRef: route.successCriteriaRef,
      evidenceTargetRef: route.evidenceTargetRef,
      pathwayPlanRef: route.pathwayPlanRef ?? null,
      steps: route.steps,
      cards,
      reusedAssetRefs: route.steps.filter((step) => step.disposition === 'reuse-existing-visual').map((step) => step.approvedAssetRef!),
      resurfacedAssetRefs: route.steps.filter((step) => step.disposition === 'resurface-prior-visual').map((step) => step.approvedAssetRef!),
      executionAuthorized: false,
      externalWriteAuthorized: false,
      productionAuthorized: false,
    }),
  };
}
