# ADR 0002 Details 1: Envelope Shape and Versioning

Companion to `adr-0002-ia4d-scheduler-handoff-contract.md`. Serialization
and digest rules are in
`adr-0002-details-01b-serialization-and-digest.md`. Freshness,
revalidation, and approval binding are in
`adr-0002-details-02-freshness-and-approval.md`.

## Envelope shape

```python
@dataclass(frozen=True)
class HandoffCohort:
    node_ids: tuple[str, ...]
    classification: str          # PlanningClassification.value
    reason_codes: tuple[str, ...]

@dataclass(frozen=True)
class SchedulerPlanningHandoff:
    contract_version: str
    planning_result_version: str
    evaluator_commit_sha: str
    repository: str
    base_branch: str
    evaluated_repository_sha: str
    supplied_node_ids: tuple[str, ...]
    graph_digest: str
    planning_result_digest: str
    cohort_summaries: tuple[HandoffCohort, ...]
    planning_scope: Literal["supplied-graph-only"]
    execution_authorized: Literal[False]
    created_at: str
```

Frozen dataclass (or equivalent immutable record); no setters, no
mutable collections (tuples only, mirroring `BatchPlanningResult`).

## Schema and compatibility versioning

- **`contract_version`**: semantic `MAJOR.MINOR.PATCH` string for the
  envelope shape itself, tracked in `04_Registry/module-version-map.md`
  once an implementation exists. MAJOR changes on any field removal,
  rename, or semantic change; MINOR on additive optional fields; PATCH
  on documentation-only clarifications.
- **`planning_result_version`**: a separate semantic version identifying
  the `BatchPlanningResult` / `PlanningClassification` shape IA4D
  produced. Decoupling the two lets the envelope evolve without forcing
  an IA4D re-release, and vice versa.
- **Unknown-field compatibility**: a future validator (IA5B) must accept
  unknown *optional* fields it does not recognize (forward
  compatibility) but must fail closed on unknown *required* fields or an
  unrecognized `contract_version` major component.
- **Unsupported-version behavior**: any `contract_version` or
  `planning_result_version` outside the validator's declared supported
  set is `invalid` (see details-02), never silently coerced or upgraded.
- **Missing-field / malformed-digest behavior**: a missing required
  field, an empty `supplied_node_ids`, or a digest that fails the
  encoding check in details-01b is `invalid` and fails closed. Partial
  graph coverage (a cohort referencing a node absent from
  `supplied_node_ids`, or vice versa) is `invalid` for the same reason
  `BatchPlanningResult.__post_init__` already rejects it at the IA4D
  layer.

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
  required from source (details-02), not trusted from the summary.

## Version

0.1.0
