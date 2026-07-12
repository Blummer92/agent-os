"""Task executor with lease lock management."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from workflow_scheduler.adapters import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.governance import StopConditionChecker
from workflow_scheduler.models import Task, TaskStatus
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
    """Executes tasks with lease locks and governance checks."""

    def __init__(self, adapter: TaskAdapter, repository: SQLiteRepository, audit_logger: AuditLogger, lease_timeout_seconds: int = 300):
        """Initialize executor.

        Args:
            adapter: TaskAdapter to execute tasks
            repository: SQLiteRepository for persistence
            audit_logger: AuditLogger for compliance tracking
            lease_timeout_seconds: Lease lock timeout in seconds
        """
        self.adapter = adapter
        self.repository = repository
        self.audit_logger = audit_logger
        self.lease_timeout_seconds = lease_timeout_seconds

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
