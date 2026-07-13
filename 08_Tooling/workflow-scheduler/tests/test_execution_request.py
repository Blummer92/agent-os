"""Tests for request-side adapter contract models."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from workflow_scheduler.models import ExecutionContext, ExecutionRequest


def _sample_created_at() -> datetime:
    return datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)


def _sample_request(**overrides):
    values = {
        "task_id": "task-123",
        "workflow_id": "workflow-456",
        "owner": "agent-a",
        "payload": {"action": "read", "target": "example"},
        "idempotency_key": "idem-789",
        "mode": "DRAFT",
        "approval_required": False,
        "production_ready": True,
        "execution_id": "execution-abc",
        "run_id": "run-def",
        "attempt_number": 0,
        "created_at": _sample_created_at(),
        "execution_context": ExecutionContext(),
    }
    values.update(overrides)
    return ExecutionRequest(**values)


def test_execution_context_defaults_are_none():
    context = ExecutionContext()

    assert context.approval_state is None
    assert context.approval_context is None
    assert context.batch_metadata is None
    assert context.pause_state is None


def test_execution_context_accepts_optional_fields():
    context = ExecutionContext(
        approval_state="APPROVED",
        approval_context={"approved_by": "user", "reason": "ok"},
        batch_metadata={"batch_id": "batch-1", "batch_position": 2},
        pause_state="READY",
    )

    assert context.approval_state == "APPROVED"
    assert context.approval_context == {"approved_by": "user", "reason": "ok"}
    assert context.batch_metadata == {"batch_id": "batch-1", "batch_position": 2}
    assert context.pause_state == "READY"


def test_execution_request_construction():
    created_at = _sample_created_at()
    context = ExecutionContext(approval_state="APPROVED")

    request = _sample_request(created_at=created_at, execution_context=context)

    assert request.task_id == "task-123"
    assert request.workflow_id == "workflow-456"
    assert request.owner == "agent-a"
    assert request.payload == {"action": "read", "target": "example"}
    assert request.idempotency_key == "idem-789"
    assert request.mode == "DRAFT"
    assert request.approval_required is False
    assert request.production_ready is True
    assert request.execution_id == "execution-abc"
    assert request.run_id == "run-def"
    assert request.attempt_number == 0
    assert request.created_at == created_at
    assert request.execution_context == context


def test_execution_request_uses_nested_execution_context():
    context = ExecutionContext(batch_metadata={"batch_id": "batch-1"})
    request = _sample_request(execution_context=context)

    assert request.execution_context is context
    assert request.execution_context.batch_metadata == {"batch_id": "batch-1"}


def test_execution_context_is_frozen():
    context = ExecutionContext()

    with pytest.raises(FrozenInstanceError):
        context.approval_state = "APPROVED"


def test_execution_request_is_frozen():
    request = _sample_request()

    with pytest.raises(FrozenInstanceError):
        request.attempt_number = 1


def test_attempt_number_preserves_zero_indexed_integer():
    first_attempt = _sample_request(attempt_number=0)
    first_retry = _sample_request(attempt_number=1)

    assert first_attempt.attempt_number == 0
    assert first_retry.attempt_number == 1
    assert isinstance(first_attempt.attempt_number, int)


def test_created_at_accepts_datetime():
    created_at = _sample_created_at()
    request = _sample_request(created_at=created_at)

    assert request.created_at == created_at
    assert isinstance(request.created_at, datetime)


def test_batch_id_defaults_to_none():
    request = _sample_request()

    assert request.batch_id is None


def test_batch_id_accepts_value():
    request = _sample_request(batch_id="batch-1")

    assert request.batch_id == "batch-1"
