# API Reference

## Models

### Task

Individual work unit in a workflow.

```python
from workflow_scheduler.models import Task, TaskStatus, TaskMode

task = Task(
    id="task-1",
    workflow_id="workflow-1",
    type="data_sync",
    owner="system",
    action="sync_database",
    idempotency_key="sync-key-1",
    status=TaskStatus.DRAFT,
    mode=TaskMode.DRAFT,
    priority=1,
    approval_required=False,
    depends_on=["task-0"],
    payload={"db": "postgres"},
    production_ready=False,
)

# State transitions
task.mark_approved()
task.mark_completed(result={"rows": 100})
task.mark_failed(error="Connection timeout", is_transient=True)
task.mark_paused()
task.mark_cancelled(reason="User cancelled")

# Status queries
is_ready = task.is_ready_to_run()
is_complete = task.is_completed()

# Lease lock management
task.acquire_lease()
has_lock = task.has_active_lease(timeout_seconds=300)
task.release_lease()
```

**Status Values**:
- `DRAFT`: Initial state
- `PENDING`: Queued for execution
- `APPROVAL_PENDING`: Waiting for approval
- `APPROVED`: Ready to execute
- `QUEUED`: In execution queue
- `RUNNING`: Currently executing
- `RETRY_SCHEDULED`: Transient failure, will retry
- `COMPLETED`: Finished successfully
- `FAILED`: Finished with error
- `GOVERNANCE_BLOCKED`: Blocked by governance
- `PAUSED`: Manually paused
- `CANCELLED`: Cancelled

### WorkflowPlan

Collection of dependent tasks.

```python
from workflow_scheduler.models import WorkflowPlan, WorkflowMode, WorkflowStatus

workflow = WorkflowPlan(
    workflow_id="workflow-1",
    title="Data Pipeline",
    created_by="user@example.com",
    mode=WorkflowMode.DRAFT,
    status=WorkflowStatus.DRAFT,
)

# Task management
workflow.add_task("task-1")
workflow.set_dependencies("task-2", ["task-1"])

# Execution control
workflow.mark_running()
workflow.mark_completed()
workflow.mark_failed(reason="Task failed")
workflow.mark_cancelled(reason="User cancelled")
workflow.mark_governance_blocked(reason="Policy violation")

# Status queries
is_done = workflow.is_terminal()
```

## Repository

### SQLiteRepository

Persistence layer for workflows and tasks.

```python
from workflow_scheduler.repository import SQLiteRepository

repo = SQLiteRepository(db_path="workflow.db")

# Workflows
repo.create_workflow(workflow)
retrieved = repo.get_workflow(workflow_id)
repo.update_workflow(workflow)

# Tasks
repo.create_task(task)
retrieved = repo.get_task(task_id)
repo.update_task(task)
tasks = repo.list_workflow_tasks(workflow_id)

# Audit log
repo.log_event(
    event_type="task_completed",
    task_id="task-1",
    workflow_id="workflow-1",
    details={"result": {"rows": 100}},
)
events = repo.get_audit_log(workflow_id="workflow-1")

repo.close()
```

## Queue

### JobQueue

Priority-based task queue.

```python
from workflow_scheduler.queue import JobQueue

queue = JobQueue()

# Queue management
queue.enqueue(task)
next_task = queue.dequeue()
peek = queue.peek()
queue.remove(task_id)

# Status
size = queue.size()
is_empty = queue.is_empty()
all_tasks = queue.list_queued()
```

## Dependencies

### DependencyResolver

Manages task dependencies and execution order.

```python
from workflow_scheduler.dependencies import DependencyResolver

resolver = DependencyResolver(tasks, dependencies)

# Cycle detection
has_cycle, cycle_path = resolver.has_cycle()

# Ready tasks
completed = {"task-0", "task-1"}
ready = resolver.get_ready_tasks(completed)

# Dependency analysis
all_deps = resolver.get_all_dependencies("task-2")

# Execution order
success, sorted_tasks = resolver.topological_sort()
```

## Governance

### StopConditionChecker

Enforces governance stop conditions.

```python
from workflow_scheduler.governance import StopConditionChecker

result = StopConditionChecker.check_all_stop_conditions(
    task=task,
    ownership_registry=registry,
    source_of_truth_db=database,
)

if result.is_blocked:
    print(f"Blocked: {result.blockers}")
    print(f"Reason: {result.reason}")

# Individual checks
result = StopConditionChecker.check_approval_required(task)
result = StopConditionChecker.check_production_mode(task)
```

**Blockers**:
- `approval_engine_deferred`: Task requires an explicit human decision (`approval_required`, `production_ready`, or `TaskMode.PRODUCTION`); resolve via `cli approve` or `cli reject`, or `repository.update_approval_decision(...)` directly
- `ambiguous_target`: Task action is empty
- `missing_authorization`: Owner doesn't own target
- `conflicting_source_of_truth`: DB conflict detected

## Audit Logger

### AuditLogger

Logs all state transitions for compliance.

```python
from workflow_scheduler.audit import AuditLogger

logger = AuditLogger(repository=repo)

# Task events
logger.log_task_created(task)
logger.log_task_approved(task, approved_by="reviewer")
logger.log_task_started(task)
logger.log_task_completed(task, result={"rows": 100})
logger.log_task_failed(task, error="Timeout", is_transient=False)
logger.log_task_paused(task)
logger.log_task_cancelled(task, reason="User cancelled")
logger.log_governance_blocked(task, blockers=["ambiguous_target"])
logger.log_governance_check_passed(task)

# Workflow events
logger.log_workflow_created(workflow)
logger.log_workflow_started(workflow)
logger.log_workflow_completed(workflow)
logger.log_workflow_failed(workflow, reason="Task failed")

# Retrieve events
all_events = logger.get_events()
task_events = logger.get_events(task_id="task-1")
workflow_events = logger.get_events(workflow_id="workflow-1")
```

## Adapters

### TaskAdapter (Base Class)

Abstract interface for task execution.

```python
from workflow_scheduler.adapters import TaskAdapter

class CustomAdapter(TaskAdapter):
    def execute(self, task: Task) -> Dict[str, Any]:
        # Implement task execution
        return {
            "success": True,
            "error": None,
            "output": {"result": "done"},
        }
```

### NoopAdapter

Test adapter that always succeeds.

```python
from workflow_scheduler.adapters import NoopAdapter

adapter = NoopAdapter(log_output=True)

result = adapter.execute(task)
# Always returns: {"success": True, "output": {...}}

log = adapter.get_execution_log()
```

## Executor

### Executor

Orchestrates task execution with governance checks and lease locks.

```python
from workflow_scheduler.execution import Executor

executor = Executor(
    adapter=adapter,
    repository=repo,
    audit_logger=logger,
    lease_timeout_seconds=300,
    max_workers=1,  # >= 1; default 1 = fully sequential
)

result = executor.execute(
    task=task,
    ownership_registry=registry,
)

if result.success:
    print(f"Status: {result.status}")
else:
    print(f"Error: {result.error}")
    print(f"Blockers: {result.blockers}")

# Run several mutually independent tasks (e.g. one dependency-resolver
# readiness pass) sequentially when max_workers=1, or concurrently
# (ThreadPoolExecutor, bounded by max_workers) otherwise. Same-process
# only. Caller is responsible for the tasks being independent -- this
# does not check dependencies.
results = executor.execute_many(tasks=[task1, task2], ownership_registry=registry)
# -> Dict[str, ExecutionResult], one entry per input task
```

**ExecutionResult**:
- `success`: Boolean success indicator
- `status`: "pass" | "fail" | "blocked"
- `error`: Error message if failed
- `output`: Execution result data
- `is_transient`: Whether error is transient (retryable)
- `blockers`: List of blocking conditions
- `checks_passed`: Passed checks
- `checks_failed`: Failed checks

## CLI

### WorkflowSchedulerCLI

Command-line interface.

```python
from workflow_scheduler.cli import WorkflowSchedulerCLI

cli = WorkflowSchedulerCLI(db_path="workflow.db", max_workers=1)  # max_workers threads through to Executor

# Workflow management
result = cli.create_workflow("path/to/workflow.yaml")
result = cli.get_workflow_status("workflow-1")
result = cli.list_workflows()

# Execution -- ready tasks within one dependency-resolver pass run
# concurrently when max_workers > 1; dependency ordering across passes is
# unaffected either way
result = cli.run_workflow("workflow-1")

# Audit
result = cli.show_audit_log(workflow_id="workflow-1")
result = cli.show_audit_log(task_id="task-1")
```

## Example: End-to-End

```python
from workflow_scheduler.models import Task, WorkflowPlan
from workflow_scheduler.repository import SQLiteRepository
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.adapters import NoopAdapter
from workflow_scheduler.execution import Executor
from workflow_scheduler.dependencies import DependencyResolver
from workflow_scheduler.governance import StopConditionChecker

# Create repository
repo = SQLiteRepository(":memory:")
logger = AuditLogger(repository=repo)
adapter = NoopAdapter()
executor = Executor(adapter=adapter, repository=repo, audit_logger=logger)

# Create workflow
workflow = WorkflowPlan(
    workflow_id="test",
    title="Test Workflow",
    created_by="user",
)

# Create tasks
task1 = Task(
    id="task-1",
    workflow_id="test",
    type="test",
    owner="system",
    action="do_work",
    idempotency_key="key-1",
)

task2 = Task(
    id="task-2",
    workflow_id="test",
    type="test",
    owner="system",
    action="verify",
    idempotency_key="key-2",
    depends_on=["task-1"],
)

# Persist
repo.create_workflow(workflow)
repo.create_task(task1)
repo.create_task(task2)
logger.log_workflow_created(workflow)
logger.log_task_created(task1)
logger.log_task_created(task2)

# Execute
result1 = executor.execute(task1)
if result1.success:
    result2 = executor.execute(task2)

# Check results
events = logger.get_events()
audit = repo.get_audit_log(workflow_id="test")
```
