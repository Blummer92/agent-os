# CKR10 Decision / ADR Retrieval Preflight

Issue: #1369

## Purpose

`decision_preflight.py` is the bounded, provider-neutral consumption seam for already-read Decision Log / ADR evidence. It lets the coding workflow decide whether prior decisions are materially useful before substantial reasoning, normalize at most five supplied records, delegate selection to the existing CKR2 selector, retain at most three decisions, and project them through existing Memory Manager fields.

```text
coding task
-> plan_decision_preflight
-> not-needed: zero Decision Log lookup
-> otherwise bounded read-only Decision evidence
-> consume_decision_preflight
-> existing CKR2 selector/sufficiency/currentness
-> existing prior_decisions / known_facts / allowed_inspect_first / stop_conditions
-> current GitHub verification before reliance
```

## Dependency contract consumed

#1367 froze the first-wave Decision index contract and positive/negative retrieval scenarios. #1368 supplied the bounded real Decision Log index: 18 GitHub-backed rows, 17 current/Accepted and one superseded naming record. Those records are secondary retrieval/index knowledge only.

## Reuse

CKR10 deliberately reuses:

- #1144 `CodingKnowledgeRequest`, `CodingKnowledgeCandidate`, deterministic selection, five-candidate budget, three-selected budget, currentness, canonical GitHub references, sufficiency, deduplication, and retrieval escalation;
- #937 / PR #970 `prior_decisions` as an existing bounded context concept;
- #1357 / PR #1358's preflight shape: plan first, consume already-read normalized evidence, safe outage behavior, and GitHub-over-Notion authority;
- the existing Memory Manager handoff projection rather than a second packet or context manager.

It creates no connector, selector, memory system, RAG/vector system, database, persistence layer, Scheduler path, background worker, or agent.

## Decision-sensitive planning

`plan_decision_preflight(...)` returns retrieval required only when explicit bounded task signals are decision-sensitive or specialized knowledge is explicitly required. Signals include architecture/contracts, ownership/routing, source-of-truth, authorization/permissions, workflow/validation, parser semantics, canonical naming, governance, and supersession. Explicit `specialized_knowledge_required=False` returns `not-needed` and performs zero Decision Log retrieval.

## Candidate semantics

`DecisionRecordEvidence` preserves stable decision identity, source revision, title, domain, status, currentness, compact summary, canonical GitHub references, evidence references, retrieval keywords, applicability scope, successor references, and authority-conflict evidence.

Accepted/Active records may be normalized into CKR2 candidates. Proposed/Exploratory/Working records remain unresolved and cannot become repository authority. Superseded/Deprecated records are never selected as the active answer; a known successor is surfaced as the next canonical reference. Stale, unverifiable, authority-conflicting, duplicate-conflicting, and oversized evidence fails closed.

## Authority and currentness

Every result fixes `source_authority` to `secondary-index`. Selected Decision Log material is context evidence only. `verification_required` is true when canonical GitHub references must be inspected. Notion `Accepted` can never override current GitHub code, tests, standards, issue contracts, supersession, ownership, authorization, or exact-head validation.

Decision text cannot grant merge, write, production, approval, validation, or other authority. The module performs no Notion or GitHub mutation.

## Request/task authority vs. candidate-owned provenance (#1520)

`request.canonical_rule_refs` is caller-owned task-authority / inspect-first evidence and never satisfies a Decision candidate's own provenance requirement. `sufficient` requires each retained selected Decision candidate to carry its own `canonical_github_refs`; CKR10 inherits this from CKR2 without an adapter-local duplicate guard. `DecisionPreflightResult.verification_required` is derived from the selected candidates' own references, not from the merged/request-inclusive `canonical_github_refs` field, so it does not become `True` merely because `request.canonical_rule_refs` is non-empty.

## Outage behavior

When Decision retrieval is unavailable and specialized prior-decision knowledge is not explicitly required, CKR10 returns `unavailable-safe-fallback` so the caller may continue from GitHub-only authority when safe. When specialized knowledge is required, it returns explicit insufficiency/manual review and never fabricates replacement guidance.

## Existing handoff projection

Selected decision identities project into the existing `prior_decisions` field. Canonical GitHub references project into `allowed_inspect_first`; source-authority evidence projects into `known_facts`; insufficiency/manual-review reasons project into `stop_conditions`. Decision/Lesson/Pattern evidence remains semantically distinct and is not recursively crawled.

## Benchmark handoff to #1146

Representative benchmark scenarios:

1. connector architecture task retrieves the canonical Navigation Registry decision before broad investigation;
2. Notion Accepted conflicts with GitHub supersession and fails closed;
3. Scheduler planning task retrieves the planning-vs-execution authority boundary;
4. old-but-current freshness decision remains eligible despite age;
5. routine mechanical task returns `not-needed` with zero Decision Log retrieval;
6. Decision retrieval unavailable but GitHub is sufficient returns safe fallback;
7. Decision retrieval unavailable when specialized prior-decision knowledge is required returns insufficiency.

#1146 remains the empirical benchmark owner. CKR10 tests prove bounded deterministic behavior, not token or compute savings.

## External-effect boundary

CKR10 is pure/offline consumption. It performs no Notion write, schema/view/property change, GitHub mutation, Scheduler action, persistence write, workflow change, protected-setting change, production action, credential/IAM operation, scheduled sync, or background work.
