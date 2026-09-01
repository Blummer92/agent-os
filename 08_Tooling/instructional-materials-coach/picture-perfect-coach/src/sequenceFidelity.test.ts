import { describe, expect, it } from 'vitest';
import {
  evaluateSequenceFidelity,
  SEQUENCE_FIDELITY_REASONS,
  type SequenceFrameSnapshot,
} from './sequenceFidelity';

function frame(overrides: Partial<SequenceFrameSnapshot> = {}): SequenceFrameSnapshot {
  return {
    frameId: 'A',
    objectIds: ['bun', 'patty', 'lettuce-copy'],
    selectedObjectId: 'lettuce-copy',
    cameraState: 'camera-1',
    workplaneState: 'workplane-1',
    uiState: 'ui-1',
    controlState: 'rotation:0',
    unrelatedObjectState: 'bun@1,patty@1',
    continuityConfidence: 'resolved',
    ...overrides,
  };
}

const rotationDelta = [{
  fromFrameId: 'A',
  toFrameId: 'B',
  allowedFields: ['controlState'] as const,
}];

describe('cross-frame sequence fidelity', () => {
  it('passes when only the evidence-authorized rotation state changes', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', controlState: 'rotation:120' })],
      rotationDelta,
    );
    expect(result).toEqual({ status: 'pass', reasons: [] });
  });

  it('fails object inventory drift such as an extra bun in Frame B', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', objectIds: ['bun', 'patty', 'lettuce-copy', 'extra-bun'], controlState: 'rotation:120' })],
      rotationDelta,
    );
    expect(result.status).toBe('fail');
    expect(result.reasons).toContain(SEQUENCE_FIDELITY_REASONS.objectInventoryDrift);
  });

  it('reports camera, UI/control grammar, and unrelated-object drift independently', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({
        frameId: 'B',
        cameraState: 'camera-2',
        uiState: 'ui-panel-moved',
        controlState: 'two-rotation-boxes:120',
        unrelatedObjectState: 'bun@2,patty@1',
      })],
      [],
    );
    expect(result.status).toBe('manual-review');
    expect(result.reasons).toEqual(expect.arrayContaining([
      SEQUENCE_FIDELITY_REASONS.ambiguousContinuity,
      SEQUENCE_FIDELITY_REASONS.cameraDrift,
      SEQUENCE_FIDELITY_REASONS.uiDrift,
      SEQUENCE_FIDELITY_REASONS.controlDrift,
      SEQUENCE_FIDELITY_REASONS.unrelatedObjectDrift,
    ]));
  });

  it('allows explicitly evidenced tutorial UI changes', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', uiState: 'ui-step-2', controlState: 'rotation:120' })],
      [{ fromFrameId: 'A', toFrameId: 'B', allowedFields: ['uiState', 'controlState'] }],
    );
    expect(result.status).toBe('pass');
  });

  it('routes unresolved persistent identity to manual review rather than guessing', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', controlState: 'rotation:120', continuityConfidence: 'ambiguous' })],
      rotationDelta,
    );
    expect(result.status).toBe('manual-review');
    expect(result.reasons).toContain(SEQUENCE_FIDELITY_REASONS.ambiguousContinuity);
  });

  it('fails requested frame-count and canonical frame-identity mismatch', () => {
    const collage = [
      frame(),
      frame({ frameId: 'B', controlState: 'rotation:120' }),
      frame({ frameId: 'alternate-1' }),
      frame({ frameId: 'alternate-2' }),
    ];
    const result = evaluateSequenceFidelity(['A', 'B'], collage, rotationDelta);
    expect(result.status).toBe('fail');
    expect(result.reasons).toContain(SEQUENCE_FIDELITY_REASONS.frameCountMismatch);
    expect(result.reasons).toContain(SEQUENCE_FIDELITY_REASONS.frameIdentityMismatch);
  });

  it('does not infer sequence pass from standalone plausibility when target identity changes', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', selectedObjectId: 'different-lettuce', controlState: 'rotation:120' })],
      rotationDelta,
    );
    expect(result.status).toBe('fail');
    expect(result.reasons).toContain(SEQUENCE_FIDELITY_REASONS.targetIdentityDrift);
  });
});
