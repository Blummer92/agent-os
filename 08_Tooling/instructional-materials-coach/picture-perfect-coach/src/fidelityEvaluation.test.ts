import { describe, expect, it } from 'vitest';
import { evaluateFidelity } from './fidelityEvaluation';

describe('evaluateFidelity', () => {
  it('keeps instructional usefulness separate from interface and artifact-state failures', () => {
    const result = evaluateFidelity({
      provider: 'gemini',
      model: 'flash',
      prompt_strategy: 'constraint-first',
      instructional_state: 'pass',
      interface_fidelity: 'fail',
      artifact_state_fidelity: 'fail',
      negative_constraints: 'pass',
      execution_completion: 'pass',
      reasons: ['invented editor controls', 'immutable layout drift'],
    });

    expect(result.status).toBe('evaluated');
    expect(result.instructional_state).toBe('pass');
    expect(result.interface_fidelity).toBe('fail');
    expect(result.artifact_state_fidelity).toBe('fail');
    expect(result.generated_output_is_source_evidence).toBe(false);
  });

  it('records explicit negative-constraint failure independently', () => {
    const result = evaluateFidelity({
      provider: 'gemini',
      model: 'flash',
      instructional_state: 'pass',
      interface_fidelity: 'warn',
      artifact_state_fidelity: 'warn',
      negative_constraints: 'fail',
      execution_completion: 'pass',
      reasons: ['invented red annotation'],
    });

    expect(result.negative_constraints).toBe('fail');
    expect(result.instructional_state).toBe('pass');
  });

  it('fails execution completion when image production collapses into coaching/specification', () => {
    const result = evaluateFidelity({
      provider: 'gemini',
      model: 'pro',
      prompt_strategy: 'minimal-imperative',
      instructional_state: 'manual-review',
      interface_fidelity: 'manual-review',
      artifact_state_fidelity: 'manual-review',
      negative_constraints: 'manual-review',
      execution_completion: 'fail',
      reasons: ['returned planning text instead of an image'],
    });

    expect(result.execution_completion).toBe('fail');
    expect(result.status).toBe('manual-review-required');
  });

  it('routes ambiguous evidence to manual review instead of fabricating certainty', () => {
    const result = evaluateFidelity({
      provider: 'gemini',
      model: 'flash-lite',
      instructional_state: 'warn',
      interface_fidelity: 'warn',
      artifact_state_fidelity: 'warn',
      negative_constraints: 'pass',
      execution_completion: 'pass',
      reasons: [],
      ambiguous: true,
    });

    expect(result.status).toBe('manual-review-required');
  });

  it('preserves provider/model/prompt strategy as evidence without creating source authority', () => {
    const result = evaluateFidelity({
      provider: ' gemini ',
      model: ' flash ',
      prompt_strategy: ' state-diff ',
      instructional_state: 'pass',
      interface_fidelity: 'warn',
      artifact_state_fidelity: 'warn',
      negative_constraints: 'pass',
      execution_completion: 'pass',
      reasons: ['transition visualization', 'transition visualization'],
    });

    expect(result.provider).toBe('gemini');
    expect(result.model).toBe('flash');
    expect(result.prompt_strategy).toBe('state-diff');
    expect(result.reasons).toEqual(['transition visualization']);
    expect(result.generated_output_is_source_evidence).toBe(false);
  });

  it('requires provider and model identity', () => {
    expect(() => evaluateFidelity({
      provider: '',
      model: 'flash',
      instructional_state: 'pass',
      interface_fidelity: 'pass',
      artifact_state_fidelity: 'pass',
      negative_constraints: 'pass',
      execution_completion: 'pass',
      reasons: [],
    })).toThrow('provider and model are required evaluation evidence');
  });
});
