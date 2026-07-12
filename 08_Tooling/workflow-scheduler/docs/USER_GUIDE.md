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
- `approval_required`: Requires approval (Phase 2, blocks in Phase 1)
- `production_ready`: Production mode (Phase 2, blocks in Phase 1)
- `depends_on`: List of task IDs this depends on
- `payload`: Arbitrary task data

## Workflow Modes

- **Draft**: Development mode (Phase 1 only)
- **Gate**: Gated execution (Phase 2+)
- **Production**: Production mode (Phase 2+)

## Governance Rules (Phase 1)

### Stop Conditions

Tasks are blocked before execution if:

1. **Approval Engine Deferred**
   - Task has `approval_required: true`
   - Task has `production_ready: true`
   - Reason: Approval engine not implemented (Phase 2)

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
- If blocked by `approval_engine_deferred`: Remove `approval_required` or `production_ready`
- If blocked by `ambiguous_target`: Ensure `action` is set
- If blocked by `missing_authorization`: Verify owner→action mapping

### Lease lock timeout
- Task may have crashed during execution
- Default timeout: 300 seconds
- Fix: Update task status manually or wait for timeout

## Phase 1 Limitations

Phase 1 MVP does NOT support:
- ❌ Approval workflows
- ❌ Automatic retries
- ❌ Pause/resume
- ❌ Task batching
- ❌ Parallel execution
- ❌ Real adapters (only NoopAdapter)
- ❌ REST API
- ❌ Web dashboard

These are planned for Phase 2+.

## For Developers

See `ARCHITECTURE.md` for implementation details, `API_REFERENCE.md` for Python API.

To run tests:
```bash
pytest tests/ -v --cov=src/workflow_scheduler --cov-report=term
```

Target: 80%+ coverage (current: 91%)
