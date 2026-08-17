import { buildPortablePrompt, type PromptCardModel, type VisualSpecification } from '../promptIntent';

const common = {
  application: 'Adobe Express',
  mustNotShow: ['student data', 'private account information', 'DevTools', 'Recorder controls', 'invented Adobe controls'],
  provenance: ['Teacher Modeling: Tutorial 0', 'Recorder evidence: approved modeled actions'],
} as const;

export const tutorial0VisualSpecifications: readonly VisualSpecification[] = [
  {
    ...common,
    stepNumber: 1,
    imagePurpose: 'Show the organized destination before collecting reference imagery.',
    imageState: 'result',
    applicationContext: 'Adobe Express Your stuff workspace and location context',
    targetState: 'Tutorial 0 - My Favorite Food location is visibly organized under Digital Media',
    mustShow: ['Adobe Express', 'Your stuff', 'Digital Media', 'Tutorial 0 - My Favorite Food'],
    annotationSpace: 'beside the visible location indicator for one teacher-added callout',
    evidenceSupportedUiDetails: ['Your stuff', 'Digital Media', 'Tutorial 0 - My Favorite Food'],
    requestedUiDetails: ['Your stuff', 'Digital Media', 'Tutorial 0 - My Favorite Food'],
  },
  {
    ...common,
    stepNumber: 2,
    imagePurpose: 'Show where a student starts a new reference file.',
    imageState: 'action',
    applicationContext: 'Adobe Express workspace with enough surrounding navigation for orientation',
    targetState: 'Create new file is the clear next action',
    mustShow: ['Adobe Express', 'Create new file'],
    annotationSpace: 'around Create new file for an arrow and step number',
    evidenceSupportedUiDetails: ['Create new file'],
    requestedUiDetails: ['Create new file'],
  },
  {
    ...common,
    stepNumber: 3,
    imagePurpose: 'Help students recognize the three modeled canvas choices during file creation.',
    imageState: 'action+result',
    applicationContext: 'Adobe Express new-file creation context',
    targetState: 'Square, Landscape, and Portrait choices are visible and distinguishable',
    mustShow: ['Adobe Express', 'Square', 'Landscape', 'Portrait'],
    annotationSpace: 'near each format choice for short teacher-added labels',
    evidenceSupportedUiDetails: ['Square', 'Landscape', 'Portrait'],
    requestedUiDetails: ['Square', 'Landscape', 'Portrait'],
  },
];

export const tutorial0PromptCards: readonly PromptCardModel[] = tutorial0VisualSpecifications.map(buildPortablePrompt);

export const tutorial0BlockedFinalState = buildPortablePrompt({
  ...common,
  stepNumber: 4,
  imagePurpose: 'Show the completed favorite-food reference setup.',
  imageState: 'result',
  applicationContext: 'Adobe Express final organized reference location',
  targetState: 'favorite-food reference files are organized in the intended Tutorial 0 location',
  mustShow: ['Adobe Express', 'Tutorial 0 - My Favorite Food'],
  annotationSpace: 'beside the final location for a Check your location callout',
  evidenceSupportedUiDetails: ['Tutorial 0 - My Favorite Food'],
  requestedUiDetails: ['Tutorial 0 - My Favorite Food', 'exact favorite-food filenames'],
  uncertainty: 'Exact favorite-food filenames and final file arrangement are not established by approved evidence.',
});
