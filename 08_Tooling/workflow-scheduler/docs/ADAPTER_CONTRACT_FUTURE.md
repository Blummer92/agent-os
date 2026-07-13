# TaskAdapter Contract (Result Side Implemented; Request Side Future)

**Status:** The five-state **result** contract below (`status`/`message`,
Phase 3D) is implemented today, additively — see `executor.py`'s
`_validate_adapter_result()` / `_validate_contract_result()` /
`_handle_contract_result()`, and `FakeContractAdapter` in
`adapters/fake_adapters.py` for a reference example. It is fully
backward compatible: every real and fake adapter still returns the
original `success`/`error`/`is_transient` shape unchanged, and nothing
is required to migrate. The **request** side (an immutable execution
request replacing the raw `Task` passed to `execute()`, with an
`execution_context` object) is still future work, deferred because it
would require changing the `TaskAdapter.execute()` signature — and
therefore every existing adapter — in one breaking phase. Do not
implement it without a dedicated, explicitly-scoped phase.

## Purpose

TaskAdapter is the execution boundary between the scheduler and a task
implementation. It receives a task, performs only the work the scheduler
allows, and returns one structured result for scheduler classification.

## Required inputs (still future)

An execution request would require: `task_id`, `owner`, `payload`, and an
`execution_context` object (`run_id`, `attempt_number`, plus optional
`batch_id`, `batch_metadata`, `retry_policy`, `approval_state`,
`pause_state`, `cancel_state`, `audit_context`). Either `task_name` or
`adapter_name` would also be required. The adapter would treat all of
this as read-only.

## Required outputs (implemented, Phase 3D)

A contract-shape result requires `status` and `message`, with optional
`output`, `metadata`, and `error`. `status` is the classification
signal, one of: `success`, `failure`, `retryable` (requires
`retry_after`), `blocked` (requires `blocked_reason`), or
`approval-required` (requires `approval_reason`). An adapter opts in by
returning `status`/`message` instead of `success`; a result containing
`success` is always treated as the original shape, even if it also
contains `status`.

## Validation and classification rules (implemented, Phase 3D)

The scheduler validates every result before classification; malformed,
unsupported-status, or missing-conditional-field results are rejected
through the same controlled failure path as any other invalid result --
never crash the scheduler loop, always audit-logged. `retryable` reuses
the existing retry-budget/audit machinery but uses the adapter's own
`retry_after` instead of computed backoff. `blocked` maps to the same
`GOVERNANCE_BLOCKED` state a pre-execution stop condition produces.
`approval-required` sets `task.approval_required = True` and creates a
pending `ApprovalRequest`, so a rerun is gated by `StopConditionChecker`
exactly like a task that declared `approval_required` up front, instead
of re-invoking the adapter.

## Governance (implemented)

The scheduler owns lifecycle state, approval routing, retry policy,
pause/resume/cancel, batching/dispatch, audit logging, and result
classification. The adapter owns only permitted task execution and
returning a valid result — it must never mutate scheduler state, write
task/retry/approval/pause/cancel/queue records, bypass or self-authorize
approval, mark a task approved/completed/retried/paused/resumed/cancelled
on its own, or perform side effects outside its allowed boundary. An
approval-required result stops at `approval-required`, exactly as a
pre-declared `approval_required` task does — the adapter cannot convert
itself to success.

## Implementation guidance

Adapters should be deterministic where possible, keep side effects
isolated, and return structured results rather than raising for expected
outcomes. `FakeContractAdapter` covers all five statuses without a real
integration; it is intentionally not registered in the adapter registry
since it exists to document/test the shape, not to be selected as a
local adapter. Real external adapters (`github_readonly`,
`notion_readonly`, `github_pr_comment`) still use the original shape and
are not required to migrate.

## Contract enforcement (implemented, result side)

Any contract-shape result violating these rules is treated as invalid:
handled safely, audit-logged, and prevented from mutating scheduler
state or bypassing approval gates -- identical treatment to a malformed
original-shape result.
