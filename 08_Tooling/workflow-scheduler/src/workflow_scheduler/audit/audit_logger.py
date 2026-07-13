"""Audit logger for task and workflow state transitions."""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from workflow_scheduler.models import Task, TaskStatus, WorkflowPlan, WorkflowStatus


@dataclass
class AuditEvent:
    """Single audit log entry."""

    timestamp: str
    event_type: str
    task_id: Optional[str]
    workflow_id: Optional[str]
    status_before: Optional[str]
    status_after: Optional[str]
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class AuditLogger:
    """Logs all task and workflow state transitions for compliance."""

    def __init__(self, repository: Any = None):
        """Initialize audit logger with optional repository backend.

        Args:
            repository: SQLiteRepository or compatible storage backend
        """
        self.repository = repository
        self.events: List[AuditEvent] = []

    def _log(
        self,
        event_type: str,
        task: Optional[Task] = None,
        workflow: Optional[WorkflowPlan] = None,
        status_before: Optional[str] = None,
        status_after: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Internal logging method."""
        event = AuditEvent(
            timestamp=datetime.utcnow().isoformat(),
            event_type=event_type,
            task_id=task.id if task else None,
            workflow_id=workflow.workflow_id if workflow else None,
            status_before=status_before,
            status_after=status_after,
            details=details or {},
        )
        self.events.append(event)

        if self.repository:
            self.repository.log_event(
                event_type=event_type,
                task_id=event.task_id,
                workflow_id=event.workflow_id,
                details=event.to_dict(),
            )

    def log_task_created(self, task: Task) -> None:
        """Log task creation."""
        self._log(
            "task_created",
            task=task,
            status_after=task.status.value,
            details={"action": task.action, "owner": task.owner, "priority": task.priority},
        )

    def log_approval_requested(self, task: Task) -> None:
        """Log creation of a pending approval request for a governed task."""
        self._log(
            "approval_requested",
            task=task,
            status_before=task.status.value,
            status_after=TaskStatus.APPROVAL_PENDING.value,
            details={},
        )

    def log_task_approved(self, task: Task, approved_by: str = "system") -> None:
        """Log task approval."""
        self._log(
            "task_approved",
            task=task,
            status_before=TaskStatus.APPROVAL_PENDING.value,
            status_after=TaskStatus.APPROVED.value,
            details={"approved_by": approved_by},
        )

    def log_task_queued(self, task: Task) -> None:
        """Log task queuing."""
        self._log(
            "task_queued",
            task=task,
            status_before=task.status.value,
            status_after=TaskStatus.QUEUED.value,
            details={},
        )

    def log_task_started(self, task: Task) -> None:
        """Log task execution start."""
        self._log(
            "task_started",
            task=task,
            status_before=TaskStatus.QUEUED.value,
            status_after=TaskStatus.RUNNING.value,
            details={"lease_acquired": datetime.utcnow().isoformat()},
        )

    def log_task_completed(self, task: Task, result: Optional[Dict[str, Any]] = None) -> None:
        """Log task completion."""
        self._log(
            "task_completed",
            task=task,
            status_before=TaskStatus.RUNNING.value,
            status_after=TaskStatus.COMPLETED.value,
            details={"result": result or {}},
        )

    def log_task_failed(self, task: Task, error: str, is_transient: bool = False) -> None:
        """Log task failure."""
        status_after = TaskStatus.RETRY_SCHEDULED.value if is_transient else TaskStatus.FAILED.value
        self._log(
            "task_failed",
            task=task,
            status_before=TaskStatus.RUNNING.value,
            status_after=status_after,
            details={"error": error, "is_transient": is_transient},
        )

    def log_adapter_result_invalid(self, task: Task, reason: str) -> None:
        """Log that an adapter returned a malformed/unusable result (or
        raised instead of returning). The task is marked FAILED, not
        retried -- an adapter that can't produce a valid result is a
        contract violation, not a transient condition."""
        self._log(
            "adapter_result_invalid",
            task=task,
            status_before=TaskStatus.RUNNING.value,
            status_after=TaskStatus.FAILED.value,
            details={"reason": reason},
        )

    def log_retry_scheduled(self, task: Task, delay_seconds: float) -> None:
        """Log that a transient failure was scheduled for retry."""
        self._log(
            "retry_scheduled",
            task=task,
            status_before=TaskStatus.RUNNING.value,
            status_after=TaskStatus.RETRY_SCHEDULED.value,
            details={
                "retry_count": task.retry_count,
                "next_retry_at": task.next_retry_at.isoformat() if task.next_retry_at else None,
                "delay_seconds": delay_seconds,
            },
        )

    def log_retry_exhausted(self, task: Task, attempts: int) -> None:
        """Log that a task exhausted its retry budget and will be marked failed."""
        self._log(
            "retry_exhausted",
            task=task,
            status_before=TaskStatus.RETRY_SCHEDULED.value,
            status_after=TaskStatus.FAILED.value,
            details={"attempts": attempts, "max_retries": task.max_retries},
        )

    def log_task_paused(self, task: Task, previous_status: Optional[str] = None) -> None:
        """Log task pause.

        Args:
            task: The paused task (status already mutated to PAUSED)
            previous_status: The task's status immediately before pausing.
                Callers should capture this before mutating the task, since
                pause is reachable from many different prior statuses.
                Falls back to task.status.value (only correct if called
                before mutation) when omitted, for backward compatibility.
        """
        self._log(
            "task_paused",
            task=task,
            status_before=previous_status if previous_status is not None else task.status.value,
            status_after=TaskStatus.PAUSED.value,
            details={},
        )

    def log_task_resumed(self, task: Task, restored_status: str) -> None:
        """Log task resume from pause.

        Args:
            task: The resumed task
            restored_status: The status the task was restored to
        """
        self._log(
            "task_resumed",
            task=task,
            status_before=TaskStatus.PAUSED.value,
            status_after=restored_status,
            details={},
        )

    def log_task_cancelled(self, task: Task, previous_status: Optional[str] = None, reason: str = "") -> None:
        """Log task cancellation.

        Args:
            task: The cancelled task (status already mutated to CANCELLED)
            previous_status: The task's status immediately before cancelling.
                Callers should capture this before mutating the task, since
                cancel is reachable from many different prior statuses.
                Falls back to task.status.value (only correct if called
                before mutation) when omitted, for backward compatibility.
            reason: Cancellation reason
        """
        self._log(
            "task_cancelled",
            task=task,
            status_before=previous_status if previous_status is not None else task.status.value,
            status_after=TaskStatus.CANCELLED.value,
            details={"reason": reason},
        )

    def log_governance_blocked(self, task: Task, blockers: List[str], reason: str = "") -> None:
        """Log governance-based execution block."""
        self._log(
            "governance_blocked",
            task=task,
            status_before=task.status.value,
            status_after=TaskStatus.GOVERNANCE_BLOCKED.value,
            details={"blockers": blockers, "reason": reason},
        )

    def log_governance_check_passed(self, task: Task) -> None:
        """Log successful governance check."""
        self._log(
            "governance_check_passed",
            task=task,
            details={"checks": ["stop_conditions", "authorization", "source_of_truth"]},
        )

    def log_workflow_created(self, workflow: WorkflowPlan) -> None:
        """Log workflow creation."""
        self._log(
            "workflow_created",
            workflow=workflow,
            status_after=workflow.status.value,
            details={"title": workflow.title, "created_by": workflow.created_by},
        )

    def log_workflow_started(self, workflow: WorkflowPlan) -> None:
        """Log workflow start."""
        self._log(
            "workflow_started",
            workflow=workflow,
            status_before=WorkflowStatus.PENDING.value,
            status_after=WorkflowStatus.RUNNING.value,
            details={},
        )

    def log_workflow_completed(self, workflow: WorkflowPlan) -> None:
        """Log workflow completion."""
        self._log(
            "workflow_completed",
            workflow=workflow,
            status_before=WorkflowStatus.RUNNING.value,
            status_after=WorkflowStatus.COMPLETED.value,
            details={},
        )

    def log_workflow_failed(self, workflow: WorkflowPlan, reason: str = "") -> None:
        """Log workflow failure."""
        self._log(
            "workflow_failed",
            workflow=workflow,
            status_before=WorkflowStatus.RUNNING.value,
            status_after=WorkflowStatus.FAILED.value,
            details={"reason": reason},
        )

    def log_workflow_paused(self, workflow: WorkflowPlan, previous_status: Optional[str] = None, reason: str = "") -> None:
        """Log workflow pause.

        Args:
            workflow: The paused workflow (status already mutated to PAUSED)
            previous_status: The workflow's status immediately before
                pausing. Pause is reachable from any non-terminal,
                non-PAUSED status (DRAFT, PENDING, RUNNING), so callers
                should capture this before mutation. Falls back to
                RUNNING.value (only correct for the RUNNING case) when
                omitted, for backward compatibility.
            reason: Pause reason
        """
        self._log(
            "workflow_paused",
            workflow=workflow,
            status_before=previous_status if previous_status is not None else WorkflowStatus.RUNNING.value,
            status_after=WorkflowStatus.PAUSED.value,
            details={"reason": reason},
        )

    def log_workflow_resumed(self, workflow: WorkflowPlan) -> None:
        """Log workflow resume from pause."""
        self._log(
            "workflow_resumed",
            workflow=workflow,
            status_before=WorkflowStatus.PAUSED.value,
            status_after=WorkflowStatus.RUNNING.value,
            details={},
        )

    def log_workflow_cancelled(self, workflow: WorkflowPlan, previous_status: Optional[str] = None, reason: str = "") -> None:
        """Log workflow cancellation.

        Args:
            workflow: The cancelled workflow (status already mutated to CANCELLED)
            previous_status: The workflow's status immediately before
                cancelling. Cancel is reachable from multiple prior
                statuses, so callers should capture this before mutation.
            reason: Cancellation reason
        """
        self._log(
            "workflow_cancelled",
            workflow=workflow,
            status_before=previous_status if previous_status is not None else workflow.status.value,
            status_after=WorkflowStatus.CANCELLED.value,
            details={"reason": reason},
        )

    def log_batch_result(self, workflow: WorkflowPlan, batch_id: str, status: str, task_ids: List[str]) -> None:
        """Log the rollup outcome of a batch dispatch pass.

        A batch has no status transition of its own (it is not a Task or
        WorkflowPlan) — this records a point-in-time rollup snapshot, not
        an authoritative state machine transition.

        Args:
            workflow: The workflow the batch belongs to
            batch_id: The batch identifier
            status: Rollup status ("completed", "failed", "partial", or
                "not_started")
            task_ids: Current member task IDs
        """
        self._log(
            "batch_result",
            workflow=workflow,
            details={"batch_id": batch_id, "status": status, "task_ids": task_ids},
        )

    def get_events(self, task_id: Optional[str] = None, workflow_id: Optional[str] = None) -> List[AuditEvent]:
        """Retrieve audit events."""
        events = self.events
        if task_id:
            events = [e for e in events if e.task_id == task_id]
        if workflow_id:
            events = [e for e in events if e.workflow_id == workflow_id]
        return events
