"""Task model for Workflow Scheduler."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from workflow_scheduler.time_utils import ensure_utc, utc_now


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


_TERMINAL_STATUSES = frozenset({
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.GOVERNANCE_BLOCKED,
    TaskStatus.CANCELLED,
})


@dataclass
class Task:
    """Individual work unit in a workflow.

    Terminal states reject transition methods. The model mutates local task
    state; the repository owns durable claims, settlement and audit history.
    """

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
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    lease_lock: Optional[datetime] = None
    production_ready: bool = False
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None
    max_retries: int = 3
    paused_from_status: Optional[str] = None
    batch_id: Optional[str] = None

    def __post_init__(self) -> None:
        self.depends_on = self.depends_on.copy()
        self.payload = deepcopy(self.payload)

    def _require_nonterminal(self) -> None:
        if self.is_completed():
            raise ValueError("Cannot transition a terminal task")

    def mark_approved(self) -> None:
        """Mark task as approved; repeating approval is a no-op."""
        self._require_nonterminal()
        if self.status is TaskStatus.APPROVED:
            return
        self.status = TaskStatus.APPROVED
        self.updated_at = utc_now()

    def mark_approval_pending(self) -> None:
        """Mark task as awaiting explicit approval decision."""
        self._require_nonterminal()
        self.status = TaskStatus.APPROVAL_PENDING
        self.updated_at = utc_now()

    def mark_completed(self, result: Optional[Dict[str, Any]] = None) -> None:
        """Settle local state; the repository still fences durable completion."""
        self._require_nonterminal()
        if result is not None:
            self.payload["result"] = deepcopy(result)
        self.status = TaskStatus.COMPLETED
        self.updated_at = utc_now()
        self.release_lease()

    def mark_failed(self, error: str, is_transient: bool = False) -> None:
        """Record a failed attempt; only schedule_retry debits the retry budget."""
        self._require_nonterminal()
        if is_transient:
            self.status = TaskStatus.RETRY_SCHEDULED
        else:
            self.status = TaskStatus.FAILED
        self.updated_at = utc_now()
        self.payload["error"] = error
        self.release_lease()

    def schedule_retry(self, delay_seconds: float) -> None:
        """Schedule task for retry after a transient failure."""
        self._require_nonterminal()
        self.retry_count += 1
        self.next_retry_at = utc_now() + timedelta(seconds=delay_seconds)
        self.status = TaskStatus.RETRY_SCHEDULED
        self.updated_at = utc_now()

    def mark_paused(self) -> None:
        """Mark task as paused, remembering its exact prior status for resume."""
        self._require_nonterminal()
        if self.status is TaskStatus.PAUSED:
            raise ValueError("Task is already paused")
        self.paused_from_status = self.status.value
        self.status = TaskStatus.PAUSED
        self.updated_at = utc_now()

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

        if restored_status is TaskStatus.PAUSED or restored_status in _TERMINAL_STATUSES:
            raise ValueError("Cannot resume task to a paused or terminal status")

        self.status = restored_status
        self.paused_from_status = None
        self.updated_at = utc_now()

    def mark_cancelled(self, reason: str = "") -> None:
        """Mark task as cancelled after the caller has checked claim ownership."""
        self._require_nonterminal()
        self.status = TaskStatus.CANCELLED
        self.updated_at = utc_now()
        if reason:
            self.payload["cancellation_reason"] = reason

    def acquire_lease(self, *, at: Optional[datetime] = None) -> None:
        """Record a local lease; paused work and existing leases are not overridden."""
        self._require_nonterminal()
        if self.status is TaskStatus.PAUSED:
            raise ValueError("Cannot acquire a lease for a paused task")
        if self.lease_lock is not None:
            raise ValueError("Task already holds a lease")
        self.lease_lock = utc_now() if at is None else ensure_utc(at)
        self.status = TaskStatus.RUNNING

    def release_lease(self) -> None:
        """Clear the local lease timestamp without changing lifecycle status."""
        self.lease_lock = None

    def is_ready_to_run(self) -> bool:
        """Check if task is ready for execution."""
        return self.status == TaskStatus.APPROVED and self.lease_lock is None

    def has_active_lease(self, timeout_seconds: int = 300, *, now: Optional[datetime] = None) -> bool:
        """Check the lease at an explicit time or the current UTC time.

        Exactly at timeout the lease is expired. A future lease remains active
        rather than permitting another claimant when clocks disagree.
        """
        if self.lease_lock is None:
            return False
        observed_at = utc_now() if now is None else ensure_utc(now)
        elapsed = (observed_at - ensure_utc(self.lease_lock)).total_seconds()
        return elapsed < timeout_seconds

    def is_completed(self) -> bool:
        """Check if task is in terminal state."""
        return self.status in _TERMINAL_STATUSES
