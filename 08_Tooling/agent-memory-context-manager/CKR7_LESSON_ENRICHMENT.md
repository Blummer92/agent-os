# CKR7 Lesson Enrichment and Consolidation Contract

Issue: #1364

## Purpose

`lesson_enrichment.py` is the pure/offline maintenance seam for already-qualified Lessons Learned. It accepts one bounded current lesson, explicit bounded related GitHub evidence, and optionally a bounded set of compatible lesson candidates. It emits a deterministic, authority-false revision proposal and performs no external writes.

```text
current lesson
+ explicit related GitHub evidence
+ optional bounded compatible lessons
-> unchanged | enrich-existing | consolidate-compatible | supersede-existing
   | distinct-lesson | manual-review | insufficient-evidence
-> authority-false LessonRevisionProposal
-> optional existing CKR6 LessonRecordEvidence projection
-> separately authorized writer, if ever approved
```

## Authority and source of truth

GitHub remains authoritative for code, tests, standards, issue/PR/commit evidence, currentness, authorization, and validation. Lessons Learned remain advisory working knowledge. A revision proposal cannot create write, merge, readiness, validation, production, or publication authority.

Every proposal fixes these fields to false:

- `authority_created`
- `side_effects_performed`
- `notion_write_performed`
- `github_external_mutation_performed`
- `publication_or_revision_authorized`

The module performs no Notion, GitHub, network, provider, Scheduler, credential, filesystem, or production operation.

## Deterministic relationship evidence

The caller must classify supplied GitHub evidence using the finite `EvidenceEffect` vocabulary:

- `confirms`
- `improves-root-cause`
- `adds-guardrail`
- `supersedes`
- `distinct-cause`
- `contradicts`
- `incidental`

This contract does not discover relationships and does not use embeddings, vector similarity, fuzzy matching, or model-scored canonical identity. Ambiguous or contradictory evidence fails closed.

## Dispositions

- `unchanged`: no guidance rewrite is justified; confirming evidence may still be added to provenance.
- `enrich-existing`: explicit evidence improves root cause or reusable guardrail.
- `consolidate-compatible`: bounded candidate lessons have compatible ecosystem/capability/library and identical normalized next-time guidance/guardrail; provenance is unioned and retrieval-record count can shrink.
- `supersede-existing`: current GitHub evidence explicitly invalidates the old guidance; the proposed old synthesis becomes stale and non-surfaceable while retaining its identity.
- `distinct-lesson`: the evidence or candidate proves materially different reusable guidance/cause.
- `manual-review`: contradiction, authority conflict, stale candidate, mixed rewrite/supersession, or budget ambiguity prevents a safe decision.
- `insufficient-evidence`: only incidental relationship evidence exists.

## Provenance preservation

Revision proposals retain:

- stable lesson identity;
- originating references;
- prior and newly supplied canonical GitHub references;
- evidence references;
- new supporting issue/PR/commit references;
- consolidated lesson identities;
- superseded identity where applicable;
- deterministic revision reason codes.

No historical record is deleted by this contract.

## CKR6 reuse

A safe current proposal can project directly to the existing `LessonRecordEvidence` type through `to_lesson_record_evidence()`. This keeps CKR6 as the existing consumption path and avoids a second selector or context packet.

Superseded proposals project as stale and `surface_before_work=false`, so CKR6 cannot treat them as current pre-work guidance. Manual-review, insufficient, and distinct-lesson outcomes do not project as a replacement lesson.

## Boundedness and compute/noise evidence

The contract accepts at most eight related evidence records and five consolidation candidates. Reference unions are bounded to twenty values. Budget overflow fails closed to manual review.

`LessonEnrichmentResult` exposes deterministic maintenance metrics:

- `candidate_lessons_considered`
- `lessons_consolidated`
- `canonical_refs_preserved`
- `estimated_retrieval_records_before`
- `after_current_synthesis_count`
- `manual_review_count`

These are local evidence for later benchmarking; they do not create a second compute-measurement owner.

## External-write boundary

This issue implements proposal generation only. Live Notion updates, bulk historical enrichment/backfill, scheduled synchronization, inference-driven row mutation, schema changes, deletion, and irreversible record merges remain separately authorization-gated.
