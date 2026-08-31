import { describe, expect, it } from 'vitest';
import {
  admitProcedureSynthesis,
  deriveProcedurePrompt,
  type ProcedureSynthesisContract,
} from './procedureSynthesis';

const hamburger: ProcedureSynthesisContract = {
  mode: 'procedure-grounded',
  evidence_id: 'teacher-confirmed:tutorial-1-hamburger',
  required_components: ['top-bun', 'patty', 'cheese', 'lettuce', 'bottom-bun'],
  forbidden_components: ['tomato', 'onion', 'pickle', 'sesame-seeds'],
  dimensionality: 'flat-2d',
  authentic_source_claimed: false,
  components: [
    { component_id: 'top-bun', primitive: 'circle', construction_method: 'shape primitive', operation: 'place', operation_parameters: {}, creation_order: 0, final_z_order: 4, fill: 'brown', opacity: 1, required_visible_consequence: 'flat circle-derived bun form', deviation: 'review-blocking' },
    { component_id: 'patty', primitive: 'simple-shape', construction_method: 'shape primitive', operation: 'place', operation_parameters: {}, creation_order: 1, final_z_order: 1, fill: 'brown', opacity: 1, required_visible_consequence: null, deviation: 'approximate' },
    { component_id: 'cheese', primitive: 'simple-shape', construction_method: 'shape plus manual erase', operation: 'erase-irregular-cutouts', operation_parameters: { irregular: true }, creation_order: 2, final_z_order: 2, fill: 'yellow', opacity: 0.7, required_visible_consequence: 'translucent cheese with irregular openings revealing content behind', deviation: 'review-blocking' },
    { component_id: 'lettuce', primitive: null, construction_method: 'manual drawing', operation: 'draw-white-linework', operation_parameters: {}, creation_order: 3, final_z_order: 3, fill: 'green', opacity: 1, required_visible_consequence: 'green manually drawn region with white line strokes', deviation: 'review-blocking' },
    { component_id: 'bottom-bun', primitive: 'circle', construction_method: 'shape primitive', operation: 'place', operation_parameters: {}, creation_order: 4, final_z_order: 0, fill: 'brown', opacity: 1, required_visible_consequence: 'flat circle-derived bun form', deviation: 'review-blocking' },
  ],
};

describe('procedure-grounded synthesis', () => {
  it('admits a complete teacher-confirmed procedure without claiming authenticity', () => {
    expect(admitProcedureSynthesis(hamburger)).toEqual({ status: 'admitted', contract: hamburger });
    expect(hamburger.authentic_source_claimed).toBe(false);
  });

  it('keeps creation order distinct from final z-order', () => {
    const cheese = hamburger.components.find((component) => component.component_id === 'cheese');
    expect(cheese?.creation_order).toBe(2);
    expect(cheese?.final_z_order).toBe(2);
    const lettuce = hamburger.components.find((component) => component.component_id === 'lettuce');
    expect(lettuce?.creation_order).toBe(3);
    expect(lettuce?.final_z_order).toBe(3);
  });

  it('fails closed when semantic prior content adds forbidden tomato', () => {
    const result = admitProcedureSynthesis({ ...hamburger, components: [...hamburger.components, { ...hamburger.components[1], component_id: 'tomato' }] });
    expect(result.status).toBe('needs-review');
    if (result.status === 'needs-review') expect(result.reasons).toContain('procedure-synthesis-forbidden-component-present:tomato');
  });

  it('fails closed when procedure evidence is missing', () => {
    expect(admitProcedureSynthesis({ ...hamburger, evidence_id: null })).toEqual({ status: 'needs-review', reasons: ['procedure-synthesis-evidence-required'] });
  });

  it('does not allow procedure synthesis to impersonate exact/authentic reproduction', () => {
    const result = admitProcedureSynthesis({ ...hamburger, mode: 'exact-authentic' });
    expect(result.status).toBe('needs-review');
    if (result.status === 'needs-review') expect(result.reasons).toContain('procedure-synthesis-exact-authentic-requires-source-admission');
  });

  it('derives provider-neutral prompt text from canonical procedure evidence', () => {
    const prompt = deriveProcedurePrompt(hamburger);
    expect(prompt).toContain('Do not add conventional details from object semantics');
    expect(prompt).toContain('Forbidden components: tomato, onion, pickle, sesame-seeds.');
    expect(prompt).toContain('Primitive: circle.');
    expect(prompt).toContain('Opacity: 0.7.');
    expect(prompt).toContain('irregular openings revealing content behind');
    expect(prompt).toContain('manual drawing');
    expect(prompt).toContain('Dimensionality: flat-2d.');
    expect(prompt).toContain('not authentic captured source evidence');
    expect(prompt).not.toMatch(/\b(?:Gemini|Flash|Pro|price)\b/i);
  });

  it('does not infer unsupported components from the semantic object label', () => {
    const prompt = deriveProcedurePrompt(hamburger);
    expect(prompt).not.toContain('sesame seeds');
    expect(prompt).not.toContain('pickles');
    expect(prompt).not.toContain('onions');
  });
});
