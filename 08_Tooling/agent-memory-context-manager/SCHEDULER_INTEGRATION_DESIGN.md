# Scheduler Integration Design

## Purpose
This document describes how Agent Memory & Context Budget Manager could integrate with Workflow Scheduler in a future phase. It is design-only: no Scheduler behavior changes are implemented here.

## Integration Boundary
- **Workflow Scheduler** owns task execution, task state, retries, approvals, batching, parallel dispatch, and audit.
- **Memory Manager** owns context packet generation, file budgets, search/test/connector budgets, summary cache lookups, stale-context checks, and stop recommendations.
- **Agent Orchestrator** owns routing, ownership, task assignment, and mode choice.
- Memory Manager must not execute tasks or mutate Scheduler task state directly.
- Scheduler remains the authority for approvals, lifecycle, leases, and state transitions.

## Proposed Pre-Task Flow
1. Scheduler receives or prepares a task.
2. Scheduler requests a Memory Manager handoff packet.
3. Memory Manager uses task objective, phase, changed files, known facts, and budget policy.
4. Memory Manager returns allowed files, forbidden files, facts, validation commands, limits, and stop conditions.
5. Agent works only inside the approved packet.
6. Scheduler pauses or escalates if the agent requests budget expansion.

## Proposed Post-Task Flow
1. Agent reports files read, searches used, tests run, connector calls, and validation result.
2. Memory Manager marks summaries stale or reusable.
3. Scheduler records context usage in audit logs.
4. Future tasks reuse validated summaries where safe.

## Scheduler-Owned Responsibilities
- Select tasks and enforce dependency order.
- Manage task state, leases, retries, approvals, and lifecycle transitions.
- Dispatch adapter work and collect results.
- Decide whether budget escalation requires approval.
- Own durable audit records for task execution.

## Memory-Owned Responsibilities
- Build handoff packets before work starts.
- Recommend file, search, test, and connector budgets.
- Retrieve reusable summaries and flag stale summaries.
- Recommend stop/escalation when scope or budget grows.
- Suggest the smallest safe expanded budget when needed.

## Audit Logging Ideas
Future audit events may include:
- context packet generated
- files allowed
- files actually inspected
- budget exceeded
- budget escalation requested
- stale summary detected
- summary reused
- stop condition triggered

## Budget Escalation Flow
If an agent needs more files, searches, tests, or connector calls than the packet allows, it must stop and request escalation. Scheduler decides whether approval is required. Memory Manager recommends the smallest expanded budget and records why the original budget was insufficient.

## Future Implementation Phases
- **Memory 1A**: local packet generator, no Scheduler integration.
- **Memory 1B**: context usage log format.
- **Memory 1C**: stale-summary detection.
- **Memory 1D**: Scheduler calls packet generator before execution.
- **Memory 1E**: budget escalation signals.
- **Memory 2+**: production integration; optional vector DB only if justified.

## Non-Goals
No code implementation. No Scheduler code changes. No Executor changes. No TaskAdapter changes. No adapter changes. No schema validator. No autonomous writes. No vector DB. No embeddings. No REST API. No dashboard. No daemon. No Phase 4 adapter-contract work.