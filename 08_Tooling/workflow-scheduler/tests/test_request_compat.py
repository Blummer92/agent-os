"""Tests for request-side adapter input compatibility."""

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


class RecordingLegacyAdapter(TaskAdapter):
    def __init__(self):
        self.received = []

    def execute(self, task):
        self.received.append(task)
        return {"success": True, "output": {"received_type": type(task).__name__}}


class RecordingRequestAdapter(TaskAdapter):
    accepts_execution_request = True

    def __init__(self):
        self.received = []

    def execute(self, request):
        self.received.append(request)
        return {"success": True, "output": {"task_id": request.task_id}}


def make_task(task_id: str = "task-123", **overrides):
    values = {
        "id": task_id,
        "workflow_id": "workflow-456",
        "type": "noop",
        "owner": "Unit Alignment Agent",
        "action": "test",
        "idempotency_key": f"idem-{task_id}",
        "status": TaskStatus.APPROVED,
        "mode": TaskMode.GATE,
        "approval_required": False,
        "payload": {"input": "value"},
        "created_at": datetime(2026, 7, 14, 12, 0, 0),
        "production_ready": False,
        "retry_count": 2,
        "paused_from_status": "retry_scheduled",
        "batch_id": "batch-001",
    }
    values.update(overrides)
    return Task(**values)


def test_build_execution_request_from_task_maps_required_fields():
    task = make_task(approval_required=True, production_ready=True)
    request = build_execution_request_from_task(
        task, execution_id="execution-abc", run_id="run-def"
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


def test_build_execution_request_preserves_optional_context():
    request = build_execution_request_from_task(
        make_task(approval_required=True),
        execution_id="execution-abc",
        run_id="run-def",
    )
    assert request.batch_id == "batch-001"
    assert request.attempt_number == 2
    assert request.execution_context.pause_state == "retry_scheduled"
    assert request.execution_context.approval_state == TaskStatus.APPROVED.value


def test_execution_request_is_immutable_and_recognized():
    task = make_task()
    request = build_execution_request_from_task(
        task, execution_id="execution-abc", run_id="run-def"
    )
    with pytest.raises(FrozenInstanceError):
        request.task_id = "changed"
    assert is_execution_request(request) is True
    assert is_execution_request(task) is False


def test_legacy_adapter_still_receives_raw_task():
    adapter = RecordingLegacyAdapter()
    repository = SQLiteRepository(":memory:")
    task = make_task()
    repository.create_task(task)
    result = Executor(adapter, repository, AuditLogger()).execute(task)
    assert result.success is True
    assert adapter.received == [task]
    assert isinstance(adapter.received[0], Task)


def test_opted_in_adapter_receives_execution_request():
    adapter = RecordingRequestAdapter()
    repository = SQLiteRepository(":memory:")
    task = make_task()
    repository.create_task(task)
    result = Executor(
        adapter, repository, AuditLogger(), run_id="run-stable"
    ).execute(task)
    assert result.success is True
    request = adapter.received[0]
    assert isinstance(request, ExecutionRequest)
    assert request.task_id == task.id
    assert request.run_id == "run-stable"
    assert request.attempt_number == task.retry_count


def test_run_id_is_stable_and_execution_ids_are_unique():
    adapter = RecordingRequestAdapter()
    repository = SQLiteRepository(":memory:")
    tasks = [make_task("task-1"), make_task("task-2")]
    for task in tasks:
        repository.create_task(task)
    executor = Executor(adapter, repository, AuditLogger(), run_id="run-stable")
    for task in tasks:
        executor.execute(task)
    assert {request.run_id for request in adapter.received} == {"run-stable"}
    assert len({request.execution_id for request in adapter.received}) == 2
