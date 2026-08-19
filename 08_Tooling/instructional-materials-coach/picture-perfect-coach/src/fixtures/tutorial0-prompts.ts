import tutorial0Evidence from './tutorial0-evidence.json';
import { deriveReviewedTutorial } from '../review';
import { projectReviewedTutorialToPromptCards, type PromptAuthoringInput } from '../promptIntent';
import type { PromptCardModel } from '../promptIntent';
import type { ReviewDecision, UploadEvidenceProjection } from '../types';

const evidence = tutorial0Evidence as unknown as UploadEvidenceProjection;

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

// Authoring content (what to show, why) supplied by approved Teacher Modeling review — not
// derivable from Recorder evidence alone. Application identity itself is never authored here;
// it flows only from each reviewed step's `modeled_application`.
const authoringByStepId = new Map<string, PromptAuthoringInput>([
  [
    'tutorial0-step-01-organize-location',
    {
      imagePurpose: 'Show the organized destination before collecting reference imagery.',
      imageState: 'result',
      applicationContext: 'Adobe Express Your stuff workspace and location context',
      targetState: 'Tutorial 0 - My Favorite Food location is visibly organized under Digital Media',
      mustShow: ['Adobe Express', 'Your stuff', 'Digital Media', 'Tutorial 0 - My Favorite Food'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'beside the visible location indicator for one teacher-added callout',
      evidenceSupportedUiDetails: ['Your stuff', 'Digital Media', 'Tutorial 0 - My Favorite Food'],
      requestedUiDetails: ['Your stuff', 'Digital Media', 'Tutorial 0 - My Favorite Food'],
    },
  ],
  [
    'tutorial0-step-03-square-file',
    {
      imagePurpose: 'Show where a student starts a new reference file.',
      imageState: 'action',
      applicationContext: 'Adobe Express workspace with enough surrounding navigation for orientation',
      targetState: 'Create new file is the clear next action',
      mustShow: ['Adobe Express', 'Create new file'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'around Create new file for an arrow and step number',
      evidenceSupportedUiDetails: ['Create new file'],
      requestedUiDetails: ['Create new file'],
    },
  ],
  [
    'tutorial0-step-05-landscape-file',
    {
      imagePurpose: 'Help students recognize the three modeled canvas choices during file creation.',
      imageState: 'action+result',
      applicationContext: 'Adobe Express new-file creation context',
      targetState: 'Square, Landscape, and Portrait choices are visible and distinguishable',
      mustShow: ['Adobe Express', 'Square', 'Landscape', 'Portrait'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'near each format choice for short teacher-added labels',
      evidenceSupportedUiDetails: ['Square', 'Landscape', 'Portrait'],
      requestedUiDetails: ['Square', 'Landscape', 'Portrait'],
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
      mustShow: ['Adobe Express', 'Tutorial 0 - My Favorite Food'],
      mustNotShow: commonMustNotShow,
      annotationSpace: 'beside the final location for a Check your location callout',
      evidenceSupportedUiDetails: ['Tutorial 0 - My Favorite Food'],
      requestedUiDetails: ['Tutorial 0 - My Favorite Food', 'exact favorite-food filenames'],
      uncertainty: 'Exact favorite-food filenames and final file arrangement are not established by approved evidence.',
    },
  ],
]);

export const tutorial0BlockedFinalState: PromptCardModel = projectReviewedTutorialToPromptCards(
  tutorial0ReviewedTutorial,
  blockedAuthoring,
)[0];
