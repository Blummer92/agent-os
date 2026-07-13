# TaskAdapter Contract (Result Side Implemented; Request Side Phase 4A Design)

**Status:** The five-state **result** contract (`status`/`message`, Phase 3D)
is implemented and in use. Phase 4A documents the **request** contract only;
it does not add models, change `TaskAdapter`, change `Executor`, or migrate adapters.

- **Result side (implemented)**: Real adapters (`github_readonly`, `notion_readonly`,
  `github_pr_comment`, `github_pr_label`) use the five-state contract. Executor
  validates and classifies results through `_is_contract_result()`,
  `_validate_contract_result()`, and `_handle_contract_result()`.
- **Backward compatibility**: Noop and fake adapters still cover the original
  `success`/`error`/`is_transient` shape. Executor treats either shape correctly.
- **Request side (Phase 4A design)**: Proposed immutable adapter input. Do not
  implement until a dedicated implementation phase adds compatibility and migration.

## Purpose

TaskAdapter is the execution boundary between the scheduler and a task
implementation. It performs only the work the scheduler allows and returns one
structured result for scheduler classification.

## Request-side contract design (Phase 4A)

Future adapters should receive an immutable `ExecutionRequest` instead of a
mutable `Task`. The object is a read-only snapshot of the execution input, not a
scheduler state handle.

Proposed required `ExecutionRequest` fields:

- `task_id`, `workflow_id`, `owner`
- `payload`, `idempotency_key`, `mode`
- `approval_required`, `production_ready`
- `execution_id`, `run_id`, `attempt_number`, `created_at`
- `execution_context`

Proposed optional `ExecutionRequest` field:

- `batch_id` when the task belongs to a batch

`execution_id` is unique for each adapter invocation. `run_id` identifies the
workflow execution session. `attempt_number` is zero-indexed, matching the
current retry attempt. `created_at` records when the request snapshot was built.

## ExecutionContext design (Phase 4A)

`ExecutionContext` carries optional governance and tracing metadata. It informs
adapters for telemetry or provider-specific messages; it does not authorize work.

Optional context fields:

- `approval_state`: current approval state when applicable
- `approval_context`: approver, timestamp, and reason metadata when available
- `batch_metadata`: batch id, position, size, or related batch data
- `pause_state`: prior status when pause/resume context is relevant

Approval gating remains pre-execution scheduler behavior. An adapter may read
approval metadata, but cannot approve, reject, or bypass approval.

## Immutability and ownership

`ExecutionRequest` and `ExecutionContext` should be frozen/read-only in the
implementation phase. Adapters may read them but must not mutate scheduler-owned
state or rely on mutable `Task` internals.

Executor-owned state that adapters must not mutate:

- task status and lifecycle transitions
- lease locks
- retry counters and `next_retry_at`
- approval gating and approval decisions
- pause/cancel transitions
- audit logging and queue records

## Migration plan

- **Phase 4A**: docs/design only; no runtime behavior change.
- **Phase 4B**: add `ExecutionRequest` and `ExecutionContext` models only.
- **Phase 4C**: add compatibility shim for Task/request input transition.
- **Phase 4D**: migrate noop/fake adapters.
- **Phase 4E**: migrate read-only real adapters.
- **Phase 4F**: migrate approval-gated write adapters.
- **Phase 4G**: remove legacy Task-based adapter input after all adapters migrate.

## Required outputs (implemented, Phase 3D)

A contract-shape result requires `status` and `message`, with optional `output`,
`metadata`, and `error`. `status` is one of: `success`, `failure`, `retryable`
(requires `retry_after`), `blocked` (requires `blocked_reason`), or
`approval-required` (requires `approval_reason`). An adapter opts in by returning
`status`/`message` instead of `success`; a result containing `success` is always
treated as the original shape, even if it also contains `status`.

## Validation and classification rules (implemented, Phase 3D)

The scheduler validates every result before classification. Malformed,
unsupported-status, or missing-conditional-field results are rejected through the
same controlled failure path as any other invalid result -- never crash the
scheduler loop, always audit-logged. `retryable` reuses the existing retry budget
and audit machinery but uses the adapter's own `retry_after`.

## Governance (implemented)

The scheduler owns lifecycle state, approval routing, retry policy,
pause/resume/cancel, batching/dispatch, audit logging, and result classification.
The adapter owns only permitted task execution and returning a valid result. It
must never write task/retry/approval/pause/cancel/queue records, bypass approval,
or mark a task approved/completed/retried/paused/resumed/cancelled on its own.

## Contract enforcement (implemented, result side)

Any contract-shape result violating these rules is treated as invalid: handled
safely, audit-logged, and prevented from mutating scheduler state or bypassing
approval gates -- identical treatment to a malformed original-shape result.
