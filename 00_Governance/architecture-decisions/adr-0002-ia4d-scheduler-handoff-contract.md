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
because the graph, SHAs, ownership, or readiness may change between
planning and dispatch. This ADR defines the versioned, immutable,
non-executable envelope between IA4D and any future Scheduler
ingestion issue, per #325.

## Decision

Define one frozen, deterministic `SchedulerPlanningHandoff` envelope.
Field, serialization, and digest decisions are in the companion
`adr-0002-details-01*.md` files (envelope shape, serialization/digest,
graph-digest payload, handoff-digest) under the same directory.
Freshness, invalidation, and approval binding are in the
`adr-0002-details-02*.md` files.

### Canonical location and ownership

- Canonical contract: this ADR pair, under `00_Governance/architecture-decisions/`.
- Owner: Integration Manager (per #325, `02_Agent_Overlays/integration-manager.md`).
- Supporting agents: QA / Test Agent, GitHub Service Agent.
- Workflow Scheduler remains sole owner of task lifecycle/execution;
  this contract does not extend `08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md`.
- Already registered as `IA4D-to-Scheduler Handoff Contract` in
  `04_Registry/module-version-map.md` (contract design, not code),
  tracking this ADR's `## Version`. Implementation stays "not
  implemented" until IA5B lands; changes follow
  `00_Governance/standards-change-control.md`.

### Classification boundary (non-authorization)

Only this mapping is defined, and it never authorizes work:

| IA4D classification | Handoff eligibility |
|---|---|
| `blocked` | not eligible for Scheduler ingestion |
| `needs-decision` | not eligible for Scheduler ingestion |
| `sequencing-review` | may appear in a reviewable draft handoff; creates no executable order |
| `parallel-candidate` | may be eligible for later revalidation; never authorizes concurrent execution |

No classification may create, approve, queue, lease, or dispatch a task,
select concurrency/worker counts, or bypass ownership, source-of-truth,
governed-field, production, or approval checks. The envelope carries no
credentials, tokens, mutable Scheduler objects, adapters, callbacks, write handles, or any filesystem/network/GitHub/database/external-system I/O.

## Rejected Alternatives

- Direct classification-to-dispatch mapping: planning inputs (graph,
  SHAs, ownership, readiness) can change before approval.
- A mutable or Scheduler-owned handoff object: would blur planning
  evidence with execution authority.
- Treating `BatchPlanningResult` itself as the handoff: it lacks
  repository/branch/evaluator provenance and digesting; the envelope
  wraps it instead.
- Trusting stored approvals indefinitely: see the freshness contract.

## Non-Goals (explicit exclusions)

This ADR does not authorize IA5B (serializer/validator), IA5C
(Scheduler draft-ingestion/revalidation), IA5D (approval binding and
invalidation), or IA5E (controlled dispatch). Each requires separate
review and approval.

## Validation Expectations

- This ADR and its detail files each remain under the Markdown line limit.
- No runtime behavior changes are introduced by this ADR.
- `bash 07_Agent_Tests/validate-repo-structure.sh` and
  `./scripts/validate-all.sh` pass with only docs files changed.
- A future implementation PR includes tests proving the envelope stays
  immutable, non-executable, and free of write handles.

## Version

0.2.0

## Changelog

- 0.2.0 review-round fixes: exact serialization bytes, complete
  `graph_digest` payload, direct classification precedence, new
  `handoff_digest` field, `planning_result_version` ownership, and
  module-version-map wording (see new `-01c-`/`-01d-` files).
- 0.1.0 accepted the `SchedulerPlanningHandoff` envelope, classification
  boundary, and non-authorization contract for IA5A (#325).
