# ADR 0002 Details 1a: `planning_result_version`

Companion to `adr-0002-details-01-envelope-and-serialization.md`.

## What it identifies

`planning_result_version` is a semantic version for the
`BatchPlanningResult` / `PlanningClassification` output shape of
`evaluate_batch_plan()` in `scripts/agent_os_issue_acceptance/batch_planning.py`.
It is distinct from `contract_version` (the envelope shape) and from
`evaluator_commit_sha` (the exact code that ran).

## Initial value, owner, and location

No governance version for this shape exists yet. This ADR sets the
initial value to `0.1.0`. Owner: whoever owns `batch_planning.py`
changes — currently QA / Test Agent, per #322's implementation. The
canonical location for this version is this ADR's envelope definition
(`adr-0002-details-01-envelope-and-serialization.md`) until a concrete
consumer issue (IA5B) needs its own `04_Registry/module-version-map.md`
row; at that point, that row becomes canonical and this file is updated
to point to it rather than duplicate the value.

## Bump policy

Same rule as `contract_version`, applied to the planning-result shape
instead of the envelope shape:

- **MAJOR**: any `BatchPlanningResult` or `PlanningClassification`
  field removal, rename, or semantic change (for example, a new
  classification value, or a changed meaning for an existing one).
- **MINOR**: additive optional fields on either dataclass.
- **PATCH**: documentation-only clarifications with no shape change.

## Version discovery

IA5B discovers supported versions from its own declared allow-list,
never by probing `batch_planning.py` at runtime or importing Scheduler
or IA4D internals to infer a version. A `planning_result_version` value
outside that allow-list is `invalid` (see
`adr-0002-details-02-freshness-and-approval.md`).

## Why both `evaluator_commit_sha` and `planning_result_version` are required

`evaluator_commit_sha` identifies the exact code that ran.
`planning_result_version` identifies the shape that code is guaranteed
to have produced. Both are required because they can diverge
independently: the same `planning_result_version` can be produced by
multiple commits (for example, a bug-fix patch that does not change the
output shape), and a commit bump does not always change the version. A
revalidation consumer must check both, not treat one as a proxy for the
other.

## Version

0.1.0
