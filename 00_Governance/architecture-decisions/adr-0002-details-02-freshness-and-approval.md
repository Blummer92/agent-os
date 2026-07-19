# ADR 0002 Details 2: Freshness, Revalidation, and Approval Binding

Companion to `adr-0002-ia4d-scheduler-handoff-contract.md`. Envelope
shape and digesting are in `adr-0002-details-01-envelope-and-serialization.md`
and `adr-0002-details-01b-serialization-and-digest.md`. Approval binding
and audit evidence are in `adr-0002-details-02b-approval-and-audit.md`.

## Timestamp semantics

`created_at` is an RFC 3339 UTC timestamp recording when the envelope
was produced. It is provenance metadata only — a record of *when*, not
a source of truth about *whether the handoff still applies*.

**Time alone can never make a handoff stale.** A handoff produced one
minute ago against a repository SHA that has since changed is stale
immediately; a handoff produced a year ago against a SHA that is still
current `base_branch` HEAD, with an unchanged graph and unchanged
classifications, is still `fresh`. Freshness is always a function of
the ten checks below, never of elapsed wall-clock time.

## Outcome definitions

- **`fresh`**: every check in "Required revalidation checks" below
  passes; a future Scheduler ingestion issue may treat the handoff as
  current input (still not as approval or authorization).
- **`stale`**: one or more bound inputs (repository SHA, graph, node
  set, ownership, source-of-truth, or classification) has changed since
  the handoff was produced, but the handoff itself is structurally
  well-formed. A stale handoff must be discarded and IA4D re-run; it
  must never be silently "refreshed" by overwriting only the changed
  field.
- **`invalid`**: the handoff fails structural validation — unsupported
  version, missing required field, malformed digest, or partial node
  coverage (details-01). An invalid handoff is rejected before
  freshness is even evaluated.
- **`needs-decision`**: revalidation itself cannot be completed
  deterministically (for example, the evaluator commit is unresolvable,
  or ownership/source-of-truth input is unavailable). This is a human
  escalation state, distinct from `stale`, and must not be auto-resolved
  to `fresh`.

## Required revalidation checks (before any future Scheduler ingestion)

A future IA5C ingestion issue must perform all ten checks below before
creating any draft task from a handoff. Missing any one check means the
handoff cannot be treated as `fresh`:

1. Verify `contract_version` and `planning_result_version` are within
   the consumer's supported set.
2. Verify `evaluator_commit_sha` against an approved IA4D
   commit/release identity.
3. Reconstruct the current supplied graph from approved current inputs
   (not from the handoff's own `cohort_summaries`).
4. Recompute `graph_digest` from that reconstruction and compare.
5. Verify exact `supplied_node_ids` coverage against the reconstructed
   graph (no added or missing nodes).
6. Verify `evaluated_repository_sha` equals the current `base_branch`
   HEAD SHA.
7. Re-run IA4D (`evaluate_batch_plan`) against the current inputs.
8. Compare the freshly computed classifications against the handoff's
   `cohort_summaries`; any current classification that is *stronger*
   (per `_ORDER` in `batch_planning.py`: `blocked` > `needs-decision` >
   `sequencing-review` > `parallel-candidate`) than the stored one
   invalidates the handoff outright — the stronger, current result
   always wins.
9. Require current ownership-registry input
   (`04_Registry/ownership-matrix.md` or its successor) rather than
   trusting any ownership data implied by the handoff.
10. Require current source-of-truth conflict input rather than trusting
    any source-of-truth data implied by the handoff.

A handoff that fails any check is `stale` (if structurally valid) or
`invalid` (if not) and must be rejected, not repaired in place.

## Lower-risk classification changes

A classification moving to a *weaker* risk tier (for example
`sequencing-review` -> `parallel-candidate`) still requires new human
review before any future action. The freshness contract only automates
the *invalidating* direction (stronger wins, check 8); it never
auto-accepts a looser classification without review, because a looser
classification suggests the graph or scope shifted in a way that
warrants inspection.

## Version

0.1.0
