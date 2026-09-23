# ADR 0002 Details 1: Envelope Shape and Versioning

Companion to `adr-0002-ia4d-scheduler-handoff-contract.md`.
`planning_result_version` ownership/bump policy is in
`adr-0002-details-01a-planning-result-version.md`. Serialization and
digest rules are in `adr-0002-details-01b-serialization-and-digest.md`.
Freshness, revalidation, and approval binding are in
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
    handoff_digest: str
```

`handoff_digest` is defined in `adr-0002-details-01d-handoff-digest.md`.
It is a field on the envelope, not a separately transported value, so
approval binding (details-02b) can reference one self-contained object.

Frozen dataclass (or equivalent immutable record); no setters, no
mutable collections (tuples only, mirroring `BatchPlanningResult`).

## Schema and compatibility versioning

- **`contract_version`**: semantic `MAJOR.MINOR.PATCH` string for the
  envelope shape itself, tracked in `04_Registry/module-version-map.md`
  once an implementation exists. MAJOR changes on any field removal,
  rename, or semantic change; MINOR on additive optional fields; PATCH
  on documentation-only clarifications.
- **`planning_result_version`**: a separate semantic version for the
  `BatchPlanningResult` / `PlanningClassification` output shape; see
  `adr-0002-details-01a-planning-result-version.md` for its initial
  value, ownership, location, and bump policy.
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

Repository/branch/evaluator identity and node-set/cohort-summary
representation are defined in
`adr-0002-details-01e-identity-and-node-set.md`.

## Version

0.2.0

## Changelog

- 0.2.0 added `handoff_digest`; moved `planning_result_version` and
  identity/node-set decisions to dedicated companion files.
- 0.1.0 initial envelope shape and versioning decisions.
