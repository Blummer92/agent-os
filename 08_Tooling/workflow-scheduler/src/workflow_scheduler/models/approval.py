"""Approval request model for explicit human sign-off on governed tasks."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from workflow_scheduler.time_utils import utc_now


class ApprovalDecision(str, Enum):
    """Decision state of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ApprovalRequest:
    """Explicit human approval record gating a task blocked by approval_engine_deferred."""

    id: str
    task_id: str
    requested_by: str
    approver: Optional[str] = None
    decision: ApprovalDecision = ApprovalDecision.PENDING
    reason: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    decided_at: Optional[datetime] = None
