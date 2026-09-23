import type { CaptureEvidenceBundle } from './captureEvidence';
import {
  buildTutorialPackage,
  type RoutedTutorialNeed,
  type TutorialPackage,
  type TutorialPackageBlocker,
} from './tutorialPackage';
import type { ReviewedTutorialProjection } from './types';
import type { VisualReferenceLibrary } from './visualReference';

export const PROMPT_PROJECTION_INPUT_VERSION = 'picture-perfect-prompt-projection-input-v1' as const;
export const PROMPT_PROJECTION_RESULT_VERSION = 'picture-perfect-prompt-projection-result-v1' as const;

export type PromptProjectionInput = Readonly<{
  formatVersion: typeof PROMPT_PROJECTION_INPUT_VERSION;
  tutorial: ReviewedTutorialProjection;
  route: RoutedTutorialNeed;
  captureBundle?: CaptureEvidenceBundle | null;
  visualReferenceLibrary?: VisualReferenceLibrary | null;
}>;

export type PromptProjectionInputBlocker =
  | 'invalid-input'
  | 'unsupported-input-version';

export type PromptProjectionBlocker = PromptProjectionInputBlocker | TutorialPackageBlocker;

export type PromptProjectionResult = Readonly<{
  formatVersion: typeof PROMPT_PROJECTION_RESULT_VERSION;
  status: 'valid' | 'blocked';
  routeId: string | null;
  sourceHandoffRef: string | null;
  sourceFingerprint: string | null;
  recordingId: string | null;
  recordingSha256: string | null;
  applications: readonly string[];
  tutorialPackage: TutorialPackage | null;
  blockers: readonly PromptProjectionBlocker[];
  executionAuthorized: false;
  externalWriteAuthorized: false;
  productionAuthorized: false;
}>;

const INPUT_KEYS = new Set([
  'formatVersion',
  'tutorial',
  'route',
  'captureBundle',
  'visualReferenceLibrary',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function stringField(value: unknown, field: string): string | null {
  if (!isRecord(value)) return null;
  const candidate = value[field];
  return typeof candidate === 'string' ? candidate : null;
}

function applicationsFromTutorial(value: unknown): readonly string[] {
  if (!isRecord(value) || !Array.isArray(value.retained_steps)) return [];
  const applications = value.retained_steps.flatMap((step) => {
    if (!isRecord(step)) return [];
    const application = step.modeled_application;
    return typeof application === 'string' && application.trim() ? [application.trim()] : [];
  });
  return [...new Set(applications)].sort((left, right) => left.localeCompare(right));
}

function blockedInputResult(value: unknown, blocker: PromptProjectionInputBlocker): PromptProjectionResult {
  const tutorial = isRecord(value) ? value.tutorial : null;
  const route = isRecord(value) ? value.route : null;
  return Object.freeze({
    formatVersion: PROMPT_PROJECTION_RESULT_VERSION,
    status: 'blocked',
    routeId: stringField(route, 'routeId'),
    sourceHandoffRef: stringField(route, 'sourceHandoffRef'),
    sourceFingerprint: stringField(route, 'sourceFingerprint'),
    recordingId: stringField(tutorial, 'recording_id'),
    recordingSha256: stringField(tutorial, 'recording_sha256'),
    applications: applicationsFromTutorial(tutorial),
    tutorialPackage: null,
    blockers: [blocker],
    executionAuthorized: false,
    externalWriteAuthorized: false,
    productionAuthorized: false,
  });
}

function parsePromptProjectionInput(value: unknown): PromptProjectionInput | PromptProjectionResult {
  if (!isRecord(value)) return blockedInputResult(value, 'invalid-input');
  if (Object.keys(value).some((key) => !INPUT_KEYS.has(key))) {
    return blockedInputResult(value, 'invalid-input');
  }
  if (value.formatVersion !== PROMPT_PROJECTION_INPUT_VERSION) {
    return blockedInputResult(value, 'unsupported-input-version');
  }
  if (!isRecord(value.tutorial) || !isRecord(value.route)) {
    return blockedInputResult(value, 'invalid-input');
  }
  if (
    typeof value.tutorial.recording_id !== 'string'
    || typeof value.tutorial.recording_sha256 !== 'string'
    || !Array.isArray(value.tutorial.retained_steps)
    || !Array.isArray(value.tutorial.excluded_step_ids)
    || !Array.isArray(value.tutorial.review_decisions)
    || !isRecord(value.tutorial.recording_evidence)
  ) {
    return blockedInputResult(value, 'invalid-input');
  }
  if (
    typeof value.route.routeId !== 'string'
    || value.route.representation !== 'tutorial-process'
    || typeof value.route.sourceHandoffRef !== 'string'
    || typeof value.route.sourceFingerprint !== 'string'
    || typeof value.route.objectiveRef !== 'string'
    || typeof value.route.successCriteriaRef !== 'string'
    || typeof value.route.evidenceTargetRef !== 'string'
    || !Array.isArray(value.route.steps)
  ) {
    return blockedInputResult(value, 'invalid-input');
  }
  if (value.captureBundle !== undefined && value.captureBundle !== null && !isRecord(value.captureBundle)) {
    return blockedInputResult(value, 'invalid-input');
  }
  if (
    value.visualReferenceLibrary !== undefined
    && value.visualReferenceLibrary !== null
    && !isRecord(value.visualReferenceLibrary)
  ) {
    return blockedInputResult(value, 'invalid-input');
  }
  return value as unknown as PromptProjectionInput;
}

/**
 * Deterministic, side-effect-free PPUX projection boundary for already-resolved
 * tutorial/handoff evidence. It delegates all tutorial-package and prompt-card
 * semantics to the existing Picture Perfect projection owners.
 */
export function projectTutorialPromptCards(value: unknown): PromptProjectionResult {
  const parsed = parsePromptProjectionInput(value);
  if ('formatVersion' in parsed && parsed.formatVersion === PROMPT_PROJECTION_RESULT_VERSION) {
    return parsed;
  }

  try {
    const result = buildTutorialPackage(
      parsed.tutorial,
      parsed.route,
      parsed.captureBundle ?? null,
      parsed.visualReferenceLibrary ?? null,
    );
    return Object.freeze({
      formatVersion: PROMPT_PROJECTION_RESULT_VERSION,
      status: result.status,
      routeId: parsed.route.routeId,
      sourceHandoffRef: parsed.route.sourceHandoffRef,
      sourceFingerprint: parsed.route.sourceFingerprint,
      recordingId: parsed.tutorial.recording_id,
      recordingSha256: parsed.tutorial.recording_sha256,
      applications: applicationsFromTutorial(parsed.tutorial),
      tutorialPackage: result.package,
      blockers: result.blockers,
      executionAuthorized: false,
      externalWriteAuthorized: false,
      productionAuthorized: false,
    });
  } catch {
    return blockedInputResult(parsed, 'invalid-input');
  }
}

export function serializePromptProjectionResult(result: PromptProjectionResult): string {
  return JSON.stringify(result);
}
