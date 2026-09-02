import { describe, expect, it } from 'vitest';
import { evaluateSequenceFidelity } from './sequenceFidelity';

describe('sequence fidelity', () => {
  it('passes an ordered sequence that preserves prior state', () => {
    expect(evaluateSequenceFidelity([
      { imageNumber: 1, preservedState: [], changedState: ['bun'] },
      { imageNumber: 2, preservedState: ['bun'], changedState: ['patty'] },
      { imageNumber: 3, preservedState: ['bun', 'patty'], changedState: ['cheese'] },
    ])).toEqual({ status: 'pass', reasonCodes: [] });
  });

  it('fails closed when a later frame claims unproven preserved state', () => {
    expect(evaluateSequenceFidelity([
      { imageNumber: 1, preservedState: [], changedState: ['bun'] },
      { imageNumber: 2, preservedState: ['lettuce'], changedState: ['patty'] },
    ])).toEqual({ status: 'manual-review', reasonCodes: ['preserved-state-unproven'] });
  });

  it('fails closed on ambiguous numbering', () => {
    expect(evaluateSequenceFidelity([
      { imageNumber: 2, preservedState: [], changedState: ['bun'] },
      { imageNumber: 3, preservedState: ['bun'], changedState: ['patty'] },
    ]).status).toBe('manual-review');
  });
});
