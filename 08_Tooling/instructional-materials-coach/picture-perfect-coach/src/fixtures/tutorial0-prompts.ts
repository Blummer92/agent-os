import tutorial0Evidence from './tutorial0-evidence.json';
import tutorial0Recording from './tutorial0-recording.json';
import { tutorial0SyntheticCapture } from './tutorial0-capture';
import { tutorial0CurrentVisualReferences } from './tutorial0-visual-references';
import { deriveReviewedTutorial } from '../review';
import { deriveRecordingUiEvidence } from '../uiEvidence';
import { projectReviewedTutorialToPromptCards, type PromptAuthoringInput } from '../promptIntent';
import type { PromptCardModel } from '../promptIntent';
import type { ReviewDecision, UploadEvidenceProjection } from '../types';

const projected = tutorial0Evidence as unknown as Omit<UploadEvidenceProjection, 'recording_evidence'>;

const evidence: UploadEvidenceProjection = {
  ...projected,
  recording_evidence: deriveRecordingUiEvidence(tutorial0Recording, projected.recording_sha256),
};

const decisions: ReviewDecision[] = [
  { step_id: 'tutorial0-step-01-organize-location', choice: 'keep' },
  { step_id: 'tutorial0-step-02-open-tutorial-location', choice: 'combine-with-previous' },
  { step_id: 'tutorial0-step-03-square-file', choice: 'keep' },
  { step_id: 'tutorial0-step-04-reference-image', choice: 'keep' },
  { step_id: 'tutorial0-step-05-landscape-file', choice: 'keep' },
  { step_id: 'tutorial0-step-06-portrait-file', choice: 'keep' },
  { step_id: 'tutorial0-step-07-verify-location', choice: 'keep' },
  { step_id: 'tutorial0-step-08-incidental-shift', choice: 'not-instructional' },
];

const reviewResult = deriveReviewedTutorial(evidence, decisions);
if (!reviewResult.ok) {
  throw new Error(`Tutorial 0 fixture review decisions are invalid: ${reviewResult.reason}`);
}

export const tutorial0ReviewedTutorial = reviewResult.tutorial;

const commonMustNotShow = ['student data', 'private account information', 'DevTools', 'Recorder controls', 'invented Adobe controls'];
const commonProvenance = ['Teacher Modeling: Tutorial 0', 'Recorder evidence: approved modeled actions'];

const authoringByStepId = new Map<string, PromptAuthoringInput>([
  [
    'tutorial0-step-01-organize-location',
    {
      imagePurpose: 'Show the organized destination before collecting reference imagery.',
      imageState: 'result',
      applicationContext: 'Adobe Express Your stuff workspace and location context',
      targetState: 'Tutorial 0 - Organize My Files location is visibly organized under Digital Media',
      mustShow: ['Adobe Express', 'Your stuff', 'Digital Media', 'Tutorial 0 - Organize My Files'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'beside the visible location indicator for one teacher-added callout',
      requestedUiDetails: ['Your stuff', 'Digital Media', 'Tutorial 0 - Organize My Files'],
      currentVisualReference: {
        applicationVariant: 'Education',
        contextState: 'navigation/your-stuff/files',
        requiredUiClaims: ['Your stuff', 'Files', 'Digital Media'],
        reconciledRecordedUiClaims: ['Your stuff', 'Files', 'Digital Media'],
      },
    },
  ],
  [
    'tutorial0-step-03-square-file',
    {
      imagePurpose: 'Show where a student starts a new reference file.',
      imageState: 'action',
      applicationContext: 'Adobe Express workspace with enough surrounding navigation for orientation',
      targetState: 'Create file is the clear next action from the Create menu',
      mustShow: ['Adobe Express', 'Create', 'Create file'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'around Create and Create file for an arrow and step number',
      requestedUiDetails: ['Create new'],
      currentVisualReference: {
        applicationVariant: 'Education',
        contextState: 'navigation/create-menu',
        requiredUiClaims: ['Create', 'Create file'],
      },
    },
  ],
  [
    'tutorial0-step-05-landscape-file',
    {
      imagePurpose: 'Help students recognize the landscape canvas choice during file creation.',
      imageState: 'action+result',
      applicationContext: 'Adobe Express new-file creation context',
      targetState: 'the Landscape 16:9 choice is visible and distinguishable',
      mustShow: ['Adobe Express', 'Landscape', '16:9'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'near the format choice for a short teacher-added label',
      requestedUiDetails: ['Landscape'],
      currentVisualReference: {
        applicationVariant: 'Education',
        contextState: 'creation/get-started',
        requiredUiClaims: ['Landscape', '16:9'],
        reconciledRecordedUiClaims: ['Landscape', '16:9'],
      },
    },
  ],
]);

function withCommonProvenance(cards: readonly PromptCardModel[]): readonly PromptCardModel[] {
  return cards.map((card) => ({ ...card, provenance: [...commonProvenance, ...card.provenance] }));
}

/** F1 regression projection: no capture or current-reference library is supplied. */
export const tutorial0PromptCards: readonly PromptCardModel[] = withCommonProvenance(
  projectReviewedTutorialToPromptCards(tutorial0ReviewedTutorial, authoringByStepId),
);

/** F2 regression projection: historical capture evidence remains independently testable. */
export const tutorial0CapturedPromptCards: readonly PromptCardModel[] = withCommonProvenance(
  projectReviewedTutorialToPromptCards(
    tutorial0ReviewedTutorial,
    authoringByStepId,
    tutorial0SyntheticCapture,
  ),
);

/**
 * Canonical VRL2 projection. Current approved application-state references are
 * selected before prompt generation while F2 capture evidence remains bound as
 * historical action/state authority.
 */
export const tutorial0CurrentReferencePromptCards: readonly PromptCardModel[] = withCommonProvenance(
  projectReviewedTutorialToPromptCards(
    tutorial0ReviewedTutorial,
    authoringByStepId,
    tutorial0SyntheticCapture,
    tutorial0CurrentVisualReferences,
  ),
);

/** Explicitly reconciled Create fixture; historical capture remains unchanged. */
const reconciledCreateAuthoring = new Map<string, PromptAuthoringInput>([
  [
    'tutorial0-step-03-square-file',
    {
      ...authoringByStepId.get('tutorial0-step-03-square-file')!,
      currentVisualReference: {
        applicationVariant: 'Education',
        contextState: 'navigation/create-menu',
        requiredUiClaims: ['Create', 'Create file'],
        reconciledRecordedUiClaims: ['Create', 'Create file'],
      },
    },
  ],
]);

export const tutorial0ReconciledCreatePromptCard: PromptCardModel = projectReviewedTutorialToPromptCards(
  tutorial0ReviewedTutorial,
  reconciledCreateAuthoring,
  tutorial0SyntheticCapture,
  tutorial0CurrentVisualReferences,
)[0];

const blockedAuthoring = new Map<string, PromptAuthoringInput>([
  [
    'tutorial0-step-07-verify-location',
    {
      imagePurpose: 'Show the completed favorite-food reference setup.',
      imageState: 'result',
      applicationContext: 'Adobe Express final organized reference location',
      targetState: 'favorite-food reference files are organized in the intended Tutorial 0 location',
      mustShow: ['Adobe Express', 'Tutorial 0 - Organize My Files'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'beside the final location for a Check your location callout',
      requestedUiDetails: ['Tutorial 0 - Organize My Files', 'exact favorite-food filenames'],
      uncertainty: 'Exact favorite-food filenames and final file arrangement are not established by approved evidence.',
    },
  ],
]);

export const tutorial0BlockedFinalState: PromptCardModel = projectReviewedTutorialToPromptCards(
  tutorial0ReviewedTutorial,
  blockedAuthoring,
  tutorial0SyntheticCapture,
  tutorial0CurrentVisualReferences,
)[0];
