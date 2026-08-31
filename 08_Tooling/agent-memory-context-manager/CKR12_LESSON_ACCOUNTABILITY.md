# CKR12 Lessons Learned Activation Accountability

Issue: #1517.

This contract adds a compact accountability layer over the live advisory
Lessons Learned catalog without duplicating that catalog into GitHub.

GitHub stores only:
- stable lesson identity
- explicit `activation_class`
- explicit `activation_readiness`

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

## Ownership boundaries

CKR12 does not normalize live Notion rows and does not select coding knowledge.

- CKR11 owns live Lessons Learned row normalization and finite vocabulary.
- CKR6 owns lesson-preflight planning and bounded lesson consumption.
- CKR2 owns relevance, deduplication, currentness, provenance sufficiency,
  conflicts, bounds, and selection.
- #1520 owns candidate-owned canonical provenance.

The accountability catalog is validation metadata only. It creates no authority.

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

No Notion write, schema change, synchronization job, or background process is
created.
