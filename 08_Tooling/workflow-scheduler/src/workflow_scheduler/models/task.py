"""Task model for Workflow Scheduler."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(str, Enum):
    """Task execution states."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    COMPLETED = "completed"
    FAILED = "failed"
    GOVERNANCE_BLOCKED = "governance_blocked"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class TaskMode(str, Enum):
    """Task execution mode."""

    DRAFT = "Draft"
    GATE = "Gate"
    PRODUCTION = "Production"


@dataclass
class Task:
    """Individual work unit in a workflow."""

    id: str
    workflow_id: str
    type: str
    owner: str
    action: str
    idempotency_key: str
    status: TaskStatus = TaskStatus.DRAFT
    mode: TaskMode = TaskMode.DRAFT
    priority: int = 0
    approval_required: bool = False
    depends_on: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    lease_lock: Optional[datetime] = None
    production_ready: bool = False
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None
    max_retries: int = 3
    paused_from_status: Optional[str] = None
    batch_id: Optional[str] = None

    def mark_approved(self) -> None:
        """Mark task as approved."""
        self.status = TaskStatus.APPROVED
        self.updated_at = datetime.utcnow()

    def mark_approval_pending(self) -> None:
        """Mark task as awaiting explicit approval decision."""
        self.status = TaskStatus.APPROVAL_PENDING
        self.updated_at = datetime.utcnow()

    def mark_completed(self, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.updated_at = datetime.utcnow()
        if result:
            self.payload["result"] = result

    def mark_failed(self, error: str, is_transient: bool = False) -> None:
        """Mark task as failed."""
        if is_transient:
            self.status = TaskStatus.RETRY_SCHEDULED
        else:
            self.status = TaskStatus.FAILED
        self.updated_at = datetime.utcnow()
        self.payload["error"] = error

    def schedule_retry(self, delay_seconds: float) -> None:
        """Schedule task for retry after a transient failure."""
        self.retry_count += 1
        self.next_retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
        self.status = TaskStatus.RETRY_SCHEDULED
        self.updated_at = datetime.utcnow()

    def mark_paused(self) -> None:
        """Mark task as paused, remembering its exact prior status for resume."""
        self.paused_from_status = self.status.value
        self.status = TaskStatus.PAUSED
        self.updated_at = datetime.utcnow()

    def resume(self) -> None:
        """Restore a paused task to its exact prior status.

        Raises:
            ValueError: If the task is not PAUSED, or has no valid recorded
                prior status to restore.
        """
        if self.status != TaskStatus.PAUSED:
            raise ValueError(f"Cannot resume task not in PAUSED status (current: {self.status.value})")
        if not self.paused_from_status:
            raise ValueError("Cannot resume task with no recorded prior status")
        try:
            restored_status = TaskStatus(self.paused_from_status)
        except ValueError:
            raise ValueError(f"Cannot resume task: invalid prior status recorded: {self.paused_from_status}")

        self.status = restored_status
        self.paused_from_status = None
        self.updated_at = datetime.utcnow()

    def mark_cancelled(self, reason: str = "") -> None:
        """Mark task as cancelled."""
        self.status = TaskStatus.CANCELLED
        self.updated_at = datetime.utcnow()
        if reason:
            self.payload["cancellation_reason"] = reason

    def acquire_lease(self) -> None:
        """Acquire execution lease lock."""
        self.lease_lock = datetime.utcnow()
        self.status = TaskStatus.RUNNING

    def release_lease(self) -> None:
        """Release execution lease lock."""
        self.lease_lock = None

    def is_ready_to_run(self) -> bool:
        """Check if task is ready for execution."""
        return self.status == TaskStatus.APPROVED and self.lease_lock is None

    def has_active_lease(self, timeout_seconds: int = 300) -> bool:
        """Check if task has active lease lock."""
        if self.lease_lock is None:
            return False
        elapsed = (datetime.utcnow() - self.lease_lock).total_seconds()
        return elapsed < timeout_seconds

    def is_completed(self) -> bool:
        """Check if task is in terminal state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.GOVERNANCE_BLOCKED,
            TaskStatus.CANCELLED,
        )
