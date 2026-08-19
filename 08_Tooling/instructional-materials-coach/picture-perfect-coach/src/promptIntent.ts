import type { ReviewedStepProjection, ReviewedTutorialProjection } from './types';

export type ImageState = 'action' | 'result' | 'action+result';

export type VisualSpecification = {
  stepNumber: number;
  imagePurpose: string;
  imageState: ImageState;
  application: string;
  applicationContext: string;
  targetState: string;
  mustShow: readonly string[];
  mustNotShow: readonly string[];
  annotationSpace: string;
  provenance: readonly string[];
  evidenceSupportedUiDetails: readonly string[];
  requestedUiDetails: readonly string[];
  uncertainty?: string;
};

export type PromptCardModel = VisualSpecification & {
  portablePrompt: string;
  status: 'ready' | 'blocked';
  blocker?: string;
};

const KNOWN_WRONG_APPS = ['Canva', 'Figma', 'Photoshop'];
const PROVIDER_SPECIFIC_MARKERS = ['Midjourney', 'Gemini', 'Adobe Firefly', 'ChatGPT image generation', '--ar ', '--stylize '];

export function validateVisualSpecification(spec: VisualSpecification): string[] {
  const errors: string[] = [];
  if (!spec.application.trim()) errors.push('application identity is required');
  if (!spec.applicationContext.trim()) errors.push('recognizable application context is required');
  if (!spec.targetState.trim()) errors.push('target state is required');
  if (spec.mustShow.length === 0) errors.push('must-show evidence is required');
  if (spec.provenance.length === 0) errors.push('approved provenance is required');

  const supported = new Set(spec.evidenceSupportedUiDetails);
  for (const detail of spec.requestedUiDetails) {
    if (!supported.has(detail)) errors.push(`unsupported UI detail: ${detail}`);
  }
  return errors;
}

export function buildPortablePrompt(spec: VisualSpecification): PromptCardModel {
  const errors = validateVisualSpecification(spec);
  if (errors.length > 0) {
    return { ...spec, portablePrompt: '', status: 'blocked', blocker: errors.join('; ') };
  }

  const prompt = [
    `Create an instructional visual of the ${spec.application} interface.`,
    `Application fidelity requirement: visibly and unmistakably depict ${spec.application}; do not substitute a generic creative application or another product.`,
    `Purpose: ${spec.imagePurpose}`,
    `Image state: ${spec.imageState}.`,
    `Application context: ${spec.applicationContext}`,
    `Target state: ${spec.targetState}`,
    `Must show: ${spec.mustShow.join('; ')}.`,
    spec.mustNotShow.length ? `Must not show: ${spec.mustNotShow.join('; ')}.` : '',
    `Leave annotation space: ${spec.annotationSpace}.`,
    `Use only these evidence-supported UI details: ${spec.evidenceSupportedUiDetails.join('; ')}.`,
    `Do not invent controls, labels, locations, states, or workflow steps that are not listed as evidence-supported.`,
  ].filter(Boolean).join(' ');

  return { ...spec, portablePrompt: prompt, status: 'ready' };
}

export function validateApplicationFidelity(card: PromptCardModel): string[] {
  if (card.status === 'blocked') return [card.blocker ?? 'prompt is blocked'];
  const errors: string[] = [];
  if (!card.portablePrompt.includes(card.application)) errors.push('portable prompt lost modeled application identity');
  if (!card.portablePrompt.includes(`${card.application} interface`)) errors.push('portable prompt lost software-interface requirement');
  for (const wrongApp of KNOWN_WRONG_APPS) {
    if (wrongApp !== card.application && card.portablePrompt.includes(`depict ${wrongApp}`)) {
      errors.push(`portable prompt substituted wrong application: ${wrongApp}`);
    }
  }
  if (!card.portablePrompt.includes(card.applicationContext)) errors.push('portable prompt lost application context');
  if (!card.portablePrompt.includes(card.targetState)) errors.push('portable prompt lost target state');
  for (const item of card.mustShow) {
    if (!card.portablePrompt.includes(item)) errors.push(`portable prompt lost must-show evidence: ${item}`);
  }
  for (const marker of PROVIDER_SPECIFIC_MARKERS) {
    if (card.portablePrompt.includes(marker)) errors.push(`canonical prompt contains provider-specific syntax: ${marker}`);
  }
  return errors;
}

/**
 * Teacher/approved image-framing content for one reviewed step. This is authoring
 * content (what to show, why, and where) that Recorder/Teacher Modeling evidence
 * does not itself supply. It never carries or overrides application identity —
 * that comes only from the reviewed step's approved `modeled_application`.
 */
export type PromptAuthoringInput = {
  imagePurpose: string;
  imageState: ImageState;
  applicationContext: string;
  targetState: string;
  mustShow: readonly string[];
  mustNotShow: readonly string[];
  annotationSpace: string;
  evidenceSupportedUiDetails: readonly string[];
  requestedUiDetails: readonly string[];
  uncertainty?: string;
};

/**
 * Projects one Stage-3 reviewed step (ReviewedStepProjection, from the merged
 * PPUX-B review boundary) plus its approved authoring content into a bounded
 * Stage-4 VisualSpecification. Application identity is taken only from
 * `step.modeled_application` (approved evidence) — never inferred from step
 * title/student_action text, branding, or the tutorial name. A missing
 * `modeled_application` blocks the resulting prompt card.
 */
export function projectReviewedStepToVisualSpecification(
  step: ReviewedStepProjection,
  authoring: PromptAuthoringInput,
): VisualSpecification {
  const provenance = [
    `recording:${step.recording_id}`,
    `recording_sha256:${step.recording_sha256}`,
    ...step.source_step_ids.map((id) => `source_step:${id}`),
    ...step.semantic_action_ids.map((id) => `semantic_action:${id}`),
  ];
  return {
    stepNumber: step.sequence,
    imagePurpose: authoring.imagePurpose,
    imageState: authoring.imageState,
    application: step.modeled_application ?? '',
    applicationContext: authoring.applicationContext,
    targetState: authoring.targetState,
    mustShow: authoring.mustShow,
    mustNotShow: authoring.mustNotShow,
    annotationSpace: authoring.annotationSpace,
    provenance,
    evidenceSupportedUiDetails: authoring.evidenceSupportedUiDetails,
    requestedUiDetails: authoring.requestedUiDetails,
    uncertainty: authoring.uncertainty,
  };
}

/**
 * Projects an approved ReviewedTutorialProjection into Stage-4 prompt cards.
 * `authoringByStepId` supplies image-framing content keyed by `review_step_id`;
 * a reviewed step with no matching authoring entry is skipped (not invented).
 * `execution_authorized` on the source tutorial and every reviewed step must
 * remain false — this function never authorizes execution and does not read
 * or propagate any execution-authorization flag into the resulting cards.
 */
export function projectReviewedTutorialToPromptCards(
  tutorial: ReviewedTutorialProjection,
  authoringByStepId: ReadonlyMap<string, PromptAuthoringInput>,
): PromptCardModel[] {
  const cards: PromptCardModel[] = [];
  for (const step of tutorial.retained_steps) {
    const authoring = authoringByStepId.get(step.review_step_id);
    if (!authoring) continue;
    cards.push(buildPortablePrompt(projectReviewedStepToVisualSpecification(step, authoring)));
  }
  return cards;
}

export function assertProviderAdapterPreservesIntent(source: PromptCardModel, adaptedPrompt: string): string[] {
  if (source.status === 'blocked') return ['blocked intent cannot be adapted'];
  const errors: string[] = [];
  if (!adaptedPrompt.includes(source.application)) errors.push('provider adapter removed application identity');
  if (!adaptedPrompt.includes(source.targetState)) errors.push('provider adapter removed target state');
  for (const item of source.mustShow) {
    if (!adaptedPrompt.includes(item)) errors.push(`provider adapter removed must-show evidence: ${item}`);
  }
  return errors;
}
