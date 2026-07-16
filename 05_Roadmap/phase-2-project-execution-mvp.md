# Phase 2 Project Execution MVP

## Purpose

This note converts multi-issue orchestration research into a governed build path.
It is not authorization for autonomous issue-to-PR work.

## Source Of Truth

GitHub remains the durable source of truth for Agent OS governance, roadmap, tests,
and project execution state. Governance and validation override research guidance.

## Architecture Summary

Agent OS Phase 2 should add a Project Manager and Scheduler layer above workers.
GitHub issues become job requests. Workers may claim and validate bounded jobs, but
workers do not merge. The Merge Gate remains separate and approval-controlled.

Core components:

- Project Manager: selects ready issues and tracks project-level progress.
- Scheduler: orders queued jobs by dependency, priority, and safety.
- Worker Agents: perform bounded assigned work under existing governance.
- Issue Queue: stores pending job requests and dry-run execution state.
- Dependency Graph: blocks jobs until required predecessors are complete.
- Lease Manager: prevents duplicate worker claims.
- Validation Queue: records validation_pending, validation_passed, and validation_failed.
- Merge Gate: remains outside worker control.
- Approval Gate: remains required where governance requires approval.
- Navigation Registry: locates governed resources and approved lookup paths.
- Memory / Context Packets: preserve durable context before future live execution.
- Execution History: records queue, claim, block, validation, and review events.

## Reusable-Code Inventory

| Path | Current purpose | Reuse recommendation | Risk |
|---|---|---|---|
| `08_Tooling/workflow-scheduler/src/workflow_scheduler/models/task.py` | task states, leases, retries | adapt concepts | states differ |
| `08_Tooling/workflow-scheduler/src/workflow_scheduler/queue/job_queue.py` | priority queue | reuse pattern | lacks dependencies |
| `08_Tooling/workflow-scheduler/src/workflow_scheduler/dependencies/resolver.py` | dependency graph | adapt later | task-specific interface |
| `08_Tooling/workflow-scheduler/src/workflow_scheduler/audit/audit_logger.py` | audit events | reuse pattern | workflow-specific names |
| `08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/retry_manager.py` | retry timing | defer | not needed yet |
| `scripts/validate-all.sh` | aggregate validation | reuse directly | runner required |
| `.github/workflows/` | validation gate | reuse directly | runner must be online |
| `04_Registry/navigation/` | governed lookup map | adapt later | not needed for dry-run |

## Traceability Map

| Finding | Governance anchor | Component | MVP smoke test |
|---|---|---|---|
| Build scheduler, not smarter workers | GitHub Service Agent owns writes | Project Manager | ready queue |
| Issues are job requests | GitHub is source of truth | Issue Queue | two jobs ready |
| Workers do not merge | write authorization | Merge Gate | worker cannot mark merged |
| Prevent duplicate work | read-only default | Lease Manager | duplicate claim blocked |
| Respect dependencies | validation before merge | Dependency Graph | dependent job waits |
| Preserve auditability | final reports required | Execution History | audit events recorded |
| Keep orchestration dry-run | automation readiness | Dry-run MVP | no external writes |

## Phase 2 Epics And Codeable Issues

1. Project Manager Agent: define issue selection, scope boundaries, and stop rules.
2. Issue Queue: persist job requests, priorities, statuses, and ownership.
3. Dependency Graph: compute safe parallel sets and blocked jobs.
4. Worker Assignment: lease jobs, simulate worker claiming, and prevent duplicates.
5. Validation Queue: model validation state before review readiness.
6. Merge Gate: define merge-readiness without giving workers merge power.
7. Execution History: record queue, claim, block, validation, and review events.
8. Navigation Registry v2: map governed resources for project execution.
9. Memory / Context Packets: preserve long-running state and handoffs.
10. Dashboard / Reporting: summarize queued, running, blocked, and review-ready work.

Each issue should include purpose, scope, non-goals, likely files, dependencies,
acceptance criteria, smoke tests, risks, owner agent, and validation command.

## Implemented First Slice

The first slice is a dry-run project execution model inside Workflow Scheduler.
It models static jobs, dependency blocking, leases, validation state, review readiness,
and audit events. It performs no live GitHub, Notion, Google Drive, or merge writes.

## Non-Goals

- No live issue-to-PR automation.
- No autonomous coding worker.
- No autonomous merge.
- No Google Drive or Notion writes.
- No external DMSC repository changes.
- No dashboard or full worker pool.

## Validation Expectations

Run the Workflow Scheduler smoke tests and then `./scripts/validate-all.sh`.

## Recommended Next Issue

Add a fixture-backed issue queue loader that reads static GitHub issue fixtures and
feeds the dry-run model without using live GitHub writes.
