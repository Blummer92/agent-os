import { validateApplicationFidelity, type PromptCardModel } from './promptIntent';
import type { ReviewedTutorialProjection } from './types';

export type PreflightState = 'pass' | 'fail' | 'needs-review' | 'not-applicable';

export type PreflightRow = {
  id: string;
  label: string;
  state: PreflightState;
  detail: string;
};

export type ReadyContext = {
  fixtureId: string;
  requiredTests: readonly string[];
  nonGoals: readonly string[];
  definitionOfDone: readonly string[];
  unresolvedArchitectureDecision: boolean;
};

export type ReadyPreflightResult = {
  rows: readonly PreflightRow[];
  ready: boolean;
};

export type GitHubHandoffPacket = {
  packet_version: 'picture-perfect-ready-v1';
  fixture_id: string;
  recording_id: string;
  recording_sha256: string;
  modeling_source_refs: readonly string[];
  retained_steps: readonly {
    review_step_id: string;
    sequence: number;
    source_step_ids: readonly string[];
    semantic_action_ids: readonly string[];
    source_indexes: readonly number[];
    modeled_application: string;
  }[];
  excluded_step_ids: readonly string[];
  review_decisions: ReviewedTutorialProjection['review_decisions'];
  prompt_requirements: readonly {
    step_number: number;
    application: string;
    image_state: PromptCardModel['imageState'];
    portable_prompt: string;
    must_show: readonly string[];
    must_not_show: readonly string[];
    provenance: readonly string[];
  }[];
  provider_adapter_boundary: string;
  presentation_evidence_only: true;
  required_tests: readonly string[];
  non_goals: readonly string[];
  definition_of_done: readonly string[];
  execution_authorized: false;
};

function row(id: string, label: string, ok: boolean, detail: string): PreflightRow {
  return { id, label, state: ok ? 'pass' : 'fail', detail };
}

function modelingSourceRefs(cards: readonly PromptCardModel[]): string[] {
  return [...new Set(cards.flatMap((card) => card.provenance.filter((item) => item.startsWith('Teacher Modeling:'))))];
}

export function runReadyPreflight(
  tutorial: ReviewedTutorialProjection,
  cards: readonly PromptCardModel[],
  context: ReadyContext,
): ReadyPreflightResult {
  const sourceIdentityOk = Boolean(tutorial.recording_id.trim() && tutorial.recording_sha256.trim());
  const retainedStepsResolved = tutorial.retained_steps.length > 0;
  const provenanceOk = tutorial.retained_steps.every((step) =>
    step.source_step_ids.length > 0 &&
    step.semantic_action_ids.length > 0 &&
    step.source_indexes.length > 0 &&
    step.recording_id === tutorial.recording_id &&
    step.recording_sha256 === tutorial.recording_sha256,
  );
  const applicationsOk = tutorial.retained_steps.every((step) => Boolean(step.modeled_application?.trim()));
  const promptCardsOk = cards.length > 0 && cards.every((card) => card.status === 'ready' && validateApplicationFidelity(card).length === 0);
  const promptProvenanceOk = cards.every((card) => card.provenance.some((item) => item.startsWith('recording:')) && card.provenance.some((item) => item.startsWith('source_step:')));
  const modelingSources = modelingSourceRefs(cards);
  const modelingSourceOk = modelingSources.length > 0;
  const testsDefined = context.requiredTests.length > 0;
  const definitionDefined = context.definitionOfDone.length > 0;
  const fixtureAvailable = Boolean(context.fixtureId.trim());
  const architectureResolved = !context.unresolvedArchitectureDecision;

  const rows: PreflightRow[] = [
    row('recorder-source', 'Recorder source identified', sourceIdentityOk, sourceIdentityOk ? `${tutorial.recording_id} · ${tutorial.recording_sha256}` : 'Recording ID and fingerprint are required.'),
    row('modeling-source', 'Tutorial/modeling source identified', modelingSourceOk, modelingSourceOk ? modelingSources.join(' · ') : 'No approved Teacher Modeling source reference is present in prompt provenance.'),
    row('meaningful-actions', 'Meaningful actions resolved', retainedStepsResolved, retainedStepsResolved ? `${tutorial.retained_steps.length} retained instructional steps` : 'No retained instructional steps are available.'),
    row('review-resolved', 'No unresolved review item', tutorial.review_decisions.length > 0, tutorial.review_decisions.length > 0 ? `${tutorial.review_decisions.length} explicit review decisions` : 'Explicit review decisions are required.'),
    row('provenance', 'Source identity/fingerprint preserved', provenanceOk && promptProvenanceOk, provenanceOk && promptProvenanceOk ? 'Reviewed steps and prompt cards retain bounded source provenance.' : 'Required reviewed-step or prompt provenance is missing or inconsistent.'),
    row('application', 'Modeled application identity preserved where required', applicationsOk, applicationsOk ? 'Every retained software step has approved application identity.' : 'A retained software step is missing approved application identity.'),
    row('prompt-contract', 'Provider-neutral prompt contract validates', promptCardsOk, promptCardsOk ? `${cards.length} prompt cards validate` : 'One or more prompt cards are blocked or violate application/provider-neutral constraints.'),
    row('presentation-only', 'Prompt/image output remains presentation-only evidence', true, 'Ready and handoff output explicitly remain non-authorizing presentation guidance.'),
    row('golden-fixture', 'Golden fixture available', fixtureAvailable, fixtureAvailable ? context.fixtureId : 'A canonical privacy-safe fixture ID is required.'),
    row('tests', 'Required tests defined', testsDefined, testsDefined ? `${context.requiredTests.length} required tests` : 'Required validation tests are missing.'),
    row('definition-of-done', 'Definition of Done defined', definitionDefined, definitionDefined ? `${context.definitionOfDone.length} completion criteria` : 'Definition of Done is missing.'),
    row('architecture', 'No unresolved architecture decision', architectureResolved, architectureResolved ? 'No unresolved architecture decision is declared.' : 'An architecture decision remains unresolved.'),
  ];

  return { rows, ready: rows.every((item) => item.state === 'pass' || item.state === 'not-applicable') };
}

export function createGitHubHandoffPacket(
  tutorial: ReviewedTutorialProjection,
  cards: readonly PromptCardModel[],
  context: ReadyContext,
): GitHubHandoffPacket | null {
  const preflight = runReadyPreflight(tutorial, cards, context);
  if (!preflight.ready) return null;

  return {
    packet_version: 'picture-perfect-ready-v1',
    fixture_id: context.fixtureId,
    recording_id: tutorial.recording_id,
    recording_sha256: tutorial.recording_sha256,
    modeling_source_refs: modelingSourceRefs(cards),
    retained_steps: tutorial.retained_steps.map((step) => ({
      review_step_id: step.review_step_id,
      sequence: step.sequence,
      source_step_ids: step.source_step_ids,
      semantic_action_ids: step.semantic_action_ids,
      source_indexes: step.source_indexes,
      modeled_application: step.modeled_application ?? '',
    })),
    excluded_step_ids: tutorial.excluded_step_ids,
    review_decisions: tutorial.review_decisions,
    prompt_requirements: cards.map((card) => ({
      step_number: card.stepNumber,
      application: card.application,
      image_state: card.imageState,
      portable_prompt: card.portablePrompt,
      must_show: card.mustShow,
      must_not_show: card.mustNotShow,
      provenance: card.provenance,
    })),
    provider_adapter_boundary: 'Provider adapters may change execution syntax/settings only; they may not change application identity, instructional meaning, target state, must-show/must-not-show constraints, provenance, or modeled sequence.',
    presentation_evidence_only: true,
    required_tests: context.requiredTests,
    non_goals: context.nonGoals,
    definition_of_done: context.definitionOfDone,
    execution_authorized: false,
  };
}
