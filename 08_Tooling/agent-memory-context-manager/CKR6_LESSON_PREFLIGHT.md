# CKR6 Lessons Learned Preflight Contract

Issue: #1357. The live activation bridge described below is #1516 / CKR11.

## Purpose

`lesson_preflight.py` is the bounded consumer seam that turns already-read, provider-neutral Lessons Learned evidence into the existing CKR2 coding-knowledge selection path before coding work begins.

It does not read or write Notion itself.

```text
coding task signals
-> plan_lesson_preflight(...)
-> not-needed: zero Notion retrieval
-> otherwise caller follows the bounded CKR2 retrieval escalation
-> LessonRecordEvidence
-> consume_lesson_preflight(...)
-> existing CKR2 select_coding_knowledge(...)
-> existing CKR2 handoff projection
-> GitHub Service Agent / QA context
```

## Authority boundary

GitHub remains authoritative for Agent OS governance, code, tests, issue contracts, authorization, validation, and exact-head evidence.

Lessons Learned are advisory working knowledge only. The result reports `source_authority=advisory-only` and cannot create GitHub, Notion, merge, production, validation, readiness, or other authority.

A lesson marked `Needs follow-up` may be surfaced as a caution. It is not evidence that the corresponding repository rule has already been implemented.

## Retrieval planning

`plan_lesson_preflight()` delegates the initial need decision and retrieval escalation to the existing CKR2 contract by evaluating the request with zero candidates.

If CKR2 reports `not-needed`, the plan returns `retrieval_required=false`; callers should perform no Notion lookup.

When retrieval is required, callers use the cheapest bounded existing path first:

1. `known-reference` when the request already carries a stable lesson/knowledge reference;
2. otherwise `filtered-data-source-query`;
3. after an insufficient supplied result, the existing CKR2 escalation continues through `exact-narrow-lookup`, then bounded `workspace-search`, then `manual-review` only as needed.

CKR6 does not perform retrieval, invent a second escalation order, or create a second selector. Workspace search is an escalation path, not the ordinary retrieval path.

## Eligible lesson evidence

`consume_lesson_preflight()` accepts at most five already-normalized `LessonRecordEvidence` values.

A row is eligible for CKR2 candidate projection only when:

- `surface_before_work=true`;
- it is not archived;
- status is `New`, `Applied`, or `Needs follow-up`.

Currentness and authority conflicts are deliberately retained in the candidate so CKR2 can fail closed using its existing `stale-relevant-candidate`, `unverifiable-relevant-candidate`, and `canonical-authority-conflict` behavior.

The adapter does not silently turn stale or conflicting rows into current knowledge.

## CKR2 reuse

Each eligible row becomes the existing `CodingKnowledgeCandidate` type with:

- stable lesson identity;
- source revision;
- ecosystem/capability hints;
- next-time guidance and guardrail;
- canonical GitHub references;
- evidence references;
- currentness;
- authority-conflict evidence.

All ranking, deduplication, candidate-budget behavior, relevant-candidate selection, currentness handling, canonical-reference requirements, and sufficiency disposition remain owned by `select_coding_knowledge()` from #1144.

Per #1520, `sufficient` requires each retained selected Lesson candidate to carry its own `canonical_github_refs`; the caller's `request.canonical_rule_refs` is task/inspect-first evidence only and cannot satisfy a Lesson candidate's missing provenance. CKR6 adds no local duplicate provenance guard -- it inherits this invariant unchanged from CKR2.

CKR6 does not implement fuzzy ranking, embeddings, model scoring, a vector store, another RAG system, or a second context manager.

## Existing handoff packet

CKR6 reuses `CodingKnowledgeSelectionResult.to_handoff_projection()`.

Selected lessons therefore enter the existing Memory Manager concepts only through:

- `known_facts`;
- `prior_decisions` where CKR2 supplies them;
- `allowed_inspect_first` canonical GitHub refs;
- `stop_conditions` for insufficient/manual-review results.

No handoff-packet schema change is introduced.

## Retrieval unavailable behavior

If the read surface is unavailable:

- when specialized knowledge is explicitly required, result is `insufficient` with manual-review escalation;
- otherwise result is `unavailable-safe-fallback`, allowing a caller to continue using current GitHub authority alone when safe.

Missing retrieval never authorizes fabricated replacement guidance.

## Deterministic evidence

`LessonPreflightResult` exposes:

- `lesson_retrieval_status`;
- `candidate_count`;
- `selected_count`;
- `selected_lesson_ids`;
- `selection_reason_codes`;
- `canonical_github_refs`;
- `knowledge_refs`;
- `stale_or_conflicting_count`;
- `retrieval_escalation`;
- `source_authority=advisory-only`;
- the existing CKR2 handoff projection.

All authority/write flags remain false.

## External-effect boundary

This module performs zero:

- Notion reads;
- Notion writes;
- Notion schema/view/property changes;
- GitHub writes;
- Scheduler/background work;
- provider calls;
- credential access;
- production operations.

The caller owns bounded retrieval through an already-approved read surface. Any later external mutation remains separately authorization-gated.

## Live activation bridge (#1516 / CKR11)

`lesson_activation_bridge.py` is the runtime seam that turns real bounded
Lessons Learned Notion rows into `LessonRecordEvidence`, reusing the existing
read-only Notion query path (e.g. the Workflow Scheduler
`NotionReadOnlyAdapter.query_data_source` action) through an injected
`execute_read` callable. It creates no Notion client, credential, schema
mutation, or second retrieval system.

```text
CodingKnowledgeRequest
-> plan_lesson_preflight(...)
-> not-needed -> zero reads
-> known lesson reference -> build_known_reference_query(...) first
-> otherwise -> build_filtered_query(...) (page_size <= MAX_LESSON_RECORDS)
-> injected execute_read(...) (existing read-only Notion adapter)
-> normalize_lesson_row(...) per returned row (<= MAX_LESSON_RECORDS)
-> consume_lesson_preflight(...)
```

`orchestrate_lesson_activation(request, execute_read=...)` is the single
entry point. `execute_read=None` degrades to the existing
`retrieval_available=False` CKR6 fallback path unchanged.

### Deterministic normalization

`normalize_lesson_row()` maps the live controlled Notion properties
(`Lesson ID`, `Lesson Learned`, `Status`, `Surface Before Work?`, `Area`,
`Applies To`, `Learning Type`, `Source Link`, `Guardrail`,
`What To Do Next Time`, plus the page's `last_edited_time`) into
`LessonRecordEvidence`, or returns an explicit `LessonActivationSkip(lesson_id,
reason)` when evidence is missing or ambiguous. It never invents
`ecosystem`, `capability_kind`, or keyword values:

- `Lesson ID` supplies the stable logical identity, never the Notion page URL;
- `last_edited_time` supplies `source_revision`;
- `Area` and `Learning Type` map through finite deterministic vocabularies to
  `ecosystem`/`capability_kind`; an unrecognized value fails closed as
  `ambiguous-area-vocabulary` / `ambiguous-learning-type-vocabulary`;
- `Status` must be one of the live finite values; anything else fails closed
  as `ambiguous-status-vocabulary`;
- `Source Link` supplies the lesson's own `canonical_github_refs` only when it
  is a recognized GitHub/repository-path reference; a missing or
  unrecognized link normalizes to `currentness=unverifiable` with an empty
  `canonical_github_refs` tuple rather than fabricating provenance -- CKR2's
  shared candidate-provenance invariant (#1520) then fails it closed with no
  Lessons-specific duplicate guard;
- oversized or malformed collections/text are rejected (`oversized-or-malformed-field`)
  rather than truncated silently.

Rows that cannot be mapped safely are excluded from the candidate set as
explicitly non-ready; they are accounted for by #1517 / CKR12, not retried or
guessed here.

### Bounded retrieval

`build_known_reference_query()` and `build_filtered_query()` both request
only the required properties and cap `page_size` at `MAX_LESSON_RECORDS`.
`orchestrate_lesson_activation()` additionally rejects (via
`LessonActivationError`) any executor response carrying more than
`MAX_LESSON_RECORDS` rows before normalization, so the full Lessons Learned
catalog can never reach `consume_lesson_preflight()`.

## Validation

Focused tests in `tests/test_lesson_preflight.py` and
`tests/test_lesson_activation_bridge.py` cover matching and unrelated tasks, zero-retrieval planning, known-reference-first planning, filtered-query fallback, `Surface Before Work` filtering, archived rows, advisory `Needs follow-up`, GitHub authority conflicts, stale evidence, Notion-unavailable fallback, required-specialized-knowledge outage behavior, duplicate identity handling, bounded candidate sets, authority-claim rejection, determinism, existing handoff projection, and fixed no-write/no-authority behavior.
