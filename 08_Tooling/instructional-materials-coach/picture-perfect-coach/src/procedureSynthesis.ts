export type SynthesisMode = 'semantic-creation' | 'procedure-grounded' | 'exact-authentic';
export type ProcedureDeviation = 'allowed' | 'approximate' | 'review-blocking';
export type Dimensionality = 'flat-2d' | 'depth-permitted' | null;

export type ProcedureComponent = Readonly<{
  component_id: string;
  primitive: string | null;
  construction_method: string | null;
  operation: string | null;
  operation_parameters: Readonly<Record<string, string | number | boolean>>;
  creation_order: number | null;
  final_z_order: number | null;
  fill: string | null;
  opacity: number | null;
  required_visible_consequence: string | null;
  deviation: ProcedureDeviation;
}>;

export type ProcedureSynthesisContract = Readonly<{
  mode: SynthesisMode;
  evidence_id: string | null;
  components: readonly ProcedureComponent[];
  required_components: readonly string[];
  forbidden_components: readonly string[];
  dimensionality: Dimensionality;
  authentic_source_claimed: false;
}>;

export type ProcedureSynthesisDecision =
  | Readonly<{ status: 'admitted'; contract: ProcedureSynthesisContract }>
  | Readonly<{ status: 'needs-review'; reasons: readonly string[] }>;

const MODES = new Set<SynthesisMode>(['semantic-creation', 'procedure-grounded', 'exact-authentic']);
const DEVIATIONS = new Set<ProcedureDeviation>(['allowed', 'approximate', 'review-blocking']);

function unique(values: readonly string[]): boolean {
  return new Set(values).size === values.length;
}

export function admitProcedureSynthesis(contract: ProcedureSynthesisContract): ProcedureSynthesisDecision {
  const reasons: string[] = [];
  if (!MODES.has(contract.mode)) reasons.push('procedure-synthesis-mode-unknown');

  if (contract.mode === 'exact-authentic') {
    reasons.push('procedure-synthesis-exact-authentic-requires-source-admission');
  }

  if (contract.mode === 'procedure-grounded' && !contract.evidence_id) {
    reasons.push('procedure-synthesis-evidence-required');
  }

  if (!unique(contract.required_components) || !unique(contract.forbidden_components)) {
    reasons.push('procedure-synthesis-component-inventory-duplicate');
  }

  if (contract.required_components.some((id) => contract.forbidden_components.includes(id))) {
    reasons.push('procedure-synthesis-component-inventory-conflict');
  }

  const ids = contract.components.map((component) => component.component_id);
  if (!unique(ids) || ids.some((id) => id.length === 0)) {
    reasons.push('procedure-synthesis-component-identity-invalid');
  }

  for (const required of contract.required_components) {
    if (!ids.includes(required)) reasons.push(`procedure-synthesis-required-component-missing:${required}`);
  }
  for (const forbidden of contract.forbidden_components) {
    if (ids.includes(forbidden)) reasons.push(`procedure-synthesis-forbidden-component-present:${forbidden}`);
  }

  for (const component of contract.components) {
    if (!DEVIATIONS.has(component.deviation)) reasons.push(`procedure-synthesis-deviation-unknown:${component.component_id}`);
    if (component.opacity !== null && (component.opacity < 0 || component.opacity > 1)) {
      reasons.push(`procedure-synthesis-opacity-invalid:${component.component_id}`);
    }
    if (component.creation_order !== null && (!Number.isInteger(component.creation_order) || component.creation_order < 0)) {
      reasons.push(`procedure-synthesis-creation-order-invalid:${component.component_id}`);
    }
    if (component.final_z_order !== null && (!Number.isInteger(component.final_z_order) || component.final_z_order < 0)) {
      reasons.push(`procedure-synthesis-final-z-order-invalid:${component.component_id}`);
    }
  }

  if (contract.mode === 'procedure-grounded' && contract.components.length === 0) {
    reasons.push('procedure-synthesis-procedure-insufficient');
  }

  return reasons.length > 0 ? { status: 'needs-review', reasons } : { status: 'admitted', contract };
}

export function deriveProcedurePrompt(contract: ProcedureSynthesisContract): string {
  if (contract.mode !== 'procedure-grounded') {
    throw new Error('procedure prompt requires procedure-grounded mode');
  }
  const decision = admitProcedureSynthesis(contract);
  if (decision.status !== 'admitted') throw new Error(decision.reasons.join(','));

  const lines = [
    'Create only from the supplied instructional procedure. Do not add conventional details from object semantics.',
    `Required components: ${contract.required_components.join(', ') || 'none'}.`,
    `Forbidden components: ${contract.forbidden_components.join(', ') || 'none'}.`,
    `Dimensionality: ${contract.dimensionality ?? 'not specified by evidence'}.`,
  ];
  for (const component of contract.components) {
    lines.push([
      `Component ${component.component_id}.`,
      component.primitive ? `Primitive: ${component.primitive}.` : '',
      component.construction_method ? `Construction: ${component.construction_method}.` : '',
      component.operation ? `Operation: ${component.operation}.` : '',
      component.opacity !== null ? `Opacity: ${component.opacity}.` : '',
      component.required_visible_consequence ? `Visible consequence: ${component.required_visible_consequence}.` : '',
      component.creation_order !== null ? `Creation order: ${component.creation_order}.` : '',
      component.final_z_order !== null ? `Final z-order: ${component.final_z_order}.` : '',
    ].filter(Boolean).join(' '));
  }
  lines.push('This output is synthetic procedure-derived content, not authentic captured source evidence.');
  return lines.join('\n');
}
