# ADR 0002 Details 1d: `handoff_digest`

Companion to `adr-0002-details-01-envelope-and-serialization.md` (field
declaration) and `adr-0002-details-02b-approval-and-audit.md` (approval
binding, which requires this field).

## Why it exists

Approval binding (`adr-0002-details-02b-approval-and-audit.md`) requires
binding to a "handoff digest," but the original envelope had no field
identifying the exact transported artifact as a whole — only digests of
its `graph_digest` and `planning_result_digest` sub-parts. `handoff_digest`
closes that gap: it digests the complete envelope, so an approval can
bind to the exact bytes that crossed the IA4D-to-Scheduler boundary, not
just to two of its inputs.

## Definition

SHA-256, lowercase hex-encoded, computed over the canonical
deterministic JSON encoding
(`adr-0002-details-01b-serialization-and-digest.md`) of the complete
`SchedulerPlanningHandoff` payload, **including every envelope field
except `handoff_digest` itself**:

`contract_version`, `planning_result_version`, `evaluator_commit_sha`,
`repository`, `base_branch`, `evaluated_repository_sha`,
`supplied_node_ids`, `graph_digest`, `planning_result_digest`,
`cohort_summaries`, `planning_scope`, `execution_authorized`,
`created_at`.

This is the safest choice: it means approval binds to the *entire*
transported artifact, including its own provenance and timestamp, not
merely to the two content digests. Any change to any field — including
`created_at` — changes `handoff_digest` and therefore invalidates any
approval bound to the old value.

## Avoiding self-reference

`handoff_digest` is computed only after every other field is finalized,
then attached as the last step of constructing the envelope. The digest
input excludes the `handoff_digest` field itself (it is not yet set, or
is explicitly omitted from the digested object) — there is no
fixed-point requirement, no "digest of a digest," and no case where the
field's own bytes participate in its own computation. A validator
recomputing `handoff_digest` for revalidation does the same: build the
JSON payload of all other fields, hash it, and compare against the
stored `handoff_digest`; the recomputation never reads the stored
`handoff_digest` as an input.

## Version

0.1.0
