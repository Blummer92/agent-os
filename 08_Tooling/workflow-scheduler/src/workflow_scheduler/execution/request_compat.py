"""Compatibility helpers for future request-side adapter input."""

from typing import Any

from workflow_scheduler.models import ExecutionContext, ExecutionRequest, Task


def is_execution_request(value: Any) -> bool:
    """Return True when value already uses the request-side contract."""
    return isinstance(value, ExecutionRequest)


def build_execution_request_from_task(
    task: Task,
    *,
    execution_id: str,
    run_id: str,
) -> ExecutionRequest:
    """Build an immutable ExecutionRequest from a legacy Task.

    This helper is intentionally pure and side-effect free. Phase 4C defines
    the compatibility boundary only; Executor still passes raw Task objects to
    adapters until a later migration phase explicitly changes that call site.
    """
    return ExecutionRequest(
        task_id=task.id,
        workflow_id=task.workflow_id,
        owner=task.owner,
        payload=task.payload,
        idempotency_key=task.idempotency_key,
        mode=task.mode.value,
        approval_required=task.approval_required,
        production_ready=task.production_ready,
        execution_id=execution_id,
        run_id=run_id,
        attempt_number=task.retry_count,
        created_at=task.created_at,
        execution_context=ExecutionContext(
            approval_state=task.status.value if task.approval_required else None,
            pause_state=task.paused_from_status,
        ),
        batch_id=task.batch_id,
    )
