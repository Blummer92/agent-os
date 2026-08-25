# CKR6 Lessons Learned Preflight Contract

Issues: #1357, #1362

## Purpose

`lesson_preflight.py` is the bounded consumer seam that turns already-read, provider-neutral Lessons Learned evidence into the existing CKR2 coding-knowledge selection path before coding work begins or a failed implementation is repaired.

It does not read or write Notion itself.

```text
coding task / failed-PR repair / CI-diagnosis signals
-> plan_lesson_preflight(...)
-> not-needed: zero Notion retrieval
-> known reference: retrieve that bounded reference first
-> otherwise caller performs bounded read-only Lessons Learned query
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

`plan_lesson_preflight()` accepts a finite caller-supplied `LessonPreflightContext`.

For ordinary `coding-task` work it delegates the initial need decision to CKR2 by evaluating the request with zero candidates. If CKR2 reports `not-needed`, the plan returns `retrieval_required=false`; callers should perform no Notion lookup. If CKR2 identifies an explicit known knowledge reference, that bounded reference is retrieved before any filtered data-source query.

`failed-pr-repair` and `ci-diagnosis` are explicit material-use contexts. They require lesson retrieval even when the initial request has sparse library/path/capability signals. They preserve CKR2/CKR6A retrieval ordering: an explicit `known_knowledge_refs` value produces `KNOWN_REFERENCE` first; only when no known reference is available does the plan use the bounded filtered-data-source query. This prevents repair flows like #1350 from silently bypassing relevant testing, lineage, or failure-pattern lessons without regressing the current known-reference-first contract.

The context is caller-supplied deterministic evidence; CKR6 does not parse free-form language to infer it and does not add a second request interpreter.

The plan does not perform retrieval and does not create a second selector.

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

This applies to repair/diagnosis contexts too. A required lookup does not turn advisory Notion availability into repository authority or an unconditional blocker.

Missing retrieval never authorizes fabricated replacement guidance.

## Deterministic evidence

`LessonPreflightPlan` records whether retrieval is required and emits context-specific reason codes such as `lesson-retrieval-required:failed-pr-repair`, `lesson-retrieval-required:ci-diagnosis`, and their `lesson-known-reference-retrieval-required:*` equivalents when a known reference takes precedence.

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

## Validation

Focused tests in `tests/test_lesson_preflight.py` cover matching and unrelated tasks, zero-retrieval planning, ordinary and repair/diagnostic known-reference-first planning, filtered-query fallback, explicit failed-PR/CI-diagnosis material-use planning, #1350-style sparse repair signals, repair-path unavailable fallback, `Surface Before Work` filtering, archived rows, advisory `Needs follow-up`, GitHub authority conflicts, stale evidence, required-specialized-knowledge outage behavior, duplicate identity handling, bounded candidate sets, authority-claim rejection, determinism, existing handoff projection, and fixed no-write/no-authority behavior.
