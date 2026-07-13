# TaskAdapter Contract (Future Reference — Not Yet Implemented)

**Status:** Draft reference document for a future phase. This is not the
current `TaskAdapter` interface and nothing in the codebase enforces it
yet. Phase 2F ("Adapter Readiness MVP") intentionally implements a much
smaller, non-breaking safety net instead — see
`08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md` and
`API_REFERENCE.md` for what actually exists today. This document is
preserved as the target shape a later phase (tentatively Phase 2G) could
formalize toward, once real external adapters are closer to landing
(tentatively Phase 2H).

Do not implement this document's JSON Schemas, immutable request object,
or `additionalProperties: false` result validation without a dedicated,
explicitly-scoped phase — Phase 2F deliberately did not.

---

## Purpose

TaskAdapter is the execution boundary between the scheduler and a task implementation. It receives an immutable task request, performs only the work allowed by the scheduler, and returns a structured result for scheduler classification.

## Required inputs

A TaskAdapter must be invoked with a complete, immutable execution request that validates against the following JSON Schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/task-adapter-execution-request.json",
  "title": "TaskAdapterExecutionRequest",
  "type": "object",
  "required": ["task_id", "owner", "payload", "execution_context"],
  "anyOf": [
    { "required": ["task_name"] },
    { "required": ["adapter_name"] }
  ],
  "properties": {
    "task_id": { "type": "string", "minLength": 1 },
    "task_name": { "type": "string", "minLength": 1 },
    "adapter_name": { "type": "string", "minLength": 1 },
    "owner": { "type": "string", "minLength": 1 },
    "payload": {},
    "execution_context": {
      "type": "object",
      "required": ["run_id", "attempt_number"],
      "properties": {
        "run_id": { "type": "string", "minLength": 1 },
        "attempt_number": { "type": "integer", "minimum": 1 },
        "batch_id": { "type": "string" },
        "batch_metadata": { "type": "object" },
        "retry_policy": { "type": "object" },
        "approval_state": { "type": "object" },
        "pause_state": { "type": "object" },
        "cancel_state": { "type": "object" },
        "audit_context": { "type": "object" }
      },
      "additionalProperties": true
    }
  },
  "additionalProperties": true
}
```

The adapter may read these inputs, but it must treat them as read-only. If additional adapter-specific fields are needed, they must be passed through the request object without changing scheduler-owned state.

## Required outputs

A TaskAdapter must return exactly one structured result object that validates against the following JSON Schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/schemas/task-adapter-result.json",
  "title": "TaskAdapterResult",
  "type": "object",
  "required": ["status", "message"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["success", "failure", "retryable", "blocked", "approval-required"]
    },
    "message": { "type": "string", "minLength": 1 },
    "output": {},
    "metadata": { "type": "object", "additionalProperties": true },
    "error": { "type": "object", "additionalProperties": true },
    "retry_after": {
      "anyOf": [
        { "type": "string", "minLength": 1 },
        { "type": "integer", "minimum": 0 },
        {
          "type": "object",
          "properties": {
            "delay_seconds": { "type": "integer", "minimum": 0 },
            "retry_at": { "type": "string", "format": "date-time" },
            "reason": { "type": "string" }
          },
          "additionalProperties": true
        }
      ]
    },
    "blocked_reason": { "type": "string", "minLength": 1 },
    "approval_reason": { "type": "string", "minLength": 1 }
  },
  "additionalProperties": false,
  "allOf": [
    {
      "if": { "required": ["status"], "properties": { "status": { "const": "retryable" } } },
      "then": { "required": ["retry_after"] }
    },
    {
      "if": { "required": ["status"], "properties": { "status": { "const": "blocked" } } },
      "then": { "required": ["blocked_reason"] }
    },
    {
      "if": { "required": ["status"], "properties": { "status": { "const": "approval-required" } } },
      "then": { "required": ["approval_reason"] }
    }
  ]
}
```

## Result states

The `status` field is the only supported classification signal and must be one of:

- `success`: the task completed successfully within the allowed execution boundary.
- `failure`: the task reached a terminal error condition.
- `retryable`: the task encountered a transient condition and may be retried later.
- `blocked`: the task cannot proceed because of a governance, dependency, or environmental stop.
- `approval-required`: the task cannot proceed until an approval gate is satisfied.

## Validation and classification rules

- The scheduler must validate every adapter result before classification.
- Malformed, incomplete, or unsupported results must be rejected through a controlled failure path.
- Validation failures must not crash the scheduler loop.
- Validation failures must be audit-logged.

## Governance

- The scheduler owns task lifecycle state, approval routing, retry policy enforcement, pause/resume/cancel handling, batching and dispatch decisions, audit logging of adapter outcomes, and final classification of adapter results.
- The adapter owns only the execution of the task logic permitted by the scheduler and the return of a valid result.
- The adapter must not mutate scheduler state directly or write to task records, retry counters, approval records, pause/resume state, cancel state, or queue state.
- The adapter must not bypass approval gates, self-authorize execution, skip approval checks, or convert an approval-required task into success without scheduler approval.
- The adapter must not perform approval-gated writes before approval is granted, mark a task approved, completed, retried, paused, resumed, or canceled on its own, perform external side effects outside the allowed execution boundary, return unsupported or ambiguous result states, rely on hidden side effects instead of returning a valid structured result, or override scheduler retry, approval, pause, resume, cancel, or governance decisions.
- If a task requires approval, the adapter must return `approval-required` and stop execution.
- The scheduler must ignore any adapter attempt to encode unsupported states or hidden transitions.

## Implementation guidance

- Adapters should be deterministic where possible.
- Adapters should keep side effects isolated and limited to the allowed execution boundary.
- Adapters should return structured results rather than raising uncaught exceptions for expected outcomes.
- Fake adapters may be used for testing success, failure, retryable, blocked, approval-required, and slow execution paths.
- Real external adapters may be added later without changing scheduler core logic, provided they conform to this contract.

## Contract enforcement

Any adapter that violates this contract must be treated as invalid by the scheduler. Invalid adapter behavior must be handled safely, logged for audit purposes, and prevented from mutating scheduler state or bypassing approval gates.
