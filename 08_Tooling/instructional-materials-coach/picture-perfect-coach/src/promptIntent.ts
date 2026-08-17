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
  for (const wrongApp of KNOWN_WRONG_APPS) {
    if (wrongApp !== card.application && card.portablePrompt.includes(`depict ${wrongApp}`)) {
      errors.push(`portable prompt substituted wrong application: ${wrongApp}`);
    }
  }
  if (!card.portablePrompt.includes(card.applicationContext)) errors.push('portable prompt lost application context');
  return errors;
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
