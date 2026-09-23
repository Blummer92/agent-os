# Workflow Scheduler User Guide

## Quick Start

### 1. Install

```bash
cd 08_Tooling/workflow-scheduler
pip install -r requirements.txt
```

### 2. Create Workflow YAML

```yaml
workflow_id: "my-workflow"
title: "Example Workflow"
created_by: "user@example.com"
mode: "Draft"
tasks:
  - id: "task-1"
    type: "data_sync"
    owner: "system"
    action: "sync_data"
    idempotency_key: "sync-20260712"
    priority: 1
    
  - id: "task-2"
    type: "verification"
    owner: "system"
    action: "verify_sync"
    idempotency_key: "verify-20260712"
    depends_on: ["task-1"]
    priority: 0
```

### 3. Create Workflow

```bash
python -m workflow_scheduler.cli create path/to/workflow.yaml
```

Output:
```json
{
  "success": true,
  "workflow_id": "my-workflow",
  "title": "Example Workflow",
  "task_count": 2
}
```

### 4. Check Status

```bash
python -m workflow_scheduler.cli status my-workflow
```

### 5. Run Workflow

```bash
python -m workflow_scheduler.cli run my-workflow
```

### 6. View Audit Log

```bash
python -m workflow_scheduler.cli audit --workflow-id my-workflow
```

## Task Configuration

### Required Fields
- `id`: Unique task identifier
- `owner`: Task owner (for authorization)
- `action`: What the task does
- `idempotency_key`: Deduplication key

### Optional Fields
- `type`: Task category (default: "generic")
- `priority`: Execution priority (default: 0, higher first)
- `approval_required`: Requires explicit human approval before execution; blocks with `approval_engine_deferred` until resolved via `cli approve` or `cli reject`
- `production_ready`: Marks the task production-scoped; blocks the same way as `approval_required` until explicitly approved
- `depends_on`: List of task IDs this depends on
- `payload`: Arbitrary task data

## Workflow Modes

- **Draft**: Development mode (Phase 1 only)
- **Gate**: Gated execution (Phase 2+)
- **Production**: Production mode (Phase 2+)

## Governance Rules

### Stop Conditions

Tasks are blocked before execution if:

1. **Approval Engine Deferred**
   - Task has `approval_required: true`
   - Task has `production_ready: true`
   - Reason: Requires an explicit human decision before executing; resolve with `cli approve --task-id <id> --approver <name>` or `cli reject --task-id <id> --approver <name> --reason <reason>`

2. **Ambiguous Target**
   - Task `action` is empty or missing
   - Reason: Can't determine what to execute

3. **Missing Authorization**
   - Task owner doesn't own the target system
   - Reason: Write permission denied

4. **Conflicting Source-of-Truth**
   - Task target conflicts with database record
   - Reason: Data inconsistency

### Blocked Tasks

When blocked, task status becomes `governance_blocked`:
- Execution skipped
- Event logged to audit trail
- Reason recorded in audit details
- Workflow continues to next ready task

## Execution Model

### Ready Tasks

A task is ready when:
- All dependencies completed
- No stop conditions triggered
- Lease lock not held (not currently executing)

### Execution Order

1. Build dependency graph
2. Check for cycles (fails if found)
3. Find ready tasks (all deps complete)
4. Execute ready tasks
5. Track completion
6. Repeat until done

### Lease Locks

Lease locks prevent concurrent execution:
- Acquired at start of execution
- Released after completion (success or failure)
- Timeout: 300 seconds

### Parallel Dispatch (opt-in)

Step 4 above ("Execute ready tasks") runs sequentially by default. Pass
`--max-workers N` to `run` (N > 1) to dispatch all of a pass's ready
tasks concurrently, bounded by N at a time. The next readiness pass still
only starts once every task in the current pass has finished, so
dependency ordering is unaffected either way -- `--max-workers` only
changes how many *independent* tasks run at once, never the order
dependent tasks become eligible. The repository is safe for this kind of
same-process, multi-threaded sharing; it does not support cross-process
concurrency (e.g. two separate `run` processes against the same file-backed
database at once).

### Task Batching

Tasks sharing a `batch_id` are grouped together in dispatch order for
rollup reporting (a `batch_result` audit event summarizing the batch as
`completed`/`failed`/`partial`/`not_started`) -- batch membership does
not by itself make tasks run sequentially or in lockstep. With the
default `--max-workers 1`, batch members execute one at a time like any
other ready task. With `--max-workers` > 1, batch members are dispatched
concurrently alongside any other ready tasks in the same pass, the same
as non-batched tasks.

## Output Schema

All execution results include:
- `status`: "pass" | "fail" | "blocked"
- `blockers`: List of blocking conditions
- `checks_passed`: Passed checks
- `checks_failed`: Failed checks
- `success`: Boolean success indicator
- `error`: Error message if failed
- `output`: Execution result data

## Common Patterns

### Simple Sequence

```yaml
tasks:
  - id: "step-1"
    action: "prepare_data"
  - id: "step-2"
    action: "process_data"
    depends_on: ["step-1"]
  - id: "step-3"
    action: "cleanup"
    depends_on: ["step-2"]
```

### Fan-Out

```yaml
tasks:
  - id: "distribute"
    action: "distribute_work"
    
  - id: "worker-1"
    action: "work_chunk_1"
    depends_on: ["distribute"]
    
  - id: "worker-2"
    action: "work_chunk_2"
    depends_on: ["distribute"]
```

### Fan-In

```yaml
tasks:
  - id: "worker-1"
    action: "work_chunk_1"
    
  - id: "worker-2"
    action: "work_chunk_2"
    
  - id: "collect"
    action: "collect_results"
    depends_on: ["worker-1", "worker-2"]
```

## Troubleshooting

### Workflow won't run
- Check for cycles: `rng --multiline "depends_on.*\[" workflow.yaml`
- Verify task actions are not empty
- Check ownership: Does owner have permission for action?

### Task blocked
- Check stop conditions in audit log: `cli audit --task-id task-1`
- If blocked by `approval_engine_deferred`: approve or reject it with `cli approve --task-id task-1 --approver <name>` or `cli reject --task-id task-1 --approver <name> --reason <reason>`, then re-run the workflow
- If blocked by `ambiguous_target`: Ensure `action` is set
- If blocked by `missing_authorization`: Verify owner→action mapping

### Lease lock timeout
- Task may have crashed during execution
- Default timeout: 300 seconds
- Fix: Update task status manually or wait for timeout

## Current Scope

Implemented (Phase 2A-2E):
- ✅ Approval workflows (`approval_required` / `production_ready`, resolved via `cli approve` / `cli reject`)
- ✅ Automatic retries (transient failures, exponential backoff, capped retry budget)
- ✅ Pause/resume/cancel lifecycle, at both the task and workflow level
- ✅ Task batching (`batch_id` grouping with rollup audit reporting)
- ✅ Opt-in parallel ready-list dispatch (`--max-workers`; sequential by default)

Still NOT supported:
- ❌ Real external adapters (only `NoopAdapter` ships in this repo)
- ❌ REST API
- ❌ Web dashboard
- ❌ Background/daemon mode (the CLI runs one workflow to completion or to its next blocking point, then exits)
- ❌ Cross-process concurrency (safe for same-process multi-threading only; two separate processes must not run against the same database concurrently)

## For Developers

See `ARCHITECTURE.md` for implementation details, `API_REFERENCE.md` for Python API.

To run tests:
```bash
pytest tests/ -v --cov=src/workflow_scheduler --cov-report=term
```

Current: 291 tests passed, 97% coverage overall (target: 80%+)
