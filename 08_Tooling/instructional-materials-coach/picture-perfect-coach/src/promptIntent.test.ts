import { describe, expect, it } from 'vitest';
import {
  BLOCKER_REASONS,
  assertProviderAdapterPreservesIntent,
  buildPortablePrompt,
  projectReviewedStepToVisualSpecification,
  projectReviewedTutorialToPromptCards,
  validateApplicationFidelity,
  type PromptAuthoringInput,
  type VisualSpecification,
} from './promptIntent';
import { deriveRecordingUiEvidence, frameUiEvidence } from './uiEvidence';
import { tutorial0BlockedFinalState, tutorial0PromptCards, tutorial0ReviewedTutorial } from './fixtures/tutorial0-prompts';
import type { ReviewedStepProjection, ReviewedTutorialProjection } from './types';

const REC_SHA = 'a'.repeat(64);

// Synthetic recording with deliberate evidence geometry:
//   index 1 -> Alpha           index 2 -> Beta
//   index 3 -> Field (label) + Gamma (entered value)
//   index 4 -> Alpha AND Beta observed together (the only co-visible state)
const syntheticRecording = {
  title: 'synthetic ui-claim recording',
  steps: [
    { type: 'setViewport', width: 1440, height: 900 },
    { type: 'click', selectors: [['aria/Alpha']] },
    { type: 'click', selectors: [['aria/Beta']] },
    { type: 'change', value: 'Gamma', selectors: [['aria/Field']] },
    { type: 'click', selectors: [['aria/Alpha'], ['aria/Beta']] },
  ],
};
const recordingEvidence = deriveRecordingUiEvidence(syntheticRecording, REC_SHA);

function reviewedStep(overrides: Partial<ReviewedStepProjection> = {}): ReviewedStepProjection {
  const sourceIndexes = overrides.source_indexes ?? [1];
  const scope = new Set(sourceIndexes);
  return {
    review_step_id: 'step-1',
    sequence: 1,
    source_step_ids: ['step-1'],
    source_steps: [],
    semantic_action_ids: ['action-1'],
    source_indexes: [...sourceIndexes],
    recording_id: 'rec-1',
    recording_sha256: REC_SHA,
    modeled_application: 'Adobe Express',
    action_identity: recordingEvidence.actionIdentity.filter((item) => scope.has(item.sourceIndex)),
    execution_authorized: false,
    ...overrides,
  };
}

function makeTutorial(retained: ReviewedStepProjection[]): ReviewedTutorialProjection {
  return {
    recording_id: 'rec-1',
    recording_sha256: REC_SHA,
    retained_steps: retained,
    excluded_step_ids: [],
    review_decisions: [],
    recording_evidence: recordingEvidence,
    execution_authorized: false,
  };
}

function authoringFor(overrides: Partial<PromptAuthoringInput> = {}): PromptAuthoringInput {
  return {
    imagePurpose: 'Show the target action.',
    imageState: 'action',
    applicationContext: 'Adobe Express workspace navigation',
    targetState: 'Alpha is the clear next action',
    mustShow: ['Adobe Express', 'Alpha'],
    mustNotShow: [],
    annotationSpace: 'beside Alpha',
    requestedUiDetails: ['Alpha'],
    ...overrides,
  };
}

function specFor(sourceIndexes: number[], authoring: PromptAuthoringInput): VisualSpecification {
  const step = reviewedStep({ source_indexes: sourceIndexes });
  return projectReviewedStepToVisualSpecification(step, authoring, makeTutorial([step]));
}

/** A frame that claims no interface text at all — the only kind that can be ready in PPUX-F1. */
const nonInterfaceSpec: VisualSpecification = {
  stepNumber: 1,
  imagePurpose: 'Show the idea of grouping work by purpose.',
  imageState: 'result',
  application: 'Adobe Express',
  applicationContext: '',
  targetState: 'related work is grouped together',
  mustShow: ['three labelled groups'],
  mustNotShow: ['student data'],
  annotationSpace: 'beside the groups',
  provenance: ['approved Teacher Modeling'],
  requestedUiDetails: [],
  requiresScreenFidelity: false,
  capturedScreenRef: null,
  evidence: frameUiEvidence(recordingEvidence, [1]),
};

describe('PPUX-F1 UI-claim evidence authority', () => {
  it('rejects a semantic target as literal UI evidence', () => {
    // `Square project` and `Tutorial 0 folder` are modeling descriptors that appear
    // nowhere in the recording as observed interface text.
    for (const semanticTarget of ['Square project', 'Tutorial 0 folder', 'Landscape project']) {
      const authoring: PromptAuthoringInput = {
        imagePurpose: 'p', imageState: 'action', applicationContext: 'ctx',
        targetState: 'ts', mustShow: [semanticTarget], mustNotShow: [], annotationSpace: 'a',
        requestedUiDetails: [semanticTarget],
      };
      const card = buildPortablePrompt(
        projectReviewedStepToVisualSpecification(
          tutorial0ReviewedTutorial.retained_steps[0],
          authoring,
          tutorial0ReviewedTutorial,
        ),
      );
      expect(card.status).toBe('blocked');
      expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimUnsupported);
    }
  });

  it('does not let authoring supply or widen supported UI evidence', () => {
    // The authoring field is gone at type level; prove a smuggled one is inert at runtime.
    const smuggled = {
      ...authoringFor({ requestedUiDetails: ['Alpha', 'Nonexistent Control'] }),
      evidenceSupportedUiDetails: ['Alpha', 'Nonexistent Control'],
    } as unknown as PromptAuthoringInput;
    const card = buildPortablePrompt(specFor([1], smuggled));
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimUnsupported);
  });

  it('refuses evidence borrowed from another action (state locality)', () => {
    // Beta exists at index 2; this frame only covers index 1.
    const card = buildPortablePrompt(specFor([1], authoringFor({
      requestedUiDetails: ['Beta'], mustShow: ['Adobe Express', 'Beta'],
    })));
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimNotStateLocal);
    expect(card.blockerReasons).not.toContain(BLOCKER_REASONS.uiClaimUnsupported);
  });

  it('refuses co-visibility for details observed at separate states', () => {
    const card = buildPortablePrompt(specFor([1, 2], authoringFor({
      requestedUiDetails: ['Alpha', 'Beta'], mustShow: ['Adobe Express', 'Alpha', 'Beta'],
    })));
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimNotCoVisible);
  });

  it('accepts co-visibility only when one state observed both details', () => {
    const card = buildPortablePrompt(specFor([4], authoringFor({
      requestedUiDetails: ['Alpha', 'Beta'], mustShow: ['Adobe Express', 'Alpha', 'Beta'],
    })));
    expect(card.blockerReasons).not.toContain(BLOCKER_REASONS.uiClaimNotCoVisible);
    expect(card.blockerReasons).not.toContain(BLOCKER_REASONS.uiClaimNotStateLocal);
  });

  it('does not flatten action-local evidence when reviewed steps are combined', () => {
    // A combined step widens which states are in scope but must not merge them into
    // one screen: Alpha@1 and Beta@2 stay separate observations.
    const combined = reviewedStep({ review_step_id: 'combined', source_indexes: [1, 2] });
    const spec = projectReviewedStepToVisualSpecification(
      combined,
      authoringFor({ requestedUiDetails: ['Alpha', 'Beta'], mustShow: ['Adobe Express', 'Alpha', 'Beta'] }),
      makeTutorial([combined]),
    );
    const card = buildPortablePrompt(spec);
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimNotCoVisible);
    expect(spec.evidence.stateLocalClaims.map((claim) => claim.sourceIndex).sort()).toEqual([1, 2]);
  });

  it('fails closed when source_index matches but source_fingerprint does not', () => {
    const spec = specFor([1], authoringFor());
    const tampered: VisualSpecification = {
      ...spec,
      evidence: {
        ...spec.evidence,
        stateLocalClaims: spec.evidence.stateLocalClaims.map((claim) => ({
          ...claim,
          sourceFingerprint: 'f'.repeat(64),
        })),
      },
    };
    const card = buildPortablePrompt(tampered);
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimIdentityMismatch);
  });

  it('never falls back to a generative reconstruction when visual evidence is missing', () => {
    const card = buildPortablePrompt(specFor([1], authoringFor()));
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.visualEvidenceMissing);
    expect(card.portablePrompt).toBe('');
  });

  it('does not let an author relabel a frame out of the gate', () => {
    // Moving the interface label from requestedUiDetails into mustShow must not help.
    const card = buildPortablePrompt(specFor([1], authoringFor({
      requestedUiDetails: [], mustShow: ['Adobe Express', 'Alpha'],
    })));
    expect(card.requiresScreenFidelity).toBe(true);
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.visualEvidenceMissing);

    // Dropping applicationContext as well must still not lower the determination.
    const stripped = buildPortablePrompt(specFor([1], authoringFor({
      requestedUiDetails: [], mustShow: ['Adobe Express', 'Alpha'], applicationContext: '',
    })));
    expect(stripped.requiresScreenFidelity).toBe(true);
    expect(stripped.blockerReasons).toContain(BLOCKER_REASONS.visualEvidenceMissing);
  });

  it('re-derives the gate even if a specification is constructed with the flag turned off', () => {
    // Defence in depth: the projection derives the flag, but validation must not trust
    // it, or a hand-built specification could claim interface text as non-interface.
    const spec = specFor([1], authoringFor());
    const forged: VisualSpecification = { ...spec, requiresScreenFidelity: false };
    const card = buildPortablePrompt(forged);
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.visualEvidenceMissing);
    expect(card.portablePrompt).toBe('');
  });

  it('lets an author raise but never lower the software-interface determination', () => {
    const raised = buildPortablePrompt(specFor([1], authoringFor({
      requestedUiDetails: [], mustShow: ['a neutral concept'], applicationContext: '',
      screenFidelityRequired: true,
    })));
    expect(raised.requiresScreenFidelity).toBe(true);
    expect(raised.blockerReasons).toContain(BLOCKER_REASONS.visualEvidenceMissing);
  });

  it('exposes no copyable prompt on any blocked card', () => {
    const blocked = [
      buildPortablePrompt(specFor([1], authoringFor())),
      tutorial0BlockedFinalState,
      ...tutorial0PromptCards.filter((card) => card.status === 'blocked'),
    ];
    expect(blocked.length).toBeGreaterThan(1);
    for (const card of blocked) {
      expect(card.status).toBe('blocked');
      expect(card.portablePrompt).toBe('');
      expect(card.blockerReasons.length).toBeGreaterThan(0);
    }
  });
});

describe('PPUX-F1 Tutorial 0 fabrication regressions', () => {
  it('rejects the fabricated tutorial folder name that the recording never contains', () => {
    const observed = new Set(tutorial0ReviewedTutorial.recording_evidence.claims.map((claim) => claim.text));
    expect(observed.has('Tutorial 0 - My Favorite Food')).toBe(false);
    expect(observed.has('Tutorial 0 - Organize My Files')).toBe(true);

    const card = buildPortablePrompt(projectReviewedStepToVisualSpecification(
      tutorial0ReviewedTutorial.retained_steps[0],
      {
        imagePurpose: 'p', imageState: 'result', applicationContext: 'ctx', targetState: 'ts',
        mustShow: ['Tutorial 0 - My Favorite Food'], mustNotShow: [], annotationSpace: 'a',
        requestedUiDetails: ['Tutorial 0 - My Favorite Food'],
      },
      tutorial0ReviewedTutorial,
    ));
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimUnsupported);
  });

  it('rejects the near-miss control label rather than normalising it', () => {
    const observed = new Set(tutorial0ReviewedTutorial.recording_evidence.claims.map((claim) => claim.text));
    expect(observed.has('Create new file')).toBe(false);
    expect(observed.has('Create new')).toBe(true);

    const squareStep = tutorial0ReviewedTutorial.retained_steps.find((step) => step.review_step_id === 'tutorial0-step-03-square-file');
    expect(squareStep).toBeDefined();
    const card = buildPortablePrompt(projectReviewedStepToVisualSpecification(
      squareStep!,
      {
        imagePurpose: 'p', imageState: 'action', applicationContext: 'ctx', targetState: 'ts',
        mustShow: ['Create new file'], mustNotShow: [], annotationSpace: 'a',
        requestedUiDetails: ['Create new file'],
      },
      tutorial0ReviewedTutorial,
    ));
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimUnsupported);
  });

  it('rejects format choices borrowed from other steps on the landscape frame', () => {
    const landscapeStep = tutorial0ReviewedTutorial.retained_steps.find((step) => step.review_step_id === 'tutorial0-step-05-landscape-file');
    expect(landscapeStep).toBeDefined();
    const card = buildPortablePrompt(projectReviewedStepToVisualSpecification(
      landscapeStep!,
      {
        imagePurpose: 'p', imageState: 'action+result', applicationContext: 'ctx', targetState: 'ts',
        mustShow: ['Square', 'Landscape', 'Portrait'], mustNotShow: [], annotationSpace: 'a',
        requestedUiDetails: ['Square', 'Landscape', 'Portrait'],
      },
      tutorial0ReviewedTutorial,
    ));
    // Square@14 and Portrait@26 are real recording text but belong to other actions.
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.uiClaimNotStateLocal);
    expect(card.blockerReasons).not.toContain(BLOCKER_REASONS.uiClaimUnsupported);
  });

  it('keeps the corrected Tutorial 0 cards blocked for want of screen evidence', () => {
    expect(tutorial0PromptCards.length).toBeGreaterThan(0);
    for (const card of tutorial0PromptCards) {
      expect(card.application).toBe('Adobe Express');
      expect(card.requiresScreenFidelity).toBe(true);
      expect(card.status).toBe('blocked');
      expect(card.blockerReasons).toContain(BLOCKER_REASONS.visualEvidenceMissing);
      expect(card.portablePrompt).toBe('');
    }
  });

  it('keeps the unsupported Tutorial 0 final state blocked rather than inventing filenames', () => {
    expect(tutorial0BlockedFinalState.status).toBe('blocked');
    expect(tutorial0BlockedFinalState.blockerReasons).toContain(BLOCKER_REASONS.uiClaimUnsupported);
    expect(tutorial0BlockedFinalState.blockerReasons).toContain(BLOCKER_REASONS.uiClaimNotStateLocal);
  });
});

describe('PPUX-C application identity fidelity (preserved)', () => {
  it('produces a ready prompt only for a non-interface frame', () => {
    const card = buildPortablePrompt(nonInterfaceSpec);
    expect(card.status).toBe('ready');
    expect(card.requiresScreenFidelity).toBe(false);
    expect(card.portablePrompt).toContain('Adobe Express');
    expect(card.portablePrompt).toContain('non-interface instructional visual');
    expect(validateApplicationFidelity(card)).toEqual([]);
  });

  it('rejects an application-neutral prompt', () => {
    const card = buildPortablePrompt(nonInterfaceSpec);
    const generic = { ...card, portablePrompt: card.portablePrompt.replaceAll('Adobe Express', 'generic creative application') };
    expect(validateApplicationFidelity(generic)).toContain('portable prompt lost modeled application identity');
  });

  it('rejects a wrong-app substitution', () => {
    const card = buildPortablePrompt(nonInterfaceSpec);
    const wrong = { ...card, portablePrompt: `${card.portablePrompt} Please depict Canva instead.` };
    expect(validateApplicationFidelity(wrong)).toContain('portable prompt substituted wrong application: Canva');
  });

  it('rejects a ready prompt that requests interface depiction', () => {
    const card = buildPortablePrompt(nonInterfaceSpec);
    const reconstructing = { ...card, portablePrompt: `${card.portablePrompt} Render a realistic screenshot.` };
    expect(validateApplicationFidelity(reconstructing)).toContain('portable prompt requests software-interface depiction without capture evidence');
  });

  it('rejects a ready prompt that dropped the non-reconstruction directive', () => {
    const card = buildPortablePrompt(nonInterfaceSpec);
    const stripped = { ...card, portablePrompt: card.portablePrompt.replace(/Do not depict[^.]*\./, '') };
    expect(validateApplicationFidelity(stripped)).toContain('portable prompt lost the non-reconstruction directive');
  });

  it('rejects a software-interface card that somehow reports ready', () => {
    const card = buildPortablePrompt(nonInterfaceSpec);
    const forged = { ...card, requiresScreenFidelity: true };
    expect(validateApplicationFidelity(forged)).toContain('a software-interface frame cannot be ready without approved capture evidence');
  });

  it('rejects provider-specific canonical syntax', () => {
    const card = buildPortablePrompt(nonInterfaceSpec);
    const providerSpecific = { ...card, portablePrompt: `${card.portablePrompt} --ar 16:9` };
    expect(validateApplicationFidelity(providerSpecific)).toContain('canonical prompt contains provider-specific syntax: --ar ');
  });

  it('blocks output when application identity is missing', () => {
    const card = buildPortablePrompt({ ...nonInterfaceSpec, application: '' });
    expect(card.status).toBe('blocked');
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.applicationIdentityMissing);
  });

  it('requires recognizable application context on a software-interface frame', () => {
    const spec = specFor([1], authoringFor({ applicationContext: '' }));
    const card = buildPortablePrompt(spec);
    expect(card.requiresScreenFidelity).toBe(true);
    expect(card.blockerReasons).toContain(BLOCKER_REASONS.specificationIncomplete);
  });

  it('prevents provider adapters from dropping application identity or must-show evidence', () => {
    const card = buildPortablePrompt(nonInterfaceSpec);
    expect(assertProviderAdapterPreservesIntent(card, 'related work is grouped together')).toContain('provider adapter removed application identity');
    expect(assertProviderAdapterPreservesIntent(card, 'Adobe Express related work is grouped together three labelled groups')).toEqual([]);
  });
});

describe('PPUX-C Stage 4 reviewed-projection consumption (preserved)', () => {
  it('feeds a ReviewedTutorialProjection into Stage 4 and preserves retained order', () => {
    const steps = [
      reviewedStep({ review_step_id: 'a', sequence: 1 }),
      reviewedStep({ review_step_id: 'b', sequence: 2 }),
    ];
    const tutorial = makeTutorial(steps);
    const cards = projectReviewedTutorialToPromptCards(tutorial, new Map([
      ['a', authoringFor()],
      ['b', authoringFor()],
    ]));
    expect(cards.map((card) => card.stepNumber)).toEqual([1, 2]);
  });

  it('excludes Not Instructional steps because they never enter retained_steps', () => {
    const tutorial = makeTutorial([reviewedStep({ review_step_id: 'a', sequence: 1 })]);
    const cards = projectReviewedTutorialToPromptCards(tutorial, new Map([['a', authoringFor()]]));
    expect(cards).toHaveLength(1);
    expect(tutorial.excluded_step_ids).not.toContain('a');
  });

  it('preserves combined-step provenance into the prompt card', () => {
    const combined = reviewedStep({
      review_step_id: 'combined',
      source_step_ids: ['step-1', 'step-2'],
      semantic_action_ids: ['action-1', 'action-2'],
    });
    const spec = projectReviewedStepToVisualSpecification(combined, authoringFor(), makeTutorial([combined]));
    expect(spec.provenance).toEqual(expect.arrayContaining([
      'source_step:step-1', 'source_step:step-2', 'semantic_action:action-1', 'semantic_action:action-2',
    ]));
  });

  it('keeps execution_authorized false throughout prompt generation', () => {
    const step = reviewedStep();
    const card = buildPortablePrompt(projectReviewedStepToVisualSpecification(step, authoringFor(), makeTutorial([step])));
    expect(tutorial0ReviewedTutorial.execution_authorized).toBe(false);
    expect(tutorial0ReviewedTutorial.retained_steps.every((item) => item.execution_authorized === false)).toBe(true);
    expect('execution_authorized' in card).toBe(false);
  });

  it('does not infer application identity from step title or branding text alone', () => {
    const step = reviewedStep({
      modeled_application: null,
      source_steps: [{
        step_id: 'step-1',
        sequence: 1,
        disposition: 'keep',
        title: 'Organize your Adobe Express location',
        semantic_action_ids: ['action-1'],
        source: {
          candidate_id: 'c1',
          recording_id: 'rec-1',
          recording_sha256: REC_SHA,
          source_indexes: [1],
          rj3_state: 'pending',
          rj4_state: 'pending',
          modeled_application: null,
        },
        execution_authorized: false,
      }],
    });
    const spec = projectReviewedStepToVisualSpecification(step, authoringFor(), makeTutorial([step]));
    expect(spec.application).toBe('');
    expect(buildPortablePrompt(spec).blockerReasons).toContain(BLOCKER_REASONS.applicationIdentityMissing);
  });
});
