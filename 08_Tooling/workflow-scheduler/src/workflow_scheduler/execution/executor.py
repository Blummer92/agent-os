"""Task executor with lease lock management."""

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from workflow_scheduler.adapters import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution.retry_manager import RetryManager
from workflow_scheduler.governance import StopConditionChecker
from workflow_scheduler.models import ApprovalDecision, ApprovalRequest, Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


@dataclass
class ExecutionResult:
    """Result of task execution."""

    success: bool
    error: Optional[str]
    output: Optional[Dict[str, Any]]
    is_transient: bool = False
    status: str = "pass"
    blockers: list[str] = None
    checks_passed: list[str] = None
    checks_failed: list[str] = None

    def __post_init__(self) -> None:
        """Initialize list fields if None."""
        if self.blockers is None:
            self.blockers = []
        if self.checks_passed is None:
            self.checks_passed = []
        if self.checks_failed is None:
            self.checks_failed = []


class Executor:
    """Executes tasks with lease locks and governance checks.

    Safe to dispatch multiple independent tasks concurrently via
    execute_many() when max_workers > 1: the repository is thread-safe
    (SQLiteRepository serializes all access through its own lock),
    StopConditionChecker is stateless, and the bundled NoopAdapter/
    AuditLogger only ever append to plain lists, which CPython's GIL
    makes safe against structural corruption from concurrent appends.
    """

    def __init__(
        self,
        adapter: TaskAdapter,
        repository: SQLiteRepository,
        audit_logger: AuditLogger,
        lease_timeout_seconds: int = 300,
        max_workers: int = 1,
    ):
        """Initialize executor.

        Args:
            adapter: TaskAdapter to execute tasks
            repository: SQLiteRepository for persistence
            audit_logger: AuditLogger for compliance tracking
            lease_timeout_seconds: Lease lock timeout in seconds
            max_workers: Maximum tasks to run concurrently in execute_many().
                Defaults to 1 (fully sequential, same behavior as before
                execute_many existed). Must be >= 1.
        """
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")

        self.adapter = adapter
        self.repository = repository
        self.audit_logger = audit_logger
        self.lease_timeout_seconds = lease_timeout_seconds
        self.max_workers = max_workers

    def execute(self, task: Task, ownership_registry: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """Execute a task with governance checks and lease locking.

        Args:
            task: Task to execute
            ownership_registry: Registry for ownership verification

        Returns:
            ExecutionResult with success status and output
        """
        # Check stop conditions first
        stop_result = StopConditionChecker.check_all_stop_conditions(
            task=task,
            ownership_registry=ownership_registry,
            source_of_truth_db=self.repository,
        )

        if stop_result.is_blocked:
            # A task blocked solely by approval_engine_deferred awaits an explicit
            # human decision rather than being hard-blocked. Any other blocker
            # (alone or alongside approval_engine_deferred) is still a hard block.
            if stop_result.blockers == [StopConditionChecker.APPROVAL_ENGINE_DEFERRED]:
                approval = self.repository.get_approval_request(task.id)

                if approval is not None and approval.decision == ApprovalDecision.REJECTED:
                    # Already decided against; a rejected task is a hard block,
                    # not a pending one — do not overwrite its cancelled state.
                    self.audit_logger.log_governance_blocked(
                        task=task,
                        blockers=stop_result.blockers,
                        reason="Task was rejected by approver",
                    )
                    task.status = TaskStatus.GOVERNANCE_BLOCKED
                    self.repository.update_task(task)

                    return ExecutionResult(
                        success=False,
                        error="Task was rejected by approver",
                        output=None,
                        is_transient=False,
                        status="blocked",
                        blockers=stop_result.blockers,
                        checks_failed=stop_result.blockers,
                    )

                if approval is None:
                    approval = ApprovalRequest(
                        id=str(uuid.uuid4()),
                        task_id=task.id,
                        requested_by=task.owner,
                        decision=ApprovalDecision.PENDING,
                    )
                    self.repository.create_approval_request(approval)
                    self.audit_logger.log_approval_requested(task)

                task.mark_approval_pending()
                self.repository.update_task(task)

                return ExecutionResult(
                    success=False,
                    error="Task requires explicit approval before execution",
                    output=None,
                    is_transient=False,
                    status="blocked",
                    blockers=stop_result.blockers,
                    checks_failed=stop_result.blockers,
                )

            self.audit_logger.log_governance_blocked(
                task=task,
                blockers=stop_result.blockers,
                reason=stop_result.reason,
            )
            task.status = TaskStatus.GOVERNANCE_BLOCKED
            self.repository.update_task(task)

            return ExecutionResult(
                success=False,
                error=stop_result.reason,
                output=None,
                is_transient=False,
                status="blocked",
                blockers=stop_result.blockers,
                checks_failed=stop_result.blockers,
            )

        # Governance checks passed
        self.audit_logger.log_governance_check_passed(task)

        # Acquire lease lock
        if not self._acquire_lease(task):
            return ExecutionResult(
                success=False,
                error="Could not acquire execution lease",
                output=None,
                is_transient=True,
                status="fail",
                checks_failed=["lease_acquisition"],
            )

        try:
            # Execute task via adapter
            adapter_result = self.adapter.execute(task)

            if adapter_result.get("success"):
                task.mark_completed(result=adapter_result.get("output"))
                self.audit_logger.log_task_completed(task, result=adapter_result.get("output"))
                self.repository.update_task(task)

                return ExecutionResult(
                    success=True,
                    error=None,
                    output=adapter_result.get("output"),
                    is_transient=False,
                    status="pass",
                    checks_passed=["execution"],
                )
            else:
                error = adapter_result.get("error", "Unknown error")
                is_transient = adapter_result.get("is_transient", False)

                if is_transient and RetryManager.should_retry(task):
                    delay = RetryManager.compute_delay(task.retry_count)
                    task.payload["error"] = error
                    task.schedule_retry(delay)
                    self.audit_logger.log_retry_scheduled(task, delay_seconds=delay)
                    self.repository.update_task(task)

                    return ExecutionResult(
                        success=False,
                        error=error,
                        output=None,
                        is_transient=True,
                        status="retry_scheduled",
                        checks_failed=["execution"],
                    )

                if is_transient:
                    # Retry budget exhausted; this transient failure is now terminal.
                    self.audit_logger.log_retry_exhausted(task, attempts=task.retry_count)

                task.mark_failed(error=error, is_transient=False)
                self.audit_logger.log_task_failed(task, error=error, is_transient=False)
                self.repository.update_task(task)

                return ExecutionResult(
                    success=False,
                    error=error,
                    output=None,
                    is_transient=False,
                    status="fail",
                    checks_failed=["execution"],
                )

        finally:
            # Release lease lock
            self._release_lease(task)

    def execute_many(
        self,
        tasks: List[Task],
        ownership_registry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, ExecutionResult]:
        """Execute a set of mutually independent tasks, one call to execute()
        per task, sequentially or concurrently depending on max_workers.

        Callers are responsible for ensuring the given tasks have no
        dependencies on each other (e.g. one readiness pass of
        DependencyResolver.get_ready_tasks) -- this method does not check
        or enforce dependency ordering; it only controls how many of the
        given tasks run at once.

        Args:
            tasks: Independent tasks to execute.
            ownership_registry: Registry for ownership verification, passed
                through unchanged to every execute() call.

        Returns:
            Dict mapping task.id -> ExecutionResult, one entry per input
            task, regardless of max_workers.
        """
        if self.max_workers == 1:
            return {task.id: self.execute(task, ownership_registry) for task in tasks}

        results: Dict[str, ExecutionResult] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_task_id = {
                pool.submit(self.execute, task, ownership_registry): task.id for task in tasks
            }
            for future in as_completed(future_to_task_id):
                task_id = future_to_task_id[future]
                results[task_id] = future.result()
        return results

    def _acquire_lease(self, task: Task) -> bool:
        """Acquire execution lease lock for a task.

        Args:
            task: Task to acquire lease for

        Returns:
            True if lease acquired, False if already held
        """
        # Check if task already has active lease
        if task.has_active_lease(timeout_seconds=self.lease_timeout_seconds):
            return False

        # Acquire lease
        task.acquire_lease()
        self.repository.update_task(task)
        return True

    def _release_lease(self, task: Task) -> None:
        """Release execution lease lock for a task.

        Args:
            task: Task to release lease for
        """
        task.release_lease()
        self.repository.update_task(task)
