"""Immutable request-side adapter contract models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ExecutionContext:
    """Optional governance and tracing metadata for adapter execution."""

    approval_state: Optional[str] = None
    approval_context: Optional[Dict[str, Any]] = None
    batch_metadata: Optional[Dict[str, Any]] = None
    pause_state: Optional[str] = None


@dataclass(frozen=True)
class ExecutionRequest:
    """Immutable read-only execution input for future adapter calls."""

    task_id: str
    workflow_id: str
    owner: str
    payload: Dict[str, Any]
    idempotency_key: str
    mode: str
    approval_required: bool
    production_ready: bool
    execution_id: str
    run_id: str
    attempt_number: int
    created_at: datetime
    execution_context: ExecutionContext
    batch_id: Optional[str] = None
