import { describe, expect, it } from 'vitest';
import {
  admitStillImageRoute,
  selectPresentationModality,
  type PresentationEvidence,
} from './presentationModality';

const frame = (sequence: number, evidenceId = `frame-${sequence}`) => ({
  sequence,
  evidenceId,
  imageState: 'action' as const,
  provenance: [`source:${evidenceId}`],
});

const evidence = (overrides: Partial<PresentationEvidence> = {}): PresentationEvidence => ({
  instructionalIntentId: 'tutorial-0-step-1',
  stableVisualStateSufficient: true,
  distinctVisualStatesRequired: false,
  continuousTemporalBehaviorRequired: false,
  frameEvidence: [frame(1)],
  ...overrides,
});

describe('presentation modality selection', () => {
  it('selects still-frame for one stable evidence-bound visual state', () => {
    const result = selectPresentationModality(evidence());
    expect(result.status).toBe('ready');
    expect(result.modality).toBe('still-frame');
  });

  it('selects frame-sequence when multiple distinct states are materially required', () => {
    const result = selectPresentationModality(evidence({
      stableVisualStateSufficient: false,
      distinctVisualStatesRequired: true,
      frameEvidence: [frame(2), frame(1), frame(3)],
    }));
    expect(result.modality).toBe('frame-sequence');
    expect(result.frameEvidence.map((item) => item.sequence)).toEqual([1, 2, 3]);
    expect(result.frameEvidence.map((item) => item.evidenceId)).toEqual(['frame-1', 'frame-2', 'frame-3']);
  });

  it('selects motion-required only when approved evidence explicitly requires temporal behavior', () => {
    const result = selectPresentationModality(evidence({
      stableVisualStateSufficient: false,
      continuousTemporalBehaviorRequired: true,
    }));
    expect(result.modality).toBe('motion-required');
    expect(admitStillImageRoute(result)).toEqual({ allowed: false, canonical: false, reason: 'motion-required' });
  });

  it('does not infer sequence or motion from multiple recorder/frame events alone', () => {
    const result = selectPresentationModality(evidence({ frameEvidence: [frame(1), frame(2), frame(3)] }));
    expect(result.modality).toBe('still-frame');
  });

  it('fails closed when evidence asserts conflicting modalities', () => {
    const result = selectPresentationModality(evidence({ distinctVisualStatesRequired: true }));
    expect(result.status).toBe('needs-review');
    expect(result.modality).toBeNull();
    expect(result.blockerReasons).toContain('presentation-modality-ambiguous-evidence');
  });

  it('fails closed when a frame-sequence lacks multiple admitted frames', () => {
    const result = selectPresentationModality(evidence({
      stableVisualStateSufficient: false,
      distinctVisualStatesRequired: true,
      frameEvidence: [frame(1)],
    }));
    expect(result.status).toBe('needs-review');
    expect(result.blockerReasons).toContain('presentation-modality-missing-frame-evidence');
  });

  it('preserves per-frame action/result/action+result vocabulary rather than overloading modality', () => {
    const result = selectPresentationModality(evidence({
      stableVisualStateSufficient: false,
      distinctVisualStatesRequired: true,
      frameEvidence: [
        { ...frame(1), imageState: 'action' },
        { ...frame(2), imageState: 'result' },
        { ...frame(3), imageState: 'action+result' },
      ],
    }));
    expect(result.frameEvidence.map((item) => item.imageState)).toEqual(['action', 'result', 'action+result']);
  });

  it('rejects duplicate frame order instead of guessing', () => {
    const result = selectPresentationModality(evidence({
      stableVisualStateSufficient: false,
      distinctVisualStatesRequired: true,
      frameEvidence: [frame(1, 'before'), frame(1, 'after')],
    }));
    expect(result.status).toBe('needs-review');
    expect(result.blockerReasons).toContain('presentation-modality-duplicate-frame-order');
  });

  it('allows a motion step still preview only as explicitly non-canonical', () => {
    const decision = selectPresentationModality(evidence({
      stableVisualStateSufficient: false,
      continuousTemporalBehaviorRequired: true,
    }));
    expect(admitStillImageRoute(decision, { previewRequested: true })).toEqual({
      allowed: true,
      canonical: false,
      reason: 'non-canonical-preview',
    });
  });

  it('keeps provider preference and price outside the modality authority surface', () => {
    const input = evidence();
    expect('provider' in input).toBe(false);
    expect('model' in input).toBe(false);
    expect('price' in input).toBe(false);
    expect(selectPresentationModality(input).modality).toBe('still-frame');
  });

  it('does not hard-code Tutorial 0 as motion', () => {
    const tutorialZeroStable = selectPresentationModality(evidence({ instructionalIntentId: 'tutorial-0-stable-state' }));
    const tutorialZeroMotion = selectPresentationModality(evidence({
      instructionalIntentId: 'tutorial-0-drag-path',
      stableVisualStateSufficient: false,
      continuousTemporalBehaviorRequired: true,
    }));
    expect(tutorialZeroStable.modality).toBe('still-frame');
    expect(tutorialZeroMotion.modality).toBe('motion-required');
  });
});
