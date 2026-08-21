import tutorial0Evidence from './tutorial0-evidence.json';
import tutorial0Recording from './tutorial0-recording.json';
import { deriveReviewedTutorial } from '../review';
import { deriveRecordingUiEvidence } from '../uiEvidence';
import { projectReviewedTutorialToPromptCards, type PromptAuthoringInput } from '../promptIntent';
import type { PromptCardModel } from '../promptIntent';
import type { ReviewDecision, UploadEvidenceProjection } from '../types';

const projected = tutorial0Evidence as unknown as Omit<UploadEvidenceProjection, 'recording_evidence'>;

// UI-claim evidence is derived from the approved recording, exactly as the upload
// boundary derives it. The recording is source evidence and is never edited to make
// authored prompt content validate.
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

// Authoring content (what to show, why) supplied by approved Teacher Modeling review.
// Authoring can no longer declare which UI details evidence supports — that is derived
// from the recording and narrowed to each frame's own source indexes.
//
// UI text below is corrected against the recording (PPUX-F1 / #1293):
//   - the tutorial folder is `Tutorial 0 - Organize My Files` (recording index 9),
//     not `Tutorial 0 - My Favorite Food`, which the recording never contains;
//   - the recorded accessible name is `Create new` (index 13), not `Create new file`;
//   - `Square` (index 14) and `Portrait` (index 26) belong to other steps, so the
//     landscape frame claims only `Landscape` (index 20).
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
    },
  ],
  [
    'tutorial0-step-03-square-file',
    {
      imagePurpose: 'Show where a student starts a new reference file.',
      imageState: 'action',
      applicationContext: 'Adobe Express workspace with enough surrounding navigation for orientation',
      targetState: 'Create new is the clear next action',
      mustShow: ['Adobe Express', 'Create new'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'around Create new for an arrow and step number',
      requestedUiDetails: ['Create new'],
    },
  ],
  [
    'tutorial0-step-05-landscape-file',
    {
      imagePurpose: 'Help students recognize the landscape canvas choice during file creation.',
      imageState: 'action+result',
      applicationContext: 'Adobe Express new-file creation context',
      targetState: 'the Landscape choice is visible and distinguishable',
      mustShow: ['Adobe Express', 'Landscape'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'near the format choice for a short teacher-added label',
      requestedUiDetails: ['Landscape'],
    },
  ],
]);

export const tutorial0PromptCards: readonly PromptCardModel[] = projectReviewedTutorialToPromptCards(
  tutorial0ReviewedTutorial,
  authoringByStepId,
).map((card) => ({ ...card, provenance: [...commonProvenance, ...card.provenance] }));

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
)[0];
