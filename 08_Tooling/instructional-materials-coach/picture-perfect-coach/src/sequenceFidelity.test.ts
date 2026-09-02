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
    tutorialPanelState: 'tutorial-step-1',
    themeState: 'theme-1',
    controlState: 'rotation:0',
    controlGrammarState: 'single-rotation-control',
    unrelatedObjectState: 'bun@1,patty@1',
    sessionId: 'session-1',
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
    expect(evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', controlState: 'rotation:120' })],
      rotationDelta,
    )).toEqual({ status: 'pass', reasons: [], singleFrameFindings: [] });
  });

  it('treats object inventory as an unordered inventory and fails an extra bun', () => {
    expect(evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', objectIds: ['lettuce-copy', 'bun', 'patty'], controlState: 'rotation:120' })],
      rotationDelta,
    ).status).toBe('pass');

    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', objectIds: ['bun', 'patty', 'lettuce-copy', 'extra-bun'], controlState: 'rotation:120' })],
      rotationDelta,
    );
    expect(result.status).toBe('fail');
    expect(result.reasons).toContain(SEQUENCE_FIDELITY_REASONS.objectInventoryDrift);
  });

  it('reports camera, panel placement, control grammar, workplane, theme, and unrelated-object drift independently', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({
        frameId: 'B',
        cameraState: 'camera-2',
        workplaneState: 'workplane-2',
        uiState: 'ui-panel-moved',
        tutorialPanelState: 'tutorial-panel-wider',
        themeState: 'theme-2',
        controlState: 'rotation:120',
        controlGrammarState: 'two-rotation-boxes',
        unrelatedObjectState: 'bun@2,patty@1',
      })],
      rotationDelta,
    );
    expect(result.status).toBe('fail');
    expect(result.reasons).toEqual(expect.arrayContaining([
      SEQUENCE_FIDELITY_REASONS.cameraDrift,
      SEQUENCE_FIDELITY_REASONS.workplaneDrift,
      SEQUENCE_FIDELITY_REASONS.uiDrift,
      SEQUENCE_FIDELITY_REASONS.tutorialPanelDrift,
      SEQUENCE_FIDELITY_REASONS.themeDrift,
      SEQUENCE_FIDELITY_REASONS.controlDrift,
      SEQUENCE_FIDELITY_REASONS.unrelatedObjectDrift,
    ]));
  });

  it('allows explicitly evidenced tutorial text/UI changes', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({
        frameId: 'B',
        tutorialPanelState: 'tutorial-step-2',
        controlState: 'rotation:120',
      })],
      [{ fromFrameId: 'A', toFrameId: 'B', allowedFields: ['tutorialPanelState', 'controlState'] }],
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

  it('fails two plausible standalone frames that represent different persistent sessions', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', sessionId: 'session-2', controlState: 'rotation:120' })],
      rotationDelta,
    );
    expect(result.status).toBe('fail');
    expect(result.reasons).toContain(SEQUENCE_FIDELITY_REASONS.sessionIdentityDrift);
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

  it('composes #1542 single-frame findings without replacing sequence evaluation', () => {
    const result = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame({ singleFrameFindings: ['single-frame-control-invalid'] }), frame({ frameId: 'B', controlState: 'rotation:120' })],
      rotationDelta,
    );
    expect(result.status).toBe('fail');
    expect(result.reasons).toContain(SEQUENCE_FIDELITY_REASONS.singleFrameFinding);
    expect(result.singleFrameFindings).toEqual(['single-frame-control-invalid']);
  });

  it('distinguishes missing transition evidence from a proven unauthorized delta', () => {
    const ambiguous = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B' })],
      [],
    );
    expect(ambiguous.status).toBe('manual-review');
    expect(ambiguous.reasons).toContain(SEQUENCE_FIDELITY_REASONS.missingTransitionEvidence);

    const unauthorized = evaluateSequenceFidelity(
      ['A', 'B'],
      [frame(), frame({ frameId: 'B', cameraState: 'camera-2' })],
      [],
    );
    expect(unauthorized.status).toBe('fail');
    expect(unauthorized.reasons).toEqual(expect.arrayContaining([
      SEQUENCE_FIDELITY_REASONS.missingTransitionEvidence,
      SEQUENCE_FIDELITY_REASONS.cameraDrift,
    ]));
  });
});
