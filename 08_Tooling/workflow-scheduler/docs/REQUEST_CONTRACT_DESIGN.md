# Request-Side Adapter Contract Design

## Purpose
This document designs the future request-side adapter contract for Workflow Scheduler. It is docs-only and does not implement the contract or migrate adapters.

## Current State
Workflow Scheduler already formalizes adapter results with five states: `success`, `failure`, `retryable`, `blocked`, and `approval-required`. Adapter request inputs are still shaped by current task/ad hoc data passed by the executor.

## Problem
Without a formal request object, adapters can receive inconsistent context as new actions are added. A request-side contract should make adapter inputs predictable without expanding adapter authority or changing Scheduler ownership.

## Proposed Request Object
The request object should be immutable, or treated as immutable, after Scheduler creates it. Adapters may read it to execute one action safely. Adapters must return a result through the existing five-state result contract.

Example shape:

```python
{
    "task_id": "task-123",
    "action": "get_repo",
    "params": {"repository_full_name": "owner/repo"},
    "mode": "Gate",
    "approval_required": False,
    "approved": False,
    "retry_count": 0,
    "max_retries": 3,
    "created_at": "2026-07-13T00:00:00Z",
    "run_id": "run-abc",
    "audit_context": {"source": "scheduler"},
    "metadata": {},
}
```

## Required Fields
- `task_id`: Scheduler task identifier.
- `action`: adapter action to execute.
- `params`: action-specific input parameters.
- `mode`: current execution mode, such as Draft, Gate, or Production.
- `approval_required`: whether Scheduler requires approval before execution.
- `approved`: whether approval has already been granted.
- `retry_count`: current retry attempt count.
- `max_retries`: retry ceiling controlled by Scheduler.
- `created_at`: request creation timestamp.
- `run_id`: execution run identifier.
- `audit_context`: Scheduler-owned audit context.
- `metadata`: non-authoritative extra context.

## Optional Fields
Future helpers may add optional fields for trace IDs, source branch, PR number, idempotency keys, or adapter-specific hints. Optional fields must not be required for existing adapters during migration.

## Adapter Read Rules
Adapters may read `action`, `params`, execution mode, approval flags, retry metadata, and audit context. Adapters should use only the fields needed for one action and should ignore unknown fields.

## Adapter Must-Not Rules
Adapters must not mutate the request object, Scheduler task state, retry counters, approvals, leases, queue state, batches, lifecycle state, or audit records. Adapters must not infer extra authority from metadata.

## Approval Boundary
Scheduler remains the only owner of approval decisions. Write adapters may receive approval state, but they must not grant, bypass, or persist approvals. A request with `approval_required` and not `approved` should not execute a write action.

## Retry and Audit Metadata
Retry and audit fields are informational inputs for adapters. Scheduler owns retry scheduling, backoff, final failure, and audit persistence. Adapters may use retry count for safe remote behavior but must report outcomes through the result contract.

## Compatibility Strategy
Phase 4A is docs-only. Legacy adapter input shape remains supported during migration. Future code should introduce a bridge that can build a request object while still supporting adapters that expect existing task-shaped inputs.

## Future Migration Plan
- **Phase 4B**: introduce request object helpers without adapter migration.
- **Phase 4C**: add a compatibility bridge.
- **Phase 4D**: migrate fake/noop adapters first.
- **Phase 4E**: migrate read-only real adapters.
- **Phase 4F**: migrate approved write adapters.
- **Phase 4G**: update docs and registry after migration.

## Risks
- Accidentally giving adapters Scheduler authority.
- Breaking legacy adapters during migration.
- Treating metadata as authoritative state.
- Mixing request contract work with result contract changes.
- Expanding Phase 4 beyond a small staged migration.

## Non-Goals
No code implementation. No Executor changes. No TaskAdapter changes. No adapter migration. No Scheduler behavior changes. No REST API. No dashboard. No daemon. No production deployment. No Memory Manager work. No autonomous writes. No unrelated cleanup.