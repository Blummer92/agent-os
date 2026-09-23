# ADR 0002 Details 1e: Identity and Node-Set Representation

Companion to `adr-0002-details-01-envelope-and-serialization.md`.

## Repository, branch, and evaluator identity

- **`repository`**: `"<owner>/<repo>"` (matches the GitHub MCP tool
  convention already used across this repository, e.g.
  `Blummer92/agent-os`).
- **`base_branch`**: the exact branch name the graph was evaluated
  against (e.g. `main`), never a ref expression or wildcard.
- **`evaluated_repository_sha`**: the full 40-character commit SHA of
  `base_branch` at evaluation time — not a short SHA, not a tag.
- **`evaluator_commit_sha`**: the full commit SHA of the IA4D
  implementation (`batch_planning.py` and its direct dependencies) used
  to produce the result, so a later revalidation can detect evaluator
  drift independent of repository content drift.

## Node set and cohort-summary representation

- **`supplied_node_ids`**: the exact, sorted tuple of node ids IA4D was
  given — copied verbatim from `BatchPlanningResult.supplied_node_ids`,
  never re-derived or filtered by the envelope layer.
- **`cohort_summaries`**: one `HandoffCohort` per `PlanningCohort`,
  carrying only `node_ids`, `classification`, and `reason_codes` —
  never `dependency_pairs` or `sequencing_pairs` verbatim beyond what a
  reviewer needs to see the grouping; a full graph reconstruction is
  required from source
  (`adr-0002-details-02-freshness-and-approval.md`), not trusted from
  the summary.

## Version

0.1.0
