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
3. after an insufficient result, `exact-narrow-lookup`;
4. after another insufficient result, the final bounded `workspace-search` slot;
5. `manual-review` after every executable step has been attempted.

#2141 makes that existing CKR2 ledger executable for the Lessons Learned provider in `lesson_retrieval_orchestrator.py`. Each provider call is recorded on an immutable `CodingKnowledgeRequest.attempted_retrieval` copy before CKR2 chooses the next step, so a recommendation can never name the query that was just executed. The loop is capped by `MAX_ESCALATION_STEPS` and therefore cannot retry indefinitely.

For this provider, the CKR2 `workspace-search` slot is implemented conservatively as the broadest bounded query **inside the canonical Lessons Learned data source**. It is not a raw Notion workspace search. This preserves #2141's prohibition on a second retrieval mechanism while retaining CKR2's finite escalation semantics.

## Eligible lesson evidence

`consume_lesson_preflight()` accepts at most five already-normalized `LessonRecordEvidence` values.

A row is eligible for CKR2 candidate projection only when:

- `surface_before_work=true`;
- it is not archived;
- status is `New`, `Applied`, or `Needs follow-up`.

Currentness and authority conflicts are deliberately retained in the candidate so CKR2 can fail closed using its existing `stale-relevant-candidate`, `unverifiable-relevant-candidate`, and `canonical-authority-conflict` behavior.

The adapter does not silently turn stale or conflicting rows into current knowledge.

## CKR2 reuse

Each eligible row becomes the existing `CodingKnowledgeCandidate` type with stable lesson identity, source revision, ecosystem/capability hints, next-time guidance and guardrail, canonical GitHub references, evidence references, currentness, and authority-conflict evidence.

All ranking, deduplication, candidate-budget behavior, relevant-candidate selection, currentness handling, canonical-reference requirements, and sufficiency disposition remain owned by `select_coding_knowledge()` from #1144.

Per #1520, `sufficient` requires each retained selected Lesson candidate to carry its own `canonical_github_refs`; the caller's `request.canonical_rule_refs` is task/inspect-first evidence only and cannot satisfy a Lesson candidate's missing provenance. CKR6 adds no local duplicate provenance guard -- it inherits this invariant unchanged from CKR2.

CKR6 does not implement fuzzy ranking, embeddings, model scoring, a vector store, another RAG system, or a second context manager.

## Existing handoff packet

CKR6 reuses `CodingKnowledgeSelectionResult.to_handoff_projection()`. Selected lessons therefore enter the existing Memory Manager concepts only through `known_facts`, `prior_decisions` where CKR2 supplies them, `allowed_inspect_first` canonical GitHub refs, and `stop_conditions` for insufficient/manual-review results. No handoff-packet schema change is introduced.

## Retrieval unavailable behavior

If the read surface is unavailable, when specialized knowledge is explicitly required the result is `insufficient` with manual-review escalation; otherwise the result is `unavailable-safe-fallback`, allowing a caller to continue using current GitHub authority alone when safe. Missing retrieval never authorizes fabricated replacement guidance. #2142 separately owns any change to the blocking classification for this condition.

## Deterministic evidence

`LessonPreflightResult` exposes `lesson_retrieval_status`, candidate and selected counts, selected lesson identities, selection reason codes, canonical GitHub refs, knowledge refs, stale/conflicting count, retrieval escalation, `source_authority=advisory-only`, and the existing CKR2 handoff projection. All authority/write flags remain false.

## External-effect boundary

The memory/context package itself performs zero Notion writes, Notion schema/view/property changes, GitHub writes, credential mutations, or production operations. The caller owns bounded retrieval through an already-approved read surface. Any later external mutation remains separately authorization-gated.

## Live activation bridge (#1516 / CKR11)

`lesson_activation_bridge.py` turns real bounded Lessons Learned Notion rows into `LessonRecordEvidence`, reusing the existing read-only `NotionReadOnlyAdapter.query_data_source` path through an injected `execute_read` callable. It creates no Notion client, credential, schema mutation, or second retrieval system.

`lesson_retrieval_orchestrator.py` composes those existing query and normalization helpers with CKR2's existing escalation ledger. `repair_lesson_activation.py` uses that bounded orchestrator for failed-repair/CI re-entry. `execute_read=None` still degrades to the existing CKR6 unavailable path.

### Deterministic normalization

`normalize_lesson_row()` maps only the controlled live Notion properties into `LessonRecordEvidence`, or returns an explicit `LessonActivationSkip` when evidence is missing or ambiguous. It never invents ecosystem, capability, keyword, provenance, or currentness evidence. Rows that cannot be mapped safely are excluded from the candidate set as explicitly non-ready; they are accounted for by #1517 / CKR12, not guessed here.

### Bounded retrieval

Provider responses are capped by `MAX_RETRIEVAL_ROWS`, and the selector receives at most `MAX_LESSON_RECORDS` after deterministic relevance narrowing. The executable escalation sequence has a fixed maximum of four calls when a known reference exists and three otherwise. Exhaustion terminates at CKR2 `manual-review`; no query can repeat indefinitely because every executed step is recorded before the next recommendation is calculated.

## Validation

Focused tests in `tests/test_lesson_preflight.py`, `tests/test_lesson_activation_bridge.py`, and `tests/test_lesson_retrieval_orchestrator.py` cover zero-retrieval planning, known-reference-first planning, task-filtered retrieval, exact-narrow distinction, immutable attempt-ledger advancement, bounded escalation exhaustion, unavailable-source behavior, normalization, candidate narrowing, authority/currentness handling, and fixed no-write/no-authority behavior.
