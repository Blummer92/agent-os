# TaskAdapter Contract

**Status:** The five-state result contract and the Phase 4D request migration for
local noop/fake adapters are implemented. Real adapters remain on legacy `Task`
input until their separately governed migration phases.

## Result Contract

Contract-shape results contain `status` and `message`. Status is one of:

- `success`;
- `failure`;
- `retryable`, requiring `retry_after`;
- `blocked`, requiring `blocked_reason`;
- `approval-required`, requiring `approval_reason`.

A result containing `success` remains on the original result path. The executor
validates both supported result shapes and converts malformed returns or raised
adapter exceptions into controlled, audited task failures.

## Request Contract

`ExecutionRequest` is an immutable adapter input containing:

- task, workflow, owner, payload, idempotency, and mode evidence;
- approval-required and production-readiness evidence;
- execution ID, run ID, attempt number, and creation time;
- optional batch ID and `ExecutionContext` metadata.

`ExecutionContext` may carry approval, batch, and pause metadata for tracing. It
does not authorize work.

## Explicit Opt-In

`TaskAdapter.accepts_execution_request` defaults to `False`.

The canonical `workflow_scheduler.execution.Executor` creates an
`ExecutionRequest` only for adapters that set the capability to `True`. Request
construction uses `build_execution_request_from_task`; one executor retains one
run ID and each adapter call receives a distinct execution ID.

Phase 4D opt-in adapters are:

- `NoopAdapter`;
- `FakeSuccessAdapter`;
- `FakeFailureAdapter`;
- `FakeRetryableAdapter`;
- `FakeNeverCalledAdapter`;
- `FakeSlowAdapter`;
- `FakeMalformedReturnAdapter`;
- `FakeRaisingAdapter`.

`FakeContractAdapter` and all real adapters continue receiving legacy `Task`
input. No signature inspection or exception-based input fallback is used.

## Ownership Boundary

The scheduler owns:

- task status and lifecycle transitions;
- lease locks, retries, and scheduling;
- approval gates and decisions;
- pause, resume, cancel, and batching behavior;
- audit logging, persistence, and result classification.

Adapters may read their input and return a supported result. They must not mutate
scheduler-owned state or treat request metadata as approval, freshness,
readiness, or execution authorization.

## Migration Sequence

- Phase 4A: request-side design.
- Phase 4B: immutable models.
- Phase 4C: pure compatibility helper.
- Phase 4D: noop and seven local fake adapters.
- Phase 4E: future read-only real-adapter migration.
- Phase 4F: future approval-gated write-adapter migration.
- Phase 4G: future legacy `Task` input removal after every adapter migrates.

Each later phase requires separate scope, validation, and authorization.
