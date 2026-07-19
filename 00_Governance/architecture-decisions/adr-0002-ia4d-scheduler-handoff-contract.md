# ADR 0002: IA4D to Workflow Scheduler Handoff Contract

## Status

Accepted for IA5A planning. Planning and contract design only. This ADR
does not implement a serializer, validator, Scheduler adapter, task
creation, approval storage, queueing, leasing, or dispatch.

## Context

IA4D (`evaluate_batch_plan()` in `scripts/agent_os_issue_acceptance/batch_planning.py`)
produces one point-in-time `BatchPlanningResult` for one supplied
`IssueBatchGraph`, with `planning_scope="supplied-graph-only"` and
`execution_authorized=False`. Workflow Scheduler
(`08_Tooling/workflow-scheduler/`) owns persistent tasks, approvals,
dependencies, leases, queues, adapters, and execution state. A direct
mapping such as `parallel-candidate -> run concurrently` is unsafe
because the graph, repository SHA, issue metadata, ownership, or
readiness may change between planning and dispatch. This ADR defines
the versioned, immutable, non-executable envelope that must sit between
IA4D and any future Scheduler ingestion issue, per #325.

## Decision

Define one frozen, deterministic `SchedulerPlanningHandoff` envelope.
Full field-by-field, serialization, and digest decisions are recorded in
`00_Governance/architecture-decisions/adr-0002-details-01-envelope-and-serialization.md`
and `adr-0002-details-01b-serialization-and-digest.md`. The freshness,
invalidation, and approval-binding model is recorded in
`adr-0002-details-02-freshness-and-approval.md` and
`adr-0002-details-02b-approval-and-audit.md` (same directory).

### Canonical location and ownership

- Canonical contract: this ADR pair, under `00_Governance/architecture-decisions/`.
- Owner: Integration Manager (per #325 and `02_Agent_Overlays/integration-manager.md`).
- Supporting agents: QA / Test Agent, GitHub Service Agent.
- Workflow Scheduler remains sole owner of task lifecycle and execution
  behavior; this contract does not extend or modify
  `08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md`.
- A future implementation registers as
  `IA4D-to-Scheduler Handoff Contract` in `04_Registry/module-version-map.md`.

### Classification boundary (non-authorization)

Only this mapping is defined, and it never authorizes work:

| IA4D classification | Handoff eligibility |
|---|---|
| `blocked` | not eligible for Scheduler ingestion |
| `needs-decision` | not eligible for Scheduler ingestion |
| `sequencing-review` | may appear in a reviewable draft handoff; creates no executable order |
| `parallel-candidate` | may be eligible for later revalidation; never authorizes concurrent execution |

No classification may create, approve, queue, lease, or dispatch a task,
select concurrency or worker counts, or bypass ownership,
source-of-truth, governed-field, production, or approval checks. The
envelope carries no credentials, tokens, mutable Scheduler objects,
adapters, callbacks, or write handles, and performs no filesystem,
network, GitHub API, database, or external-system I/O.

## Rejected Alternatives

- Direct classification-to-dispatch mapping: rejected because planning
  inputs (graph, SHAs, ownership, readiness) can change before approval.
- A mutable or Scheduler-owned handoff object: rejected because it would
  blur planning evidence with execution authority.
- Treating IA4D's `BatchPlanningResult` itself as the handoff: rejected
  because it lacks repository/branch/evaluator provenance and digesting;
  the envelope wraps it rather than replacing it.
- Trusting stored approvals indefinitely: rejected; see the freshness
  contract in details-02.

## Non-Goals (explicit exclusions)

This ADR does not authorize IA5B (serializer/validator), IA5C
(Scheduler draft-ingestion and revalidation), IA5D (approval binding and
invalidation implementation), or IA5E (controlled dispatch). Each
requires separate review and approval.

## Validation Expectations

- This ADR and its detail files each remain under the Markdown line limit.
- No runtime behavior changes are introduced by this ADR.
- `bash 07_Agent_Tests/validate-repo-structure.sh` and
  `./scripts/validate-all.sh` pass with only these documentation files
  added.
- A future implementation PR includes tests proving the envelope stays
  immutable, non-executable, and free of write handles.

## Version

0.1.0

## Changelog

- 0.1.0 accepted the `SchedulerPlanningHandoff` envelope, classification
  boundary, and non-authorization contract for IA5A (#325).
