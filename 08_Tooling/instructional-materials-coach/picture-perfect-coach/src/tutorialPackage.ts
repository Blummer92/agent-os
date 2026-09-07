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
  visualArtifactIdentity?: string;
  crossContextExemplarEvidenceRef?: string;
  instructionalSpecificityEvidenceRefs?: readonly string[];
}>;

export type RoutedTutorialNeed = Readonly<{
  routeId: string;
  representation: 'tutorial-process';
  sourceHandoffRef: string;
  sourceFingerprint: string;
  objectiveRef: string;
  successCriteriaRef: string;
  evidenceTargetRef: string;
  canonicalArtifactIdentity?: string;
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
  | 'reason-evidence-missing'
  | 'artifact-identity-missing'
  | 'artifact-identity-mismatch'
  | 'cross-context-exemplar-evidence-missing'
  | 'unsupported-instructional-specificity';

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
  canonicalArtifactIdentity: string | null;
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

const EXACT_INSTRUCTIONAL_DETAIL = /\b\d+(?:\.\d+)?\s*(?:pt|px|pixels?|points?|rem|em|%|mm|cm|inches?)\b/i;

function authoredInstructionText(authoring: PromptAuthoringInput): string {
  return [
    authoring.imagePurpose,
    authoring.targetState,
    ...authoring.mustShow,
    ...authoring.mustNotShow,
    authoring.annotationSpace,
  ].join(' ');
}

function artifactDirective(canonicalArtifactIdentity: string, exemplarIdentity: string | null): string {
  const base = `Canonical task/artifact identity: ${canonicalArtifactIdentity}. Preserve this identity; do not substitute another assessed artifact.`;
  return exemplarIdentity && exemplarIdentity !== canonicalArtifactIdentity
    ? `${base} Cross-context exemplar: ${exemplarIdentity}; treat it as illustrative only and do not replace the canonical task/artifact identity.`
    : base;
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
  const canonicalArtifactIdentity = route.canonicalArtifactIdentity?.trim() || null;

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

    if (step.disposition === 'new-visual' && canonicalArtifactIdentity) {
      const visualArtifactIdentity = step.visualArtifactIdentity?.trim();
      if (!visualArtifactIdentity) blockers.push('artifact-identity-missing');
      else if (visualArtifactIdentity !== canonicalArtifactIdentity && !step.crossContextExemplarEvidenceRef?.trim()) {
        blockers.push('artifact-identity-mismatch');
        blockers.push('cross-context-exemplar-evidence-missing');
      }
    }

    if (step.disposition === 'new-visual' && step.authoring && !step.authoring.screenFidelityRequired) {
      const hasExactInstructionalDetail = EXACT_INSTRUCTIONAL_DETAIL.test(authoredInstructionText(step.authoring));
      const hasOwnerEvidence = (step.instructionalSpecificityEvidenceRefs ?? []).some((ref) => ref.trim().length > 0);
      if (hasExactInstructionalDetail && !hasOwnerEvidence) blockers.push('unsupported-instructional-specificity');
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
  let cardIndex = 0;
  const cards = projectedCards.map((card) => {
    const step = route.steps.filter((item) => item.disposition === 'new-visual')[cardIndex++];
    const visualArtifactIdentity = step.visualArtifactIdentity?.trim() || canonicalArtifactIdentity;
    const identityPrompt = canonicalArtifactIdentity && visualArtifactIdentity
      ? artifactDirective(canonicalArtifactIdentity, visualArtifactIdentity)
      : '';
    return {
      ...card,
      portablePrompt: card.status === 'ready' && identityPrompt
        ? `${identityPrompt} ${card.portablePrompt}`
        : card.portablePrompt,
      provenance: [
        `Teacher Modeling: ${route.sourceHandoffRef}`,
        `tutorial_route:${route.routeId}`,
        `tutorial_route_fingerprint:${route.sourceFingerprint}`,
        ...(canonicalArtifactIdentity ? [`canonical_artifact:${canonicalArtifactIdentity}`] : []),
        ...(visualArtifactIdentity && visualArtifactIdentity !== canonicalArtifactIdentity
          ? [`cross_context_exemplar:${visualArtifactIdentity}`, `cross_context_exemplar_evidence:${step.crossContextExemplarEvidenceRef}`]
          : []),
        ...(step.instructionalSpecificityEvidenceRefs ?? []).map((ref) => `instructional_specificity_evidence:${ref}`),
        ...card.provenance,
      ],
    };
  });

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
      canonicalArtifactIdentity,
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
