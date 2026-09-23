# CKR6 Notion Engineering-Learning Backfill Contract

Issue: #1354

## Purpose

CKR6 is a pure, repository-local projection and planning seam between CKR5 lesson decisions and a later separately authorized Notion operation. It does not retrieve from or write to Notion.

```text
canonical GitHub bug / investigation evidence
-> CKR5 bounded failure observation
-> CKR5 qualification + deterministic lesson identity
-> CKR6 non-authoritative Notion record proposal
-> paginated historical backfill plan or post-resolution proposal
-> later separately authorized Notion operation
```

GitHub remains canonical for issue state, implementation, PRs, validation, resolution, and lesson evidence. Notion is working knowledge only.

## Inclusion policy

Include only CKR5 results classified `reusable-new` or `reusable-recurrence` with canonical GitHub and evidence references. High-value candidates include silent-correctness/parser defects, CI/configuration drift, acceptance/orchestration failures, lifecycle/authorization edge cases, recurring validation failures, and diagnosis patterns that materially improve future work.

Skip CKR5 `non-reusable` and `insufficient-evidence` results. Preserve `manual-review` rather than guessing. Trivial corrections, ordinary one-offs, transient environment failures, flaky noise without reusable guidance, and already-canonical rules with no distinct operational lesson do not become learning records automatically.

## Record proposal

A proposal carries bounded concepts for title, component, symptom, diagnosis/root-cause evidence, next-time resolution guidance, prevention guardrail, learning type, severity, owner, source reference, canonical GitHub refs, evidence refs, recurrence count, and surface-before-work recommendation.

Symptom and diagnosis are deliberately distinct. CKR5's `what_happened` supplies the symptom. A caller may supply a separate bounded `root_cause_or_diagnosis` only when canonical evidence supports it. CKR6 never copies the symptom into the diagnosis field and never invents a root cause. If no distinct diagnosis is supplied, the proposal records `None` and adds `root-cause-or-diagnosis-not-supplied` evidence for downstream review.

The proposal explicitly records:

```text
source_of_truth=GitHub
notion_role=non-authoritative-working-knowledge
authority_created=false
side_effects_performed=false
notion_write_performed=false
publication_authorized=false
```

The projection does not claim a Notion page ID, database status, authoritative resolution status, or write success.

## Identity, duplicates, and recurrence

CKR5 owns deterministic lesson identity and recurrence classification. CKR6 must not create a second fingerprint or fuzzy matcher.

- `reusable-new` -> propose `create`.
- `reusable-recurrence` -> preserve CKR5 `increment-recurrence` and proposed recurrence count.
- duplicate lesson identities anywhere in the supplied historical backfill set -> `manual-review`; do not allow pagination to hide a cross-page duplicate.
- duplicate cleanup, destructive merge, or historical rewrite in Notion remains separately authorization-gated.

## Historical backfill procedure

1. Gather bounded canonical GitHub evidence for candidate resolved bugs or investigations.
2. Normalize each candidate through the existing CKR5 `FailureObservation` contract.
3. Run CKR5 qualification and deterministic identity/recurrence handling.
4. Supply the complete bounded result set to CKR6 and request a page by `offset`.
5. CKR6 projects at most `MAX_BACKFILL_BATCH_SIZE` records in one page and returns `next_offset` when more remain.
6. Continue requesting pages until `complete=true`.
7. Review `eligible`, `recurrence`, `skip`, and `manual-review` outcomes.
8. Treat the resulting plans as handoffs only. Any actual Notion mutation requires separate current authorization and destination verification.

`MAX_BACKFILL_BATCH_SIZE = 50` is a per-call processing bound, **not a global historical limit**. A backfill of 57, 500, or more qualified historical candidates can be planned through successive pages. Pagination does not authorize writes and does not bypass duplicate/manual-review safeguards.

## Post-resolution capture

Future bug completion can use the same CKR5 -> CKR6 path after canonical resolution evidence exists. Capture is not automatic merely because an issue closes. The lesson must independently satisfy CKR5 reusable-learning requirements.

## External-write and schema boundary

CKR6 performs no Notion/GitHub/network/provider/Scheduler/credential/production access and changes no Notion database, schema, view, property, relation, formula, sharing setting, governed field, or source-of-truth designation.

Actual Notion row creation/update, bulk synchronization, automated row-writing, scheduled mutation, duplicate cleanup, schema changes, or governed-field changes remain subject to `00_Governance/write-authorization-policy.md` and the live destination/owner contract.

## Validation

Focused tests verify eligible projection, distinct diagnosis preservation, missing-diagnosis evidence, non-reusable skip, manual-review preservation, cross-set duplicate rejection, pagination beyond 50 candidates, fixed non-authority evidence, and canonical GitHub reference preservation.
