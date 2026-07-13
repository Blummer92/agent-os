# Workflow Scheduler Architecture

## Overview

The Workflow Scheduler is a simple, governance-first task execution engine. Phase 1 shipped the core engine; Phase 2A-2E added approvals, retries, pause/resume/cancel, batching, and opt-in parallel dispatch on top of it. It prioritizes:
1. **Governance enforcement** - Stop conditions checked before execution
2. **Audit compliance** - All state transitions logged
3. **Lease locks** - Prevent concurrent execution of the same task
4. **Dependency management** - Topological sort with cycle detection

## Core Components

### Models (`src/workflow_scheduler/models/`)
- **Task**: Individual work unit with status state machine
- **WorkflowPlan**: Collection of dependent tasks

### Repository (`src/workflow_scheduler/repository/`)
- **SQLiteRepository**: Simple file-based persistence
- CRUD operations for workflows, tasks, and audit events

### Execution Flow

```
1. Load workflow from YAML
2. Create WorkflowPlan with tasks
3. For each task:
   a. Check stop conditions (governance)
   b. Acquire lease lock
   c. Execute via adapter
   d. Update task status
   e. Log to audit trail
   f. Release lease lock
4. Track dependencies using DependencyResolver
5. Execute ready tasks in order
```

### Queue (`src/workflow_scheduler/queue/`)
- **JobQueue**: Priority-based FIFO queue
- Tasks ordered by priority (higher first) then creation time

### Dependencies (`src/workflow_scheduler/dependencies/`)
- **DependencyResolver**: Manages task ordering
- Detects cycles via DFS
- Identifies ready tasks via topological sort

### Governance (`src/workflow_scheduler/governance/`)
- **StopConditionChecker**: Enforces 4 governance blocks:
  1. Approval Engine Deferred (resolved via explicit `cli approve`/`cli reject`, not automatic)
  2. Ambiguous Target (empty action)
  3. Missing Authorization (ownership verification)
  4. Conflicting Source-of-Truth (DB conflict check)

### Audit (`src/workflow_scheduler/audit/`)
- **AuditLogger**: Logs all state transitions
- Events include: timestamp, event_type, task/workflow IDs, status changes

### Adapters (`src/workflow_scheduler/adapters/`)
- **TaskAdapter**: Interface for task execution
- **NoopAdapter**: Test stub (always succeeds)

### Executor (`src/workflow_scheduler/execution/`)
- **Executor**: Orchestrates execution with governance checks
- Manages lease locks (300s timeout default)
- Logs governance checks and failures
- `execute_many()`: runs a set of mutually independent tasks (e.g. one
  dependency-resolver readiness pass), sequentially when
  `max_workers=1` (the default), or concurrently via a bounded
  `ThreadPoolExecutor` when `max_workers` > 1. Same-process only -- no
  cross-process concurrency.

### CLI (`src/workflow_scheduler/cli.py`)
- **create**: Load workflow from YAML
- **list**: List all workflows
- **status**: Get workflow status
- **run**: Execute workflow
- **audit**: View audit log

## Data Flow

### Workflow Creation
```yaml
workflow:
  id: "workflow-1"
  title: "Dashboard Sync"
  tasks:
    - id: "task-1"
      action: "sync_dashboard"
      depends_on: []
    - id: "task-2"
      action: "verify_sync"
      depends_on: ["task-1"]
```

### Execution Flow
1. Parse YAML → Create WorkflowPlan
2. Create Task objects, persist to SQLite
3. Build dependency graph
4. Loop: Get ready tasks → Execute → Track completion
5. Update workflow status (completed/failed/blocked)

## Stop Conditions in Action

Task with `production_ready=True` (or `approval_required=True`), first time through:
```
Check stop conditions
  ↓
Blocked: approval_engine_deferred (and no other blocker)
  ↓
Create ApprovalRequest, log approval_requested
  ↓
Mark task APPROVAL_PENDING (resumable, not terminal)
  ↓
Return blocked result
```
A human then resolves it out-of-band with `cli approve`/`cli reject`. On
the next `run`, an approved task proceeds to lease acquisition and
execution as normal; a rejected task is marked `GOVERNANCE_BLOCKED` and
does not retry. Any *other* stop condition (ambiguous target, missing
authorization, conflicting source-of-truth) still blocks immediately as
`GOVERNANCE_BLOCKED` with no approval step, same as before.

## Lease Lock Mechanism

Prevents concurrent execution of same task:
```
1. acquire_lease() → task.lease_lock = now()
2. execute task via adapter
3. release_lease() → task.lease_lock = None
```

If task has active lease (elapsed < 300s), execution fails.

## Audit Logging

Every state transition logged:
- task_created
- task_approved
- task_started
- task_completed
- task_failed
- governance_blocked
- workflow_created
- workflow_started
- workflow_completed

## Design Constraints

✅ **Simple**: No ORM, no Redis, no cloud workers  
✅ **Governance-first**: Stop conditions before execution  
✅ **Idempotent**: Adapter responsible for deduplication  
✅ **Audited**: All transitions logged  
✅ **Tested**: 291 tests, 97% coverage  
✅ **Shipped (Phase 2A-2E)**: Approval engine, retry manager, pause/resume/cancel, task batching, opt-in parallel dispatch (`--max-workers`, same-process threading only)

❌ **Still out of scope**: Real external adapters (only `NoopAdapter`), REST API, web dashboard UI, background/daemon mode, cross-process concurrency

## Future Phases

**Phase 3**: Real adapters, REST API, dashboard UI
