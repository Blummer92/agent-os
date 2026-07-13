# TaskAdapter Contract (Future Reference — Not Yet Implemented)

**Status:** Draft summary for a future phase (tentatively Phase 2G). Not
the current `TaskAdapter` interface; nothing in the codebase enforces
this. Phase 2F ("Adapter Readiness MVP") implements a much smaller,
non-breaking safety net instead — see `ARCHITECTURE.md`/`API_REFERENCE.md`
for what actually exists today, and `executor.py`'s
`_validate_adapter_result()` for the minimal validation Phase 2F added.

The full JSON-Schema request/result contract (immutable execution
request, `additionalProperties: false` result validation, five-state
`status` enum) is intentionally deferred to Phase 2G, once real external
adapters are closer to landing (tentatively Phase 2H). Do not implement
it without a dedicated, explicitly-scoped phase.

## Purpose

TaskAdapter is the execution boundary between the scheduler and a task
implementation. A future, formalized version would receive an immutable
task request, perform only the work the scheduler allows, and return one
structured result for scheduler classification.

## Required inputs (future)

An execution request would require: `task_id`, `owner`, `payload`, and an
`execution_context` object (`run_id`, `attempt_number`, plus optional
`batch_id`, `batch_metadata`, `retry_policy`, `approval_state`,
`pause_state`, `cancel_state`, `audit_context`). Either `task_name` or
`adapter_name` would also be required. The adapter would treat all of
this as read-only.

## Required outputs (future)

A result would require `status` and `message`, with optional `output`,
`metadata`, `error`, `retry_after`, `blocked_reason`, and
`approval_reason`. `status` would be the only classification signal,
one of: `success`, `failure`, `retryable` (requires `retry_after`),
`blocked` (requires `blocked_reason`), or `approval-required` (requires
`approval_reason`).

## Validation and classification rules (future)

The scheduler would validate every result before classification;
malformed/incomplete/unsupported results would be rejected through a
controlled failure path, never crash the scheduler loop, and always be
audit-logged. (Phase 2F already does a smaller version of this today —
see `_validate_adapter_result()`.)

## Governance (future, and already true today)

The scheduler owns lifecycle state, approval routing, retry policy,
pause/resume/cancel, batching/dispatch, audit logging, and result
classification. The adapter owns only permitted task execution and
returning a valid result — it must never mutate scheduler state, write
task/retry/approval/pause/cancel/queue records, bypass or self-authorize
approval, mark a task approved/completed/retried/paused/resumed/cancelled
on its own, or perform side effects outside its allowed boundary. An
approval-required task must resolve to `approval-required` and stop, not
be converted to success by the adapter.

## Implementation guidance (future)

Adapters should be deterministic where possible, keep side effects
isolated, and return structured results rather than raising for expected
outcomes. Fake adapters (Phase 2F: `adapters/fake_adapters.py`) can cover
success/failure/retryable/blocked/approval-required/slow paths without a
formal schema. Real external adapters should be addable later without
changing scheduler core logic, once this contract is formalized.

## Contract enforcement (future)

Any adapter violating this contract would be treated as invalid: handled
safely, audit-logged, and prevented from mutating scheduler state or
bypassing approval gates.
