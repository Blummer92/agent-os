"""Workflow model for Workflow Scheduler."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowStatus(str, Enum):
    """Workflow execution states."""

    DRAFT = "draft"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    GOVERNANCE_BLOCKED = "governance_blocked"


class WorkflowMode(str, Enum):
    """Workflow execution mode."""

    DRAFT = "Draft"
    GATE = "Gate"
    PRODUCTION = "Production"


@dataclass
class WorkflowPlan:
    """Collection of dependent tasks forming a workflow."""

    workflow_id: str
    title: str
    created_by: str
    mode: WorkflowMode = WorkflowMode.DRAFT
    status: WorkflowStatus = WorkflowStatus.DRAFT
    tasks: List[str] = field(default_factory=list)
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_task(self, task_id: str) -> None:
        """Add task to workflow."""
        if task_id not in self.tasks:
            self.tasks.append(task_id)
        self.updated_at = datetime.utcnow()

    def set_dependencies(self, task_id: str, depends_on: List[str]) -> None:
        """Set task dependencies."""
        self.dependencies[task_id] = depends_on
        self.updated_at = datetime.utcnow()

    def mark_running(self) -> None:
        """Mark workflow as running."""
        self.status = WorkflowStatus.RUNNING
        self.updated_at = datetime.utcnow()

    def mark_completed(self) -> None:
        """Mark workflow as completed."""
        self.status = WorkflowStatus.COMPLETED
        self.updated_at = datetime.utcnow()

    def mark_failed(self, reason: str = "") -> None:
        """Mark workflow as failed."""
        self.status = WorkflowStatus.FAILED
        self.updated_at = datetime.utcnow()
        if reason:
            self.metadata["failure_reason"] = reason

    def mark_cancelled(self, reason: str = "") -> None:
        """Mark workflow as cancelled."""
        self.status = WorkflowStatus.CANCELLED
        self.updated_at = datetime.utcnow()
        if reason:
            self.metadata["cancellation_reason"] = reason

    def mark_governance_blocked(self, reason: str = "") -> None:
        """Mark workflow as governance blocked."""
        self.status = WorkflowStatus.GOVERNANCE_BLOCKED
        self.updated_at = datetime.utcnow()
        if reason:
            self.metadata["governance_block_reason"] = reason

    def is_terminal(self) -> bool:
        """Check if workflow is in terminal state."""
        return self.status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.GOVERNANCE_BLOCKED,
        )
