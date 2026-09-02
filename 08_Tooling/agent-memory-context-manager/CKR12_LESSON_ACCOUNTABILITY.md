# CKR12 Lessons Learned Activation Accountability

Issues: #1517, #1559.

This contract adds a compact accountability layer over the live advisory
Lessons Learned catalog without duplicating that catalog into GitHub.

GitHub stores only:
- stable lesson identity
- explicit `activation_class`
- explicit `activation_readiness`
- bounded deterministic risk/contract -> lesson identity activation metadata

It does not store lesson prose, Guardrail, What Happened, or What To Do Next Time.

## Activation class

Finite reachability vocabulary:
- `signal-activatable`
- `known-reference-only`
- `context-only`
- `out-of-coding-scope`

## Activation readiness

Finite readiness vocabulary:
- `ready`
- `blocked-provenance`
- `blocked-vocabulary`
- `blocked-currentness`
- `blocked-conflict`
- `manual-review`

Reachability and readiness are deliberately orthogonal.

## Deterministic risk activation projection

#1559 adds one small projection from already-canonical #1537 risk identifiers to
stable lesson identities. The projection does not inspect changed files, infer
risk, classify review depth, retrieve Notion content, or select final coding
knowledge.

The checked-in mapping is deliberately sparse and bounded to at most three
lesson identities per risk. Unknown or unmapped risks produce `not-needed` and
zero lesson retrieval rather than broad search or heuristic matching. A mapped
identity must exist in the CKR12 accountability catalog and must remain both
`signal-activatable` and `ready`; otherwise it is blocked from ordinary signal
activation. The resulting ready IDs enter the existing CKR6 path only as known
references, where CKR11 live normalization and CKR2 currentness, provenance,
conflict, relevance, deduplication, bounds, and sufficiency still apply.

The initial mapping consumes current #1537 identifiers only:
- `authorization` -> `lesson-36`, `lesson-37`
- `permissions` -> `lesson-36`, `lesson-37`
- `workflow-ci-authority` -> `lesson-5`, `lesson-12`, `lesson-13`

These mappings are advisory context, not enforcement. Lessons cannot create or
change #1537 review depth and cannot grant CI pass/fail, validation, execution,
merge, closure, production, credential, permission, or external-write authority.

## Ownership boundaries

CKR12 does not normalize live Notion rows and does not select coding knowledge.

- #1537 owns deterministic review-risk and review-depth classification.
- CKR11 owns live Lessons Learned row normalization and finite vocabulary.
- CKR6 owns lesson-preflight planning and bounded lesson consumption.
- CKR2 owns relevance, deduplication, currentness, provenance sufficiency,
  conflicts, bounds, and selection.
- #1520 owns candidate-owned canonical provenance.
- #520 owns CI/build/validation runtime measurement.
- #1146 owns retrieval/context quality and benchmark evidence.

The accountability catalog and risk projection are validation/activation metadata
only. They create no authority.

## Initial live snapshot

The bounded read-only audit for #1517 on 2026-08-31 found 50 eligible,
non-archived rows with `Surface Before Work? = Yes`, identities `lesson-2`
through `lesson-51`.

The initial explicit dispositions are conservative:
- rows with a bounded `Applies To` signal are `signal-activatable`
- rows without that signal are `known-reference-only`
- rows missing candidate-owned `Source Link` provenance are
  `blocked-provenance`
- other rows are `ready`

Runtime CKR11/CKR6/CKR2 behavior remains authoritative. The accountability
validator does not reconstruct lesson meaning from prose.

## Drift validation

Ordinary tests are deterministic and network-free.

A bounded read-only live audit may compare current eligible lesson identities
with the checked-in accountability catalog to detect:
- newly eligible lessons missing accountability
- stale accountability for removed, archived, or non-surface lessons
- duplicate live identities

Risk mappings fail closed when they reference an identity absent from CKR12.
Readiness/class changes block the mapped identity from ordinary signal activation
until CKR12 accountability is intentionally reconciled. No broad Notion fallback
is triggered by an unknown risk or an empty projection.

No Notion write, schema change, synchronization job, workflow, background
process, second risk classifier, second lesson selector, semantic search mapping,
vector database, or RAG system is created.
