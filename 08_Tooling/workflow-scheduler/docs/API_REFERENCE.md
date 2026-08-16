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

# Individual checks. Pass source_of_truth_db to let a recorded APPROVED
# decision clear the block; omit it and the governed task stays blocked.
result = StopConditionChecker.check_approval_required(task, source_of_truth_db=database)
result = StopConditionChecker.check_production_mode(task, source_of_truth_db=database)
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

### InstructionalMaterialsDryRunAdapter

`InstructionalMaterialsDryRunAdapter` explicitly opts into immutable
`ExecutionRequest` input and delegates the request unchanged to the C3A
`validate_instructional_materials_contract` helper. The adapter contains no
payload validation, execution sink, credential lookup, network access, or
filesystem-write behavior of its own.

```python
from workflow_scheduler.adapters import InstructionalMaterialsDryRunAdapter

adapter = InstructionalMaterialsDryRunAdapter()
result = adapter.execute(execution_request)
```

A successful result proves only local contract validation and deterministic
receipt rendering. It does **not** prove approval, execution authorization,
source freshness, external capability, template access, target-folder access,
credentials, artifact quality, or permission to write. The receipt command is an
inert argument list and is never executed by this adapter. The sanitized authoring
example is `examples/instructional-materials-dry-run.yaml`.

### HostLocalLeaseAdapter

`HostLocalLeaseAdapter` is the bounded host-local implementation of the canonical
single-issue `LeaseAdapter` protocol. It coordinates independent processes on one
host through caller-supplied private filesystem metadata; it is not a distributed
lease, scheduler, daemon, retry service, or recovery mechanism.

```python
from workflow_scheduler.execution import HostLocalLeaseAdapter, HostLocalLeasePolicy

lease = HostLocalLeaseAdapter(
    policy=HostLocalLeasePolicy(lease_directory="/private/path/agent-os-leases")
)
grant = lease.acquire(request)
if grant.acquired:
    release = lease.release(grant)
```

The lease directory must be absolute, normalized, non-symlinked, and private to
the current owner (`0700`); lease metadata is written `0600`. Acquisition is
atomic across local processes, and every grant is bound to the canonical lease
identity, holder identity, and a monotonically increasing generation/fencing
value. Release succeeds only for the exact active lease, holder, and generation
and rereads filesystem state by requiring the active metadata path to be absent
before reporting success.

Existing, malformed, stale, orphaned, oversized, symlinked, or otherwise
ambiguous metadata is fail-closed. The adapter never infers safe ownership from
file age, TTL, process absence, or clock expiry and never steals, renews,
force-releases, automatically retries, or takes over a lease. Crash recovery and
manual cleanup of ambiguous metadata remain separately authorized operator work.
The existing `InMemoryLeaseAdapter` remains supported for process-local tests;
real runtime selection/wiring of the host-local adapter belongs to #762.

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

## POSIX Process Execution

### PosixProcessAdapter and WSC-AUTO1C cgroup v2 Containment

`run_bounded_posix_process` (`execution/posix_process_adapter.py`) runs one
argv sequence at most once and returns a bounded, immutable evidence
record: exact argv/cwd/env, `stdin=/dev/null`, bounded stdout/stderr,
timeout/cancellation, process-group `SIGTERM`, one bounded escalation, and
`termination_confirmed` only once the child's exit and the final pipe
drain/reap are directly observed. `PosixProcessExecutor` is the thin
one-shot `PilotExecutor` adapter around it.

An optional `containment: ContainmentConfig | None` parameter (also
`PosixProcessExecutorConfig.containment`) adds exact per-invocation Linux
cgroup v2 containment evidence. Omitted, behavior is exactly the pre-#759
adapter -- this is the rollback path: drop the `containment` argument (or
leave it unset) and the caller reverts to plain `subprocess.Popen` with no
cgroup involvement at all.

**Prerequisites**: Linux with cgroup v2 mounted (unified or hybrid
`.../unified`), one exact delegated Agent OS parent cgroup subtree the
caller already owns write access to, and a kernel implementing the
`clone3()` syscall with `CLONE_INTO_CGROUP` (see `clone3(2)`, `cgroups(7)`).

**Why a C extension**: a race-free way to land a child directly inside a
target cgroup does not exist through `subprocess.Popen`/`posix_spawn` plus
a later `cgroup.procs` migration -- the child can exec or fork before
migration completes. `preexec_fn` is documented by CPython as unsafe in a
threaded process. `clone3_cgroup_launcher.py` wraps the minimal
`_clone3_cgroup` C extension (`_clone3_cgroup.c`), which calls
`clone3(CLONE_INTO_CGROUP)` directly so the kernel creates the child
already inside the target cgroup. Only the parent side uses the Python C
API; the moment the syscall returns in the child, execution follows a
narrow, pre-computed, async-signal-safe path (`dup2`, `chdir`, `setsid`,
`execve`) with no `Py_*` call and no heap allocation, then hands off via
`execve` or reports a bounded exec failure through a dedicated
`O_CLOEXEC` error pipe -- never a hang. There is no fallback to the
uncontained launch mechanism from this path.

**Preflight** (`cgroup_v2_containment.preflight_check`): probes cgroup v2
mount, delegated-parent existence, create/remove rights, native extension
availability, `clone3()` kernel support, and `cgroup.events`/`cgroup.kill`
accessibility -- all before any validation launch. Any failure raises
`CgroupV2PreflightError` with zero uncontained spawn attempts; there is no
silent fallback for that invocation.

**Launch and identity**: one fresh `wsc-invocation-<id>` cgroup is created
under the delegated parent per run and removed again at the end; no other
cgroup path is ever read, signaled, or removed.

**Escalation order**: process-group `SIGTERM` first (identical timing to
the uncontained path), then bounded exact-scope `cgroup.kill` only if the
grace period expires without exit -- reaching descendants that forked,
detached via `setsid()`, or otherwise left the original process group,
because cgroup membership (not process-group membership) is what
containment relies on.

**Recursive emptiness proof and cleanup**: `termination_confirmed` requires
the kernel's own recursive `cgroup.events` `populated=0` proof (covering
the invocation cgroup and every descendant, not just the direct child)
plus confirmed `rmdir` of that now-empty cgroup. A non-empty cleanup
attempt raises `CgroupV2NotEmptyError` and leaves the cgroup in place
rather than force-removing it.

**Unsupported host / quarantine**: on a host that fails preflight,
containment fails closed with a typed error before any process runs --
callers should route this to the same manual-review/quarantine path used
for other unproven-termination cases, never a silent uncontained retry.

```python
from workflow_scheduler.execution.posix_process_adapter import (
    ContainmentConfig, run_bounded_posix_process,
)

result = run_bounded_posix_process(
    ["some-command"],
    containment=ContainmentConfig(
        delegated_parent_cgroup="/sys/fs/cgroup/agent-os-workflow-scheduler",
        invocation_id="issue-759-attempt-1",
    ),
)
```

## Frozen-Test Validation

### FrozenTestValidationAdapter and Explicit Termination Evidence (AOS-VALTERM1 / #1205)

`FrozenTestValidationAdapter` (`execution/frozen_test_validation_adapter.py`)
is the one-shot `ValidationAdapter` that runs a caller-frozen, immutable set
of required-test commands through an injected `BoundedCommandRunner` and
returns a `PilotValidationObservation`. Command execution stays fully
delegated -- this module owns bounding, aggregation, and evidence, never a
process runner of its own.

`CommandRunObservation`, `FrozenTestValidationResult`, and
`PilotValidationObservation` each carry `started`/`termination_confirmed`/
`possible_partial_effects` -- the same #759 vocabulary
`PosixProcessExecutionResult`/`PilotExecutionObservation` already use for the
executor lane, now threaded through the validation lane too. Before #1205
this evidence stopped at `CommandRunObservation.started`; a validator
returning control (`attempted=True`, `passed=True`) was not, by itself,
proof that every dispatched command's process actually terminated.

`termination_confirmed`/`possible_partial_effects` are always independent of
`outcome`/`return_code`: a command can be `outcome="failed"` (or
`"timed-out"`, `"cancelled"`) while still confirmed terminal, and
`outcome="succeeded"` while termination remains unconfirmed. Neither field
is ever inferred from the other.

```python
from workflow_scheduler.execution.frozen_test_validation_adapter import (
    FrozenTestValidationAdapter, FrozenTestCommand,
)

adapter = FrozenTestValidationAdapter(
    required_test_commands=(FrozenTestCommand(test_id="pytest", argv=("pytest",)),),
    runner=my_bound_posix_command_runner,
)
observation = adapter.validate(request)
if observation.attempted and not observation.termination_confirmed:
    # A command may have started and never confirmed termination even
    # though validate() returned normally -- this is not "safe by default".
    ...
```

**Aggregation** (`_aggregate_command_termination`): conservative over every
command actually dispatched. A command that never started (excluded by an
earlier cancellation, timeout, or budget exhaustion) requires no termination
proof and can never make an otherwise-terminal result look unresolved; zero
started commands is vacuously terminal. `termination_confirmed` requires
every started command to confirm it explicitly; `possible_partial_effects` is
set by any started command reporting it directly, or lacking the required
proof.

**Fail-closed evidence**: a non-bool `termination_confirmed`/
`possible_partial_effects`, or a `started=False` command claiming confirmed
termination, is rejected as malformed -- never silently accepted or defaulted
toward "terminal". Both fields default `False` on `CommandRunObservation`,
so a `BoundedCommandRunner` written before #1205 is read as having proven
nothing, not as having proven safety.

**`BoundPosixCommandRunner`** (`concrete_runtime_adapters.py`) maps
`termination_confirmed`/`possible_partial_effects` straight from the real
`PosixProcessExecutionResult` it obtains via `run_bounded_posix_process`,
unchanged -- the same #759 evidence the executor lane already trusts.

**Scope**: this is evidence only. `PilotValidationObservation` decides no
lease-release policy; #1202 remains the sole owner of when a lease may be
released, and its release fence is not implemented by this module. #1205
makes the explicit validation-termination evidence available for a future
#1202 refresh to consume in place of a weaker call-return proxy.

**Known gap**: `agent-os-execution-service`'s
`validation_lifecycle_evidence.py` serialize/reconstruct round-trip for
`CommandRunObservation`/`FrozenTestValidationResult` does not yet carry these
fields -- a reconstructed evidence bundle reads the conservative default
regardless of what was actually observed. That module's own tests could not
be collected in this environment (pre-existing missing `github` dependency),
so this was flagged rather than fixed here.

## Workspace State Evidence (WSC-AUTO1D)

### `workspace_state_evidence`

Complete, content-addressed workspace-state and changed-path evidence,
reusing `GitWorktreeAdapter`'s own `GitRunner`/`PosixGitRunner` and bounded
process path. Adds no second Git runner, worktree manager, or cleanup
subsystem.

**Path categories** (never collapsed into a single `clean: bool`):
`staged`, `unstaged`, `untracked`, `ignored`, `renamed`, `copied`, `deleted`,
`conflict`, `submodule`. A path can appear in more than one category (for
example a rename that is also further modified in the worktree). `is_clean`
is a derived convenience value computed from every category except
`ignored`; the categories themselves remain the authoritative evidence.

**Completeness rules**: an observation is `complete` only when both
`git worktree list --porcelain -z` and `git status --porcelain=v2 -z`
succeed, exactly one worktree record matches the observed path, the lock
identity (when supplied) matches, and status parsing raised no error.
Timeout, truncation, malformed NUL framing, an unsupported status record
type, a truncated rename/copy pairing, a duplicate/conflicting record, or
more than 512 status records all mark the observation incomplete rather
than guessing. Documented `#` porcelain-v2 header lines are skipped
forward-compatibly; any other unknown record type fails closed.

**Initial/final timing and the validation-only empty-path invariant**:
`WorkspaceLifecycleEvidence` bundles exactly one `initial` and one `final`
`WorkspaceStateObservation`. `initial_blocks_validation` is true when the
initial observation is incomplete or not clean. `final_prevents_success` is
true when the final observation is incomplete or not clean.
`validation_only_success` requires both to be false, and
`satisfies_expected_changed_paths` additionally requires the caller-supplied
expected-changed-paths set to be empty alongside the final observation's
observed changed paths.

**Cleanup proof**: filesystem worktree removal and Git administrative
metadata removal remain the two independent proofs already produced by
`GitWorktreeAdapter.cleanup` (`WorkspaceCleanup.filesystem_removed` and
`WorkspaceCleanup.metadata_removed`); this module does not add or replace
cleanup behavior and adds no destructive Git command.

```python
from workflow_scheduler.execution.workspace_state_evidence import (
    WorkspaceLifecycleEvidence,
)

initial = adapter.inspect_complete_state(handle, observation_kind="initial")
# ... validation-only execution happens here, outside this module ...
final = adapter.inspect_complete_state(handle, observation_kind="final")

evidence = WorkspaceLifecycleEvidence(
    initial=initial, final=final, validation_only=True,
)
assert evidence.validation_only_success
```

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
