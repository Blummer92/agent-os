"""Tests for request-side adapter input compatibility helpers."""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from workflow_scheduler.adapters import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import (
    Executor,
    build_execution_request_from_task,
    is_execution_request,
)
from workflow_scheduler.models import ExecutionRequest, Task, TaskMode, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


class RecordingAdapter(TaskAdapter):
    """Adapter that records the object received from Executor."""

    def __init__(self):
        self.received = None

    def execute(self, task):
        self.received = task
        return {"success": True, "output": {"received_type": type(task).__name__}}


def make_task(**overrides):
    values = {
        "id": "task-123",
        "workflow_id": "workflow-456",
        "type": "noop",
        "owner": "Unit Alignment Agent",
        "action": "test",
        "idempotency_key": "idem-789",
        "status": TaskStatus.APPROVED,
        "mode": TaskMode.GATE,
        "approval_required": True,
        "payload": {"input": "value"},
        "created_at": datetime(2026, 7, 14, 12, 0, 0),
        "production_ready": True,
        "retry_count": 2,
        "paused_from_status": "retry_scheduled",
        "batch_id": "batch-001",
    }
    values.update(overrides)
    return Task(**values)


def test_build_execution_request_from_task_maps_required_fields():
    task = make_task()

    request = build_execution_request_from_task(
        task,
        execution_id="execution-abc",
        run_id="run-def",
    )

    assert isinstance(request, ExecutionRequest)
    assert request.task_id == task.id
    assert request.workflow_id == task.workflow_id
    assert request.owner == task.owner
    assert request.payload == task.payload
    assert request.idempotency_key == task.idempotency_key
    assert request.mode == task.mode.value
    assert request.approval_required is True
    assert request.production_ready is True
    assert request.execution_id == "execution-abc"
    assert request.run_id == "run-def"
    assert request.created_at == task.created_at


def test_build_execution_request_from_task_preserves_batch_pause_and_attempt_context():
    task = make_task()

    request = build_execution_request_from_task(
        task,
        execution_id="execution-abc",
        run_id="run-def",
    )

    assert request.batch_id == "batch-001"
    assert request.attempt_number == 2
    assert request.execution_context.pause_state == "retry_scheduled"
    assert request.execution_context.approval_state == TaskStatus.APPROVED.value


def test_build_execution_request_from_task_handles_optional_context_defaults():
    task = make_task(
        approval_required=False,
        paused_from_status=None,
        batch_id=None,
        retry_count=0,
        production_ready=False,
    )

    request = build_execution_request_from_task(
        task,
        execution_id="execution-abc",
        run_id="run-def",
    )

    assert request.batch_id is None
    assert request.attempt_number == 0
    assert request.production_ready is False
    assert request.execution_context.approval_state is None
    assert request.execution_context.pause_state is None


def test_execution_request_result_is_immutable():
    task = make_task()
    request = build_execution_request_from_task(
        task,
        execution_id="execution-abc",
        run_id="run-def",
    )

    with pytest.raises(FrozenInstanceError):
        request.task_id = "changed"


def test_is_execution_request_recognizes_request_contract_only():
    task = make_task()
    request = build_execution_request_from_task(
        task,
        execution_id="execution-abc",
        run_id="run-def",
    )

    assert is_execution_request(request) is True
    assert is_execution_request(task) is False
    assert is_execution_request({"task_id": task.id}) is False
    assert is_execution_request(None) is False


def test_executor_still_passes_raw_task_to_adapter():
    adapter = RecordingAdapter()
    repository = SQLiteRepository(":memory:")
    task = make_task()
    repository.create_task(task)

    executor = Executor(
        adapter=adapter,
        repository=repository,
        audit_logger=AuditLogger(),
    )

    result = executor.execute(task)

    assert result.success is True
    assert adapter.received is task
    assert isinstance(adapter.received, Task)
    assert not is_execution_request(adapter.received)
