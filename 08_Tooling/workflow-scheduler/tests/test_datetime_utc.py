"""Focused timezone-aware UTC and legacy persistence compatibility tests."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import RetryManager
from workflow_scheduler.models import ApprovalRequest, Task, WorkflowPlan
from workflow_scheduler.repository import SQLiteRepository
from workflow_scheduler.time_utils import ensure_utc, parse_utc_storage, utc_now, utc_storage_string


def make_task(task_id: str = "task-utc") -> Task:
    return Task(
        id=task_id,
        workflow_id="workflow-utc",
        type="test",
        owner="system",
        action="test_action",
        idempotency_key=f"key-{task_id}",
    )


def test_runtime_defaults_are_timezone_aware_utc():
    task = make_task()
    workflow = WorkflowPlan(
        workflow_id="workflow-utc",
        title="UTC Workflow",
        created_by="test",
    )
    approval = ApprovalRequest(
        id="approval-utc",
        task_id=task.id,
        requested_by="test",
    )

    for value in (
        utc_now(),
        task.created_at,
        task.updated_at,
        workflow.created_at,
        workflow.updated_at,
        approval.created_at,
    ):
        assert value.tzinfo is UTC
        assert value.utcoffset() == timedelta(0)


def test_helpers_normalize_legacy_and_offset_aware_values():
    legacy = datetime(2026, 1, 2, 3, 4, 5, 123456)
    plus_two = datetime(2026, 1, 2, 5, 4, 5, 123456, tzinfo=timezone(timedelta(hours=2)))

    assert ensure_utc(legacy) == datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
    assert ensure_utc(plus_two) == datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
    assert utc_storage_string(plus_two) == "2026-01-02T03:04:05.123456"
    assert parse_utc_storage("2026-01-02T03:04:05.123456").tzinfo is UTC
    assert parse_utc_storage("2026-01-02T03:04:05.123456+00:00").tzinfo is UTC


def test_sqlite_writes_keep_legacy_offset_free_format_and_round_trip(tmp_path):
    db_path = str(tmp_path / "utc.db")
    repository = SQLiteRepository(db_path)
    workflow = WorkflowPlan(
        workflow_id="workflow-utc",
        title="UTC Workflow",
        created_by="test",
    )
    task = make_task()
    task.acquire_lease()
    task.schedule_retry(delay_seconds=30)
    approval = ApprovalRequest(
        id="approval-utc",
        task_id=task.id,
        requested_by="test",
    )

    repository.create_workflow(workflow)
    repository.create_task(task)
    repository.create_approval_request(approval)
    repository.log_event("utc_test", task_id=task.id, details={"ok": True})
    repository.close()

    connection = sqlite3.connect(db_path)
    workflow_row = connection.execute(
        "SELECT created_at, updated_at FROM workflows WHERE workflow_id = ?",
        (workflow.workflow_id,),
    ).fetchone()
    task_row = connection.execute(
        "SELECT created_at, updated_at, lease_lock, next_retry_at FROM tasks WHERE id = ?",
        (task.id,),
    ).fetchone()
    approval_row = connection.execute(
        "SELECT created_at FROM approval_requests WHERE id = ?",
        (approval.id,),
    ).fetchone()
    audit_row = connection.execute(
        "SELECT timestamp, created_at, details FROM audit_log WHERE task_id = ?",
        (task.id,),
    ).fetchone()
    connection.close()

    values = [*workflow_row, *task_row, *approval_row, audit_row[0], audit_row[1]]
    assert all("+00:00" not in value and not value.endswith("Z") for value in values)
    assert json.loads(audit_row[2]) == {"ok": True}

    reopened = SQLiteRepository(db_path)
    stored_workflow = reopened.get_workflow(workflow.workflow_id)
    stored_task = reopened.get_task(task.id)
    stored_approval = reopened.get_approval_request(task.id)

    assert stored_workflow.created_at.tzinfo is UTC
    assert stored_workflow.updated_at.tzinfo is UTC
    assert stored_task.created_at.tzinfo is UTC
    assert stored_task.updated_at.tzinfo is UTC
    assert stored_task.lease_lock.tzinfo is UTC
    assert stored_task.next_retry_at.tzinfo is UTC
    assert stored_approval.created_at.tzinfo is UTC


def test_legacy_offset_free_rows_are_read_as_aware_utc(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    repository = SQLiteRepository(db_path)
    workflow = WorkflowPlan(
        workflow_id="workflow-utc",
        title="UTC Workflow",
        created_by="test",
    )
    task = make_task()
    approval = ApprovalRequest(
        id="approval-utc",
        task_id=task.id,
        requested_by="test",
    )
    repository.create_workflow(workflow)
    repository.create_task(task)
    repository.create_approval_request(approval)
    repository.close()

    legacy = "2025-12-31T23:59:58.123456"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE workflows SET created_at = ?, updated_at = ? WHERE workflow_id = ?",
        (legacy, legacy, workflow.workflow_id),
    )
    connection.execute(
        "UPDATE tasks SET created_at = ?, updated_at = ?, lease_lock = ?, next_retry_at = ? WHERE id = ?",
        (legacy, legacy, legacy, legacy, task.id),
    )
    connection.execute(
        "UPDATE approval_requests SET created_at = ?, decided_at = ? WHERE id = ?",
        (legacy, legacy, approval.id),
    )
    connection.commit()
    connection.close()

    reopened = SQLiteRepository(db_path)
    stored_workflow = reopened.get_workflow(workflow.workflow_id)
    stored_task = reopened.get_task(task.id)
    stored_approval = reopened.get_approval_request(task.id)
    expected = datetime(2025, 12, 31, 23, 59, 58, 123456, tzinfo=UTC)

    assert stored_workflow.created_at == expected
    assert stored_workflow.updated_at == expected
    assert stored_task.created_at == expected
    assert stored_task.updated_at == expected
    assert stored_task.lease_lock == expected
    assert stored_task.next_retry_at == expected
    assert stored_approval.created_at == expected
    assert stored_approval.decided_at == expected


def test_retry_and_lease_comparisons_accept_legacy_naive_values():
    task = make_task()
    task.next_retry_at = datetime(2026, 1, 1, 12, 0, 0)
    task.lease_lock = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=10)

    assert RetryManager.is_due(task, now=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)) is True
    assert RetryManager.is_due(task, now=datetime(2026, 1, 1, 11, 59, 59)) is False
    assert task.has_active_lease(timeout_seconds=1) is False


def test_audit_timestamps_preserve_format_and_ordering():
    logger = AuditLogger()
    task = make_task()
    task.schedule_retry(delay_seconds=5)

    logger.log_task_created(task)
    logger.log_retry_scheduled(task, delay_seconds=5)
    events = logger.get_events(task_id=task.id)

    assert len(events) == 2
    assert events[0].timestamp <= events[1].timestamp
    assert all("+00:00" not in event.timestamp and not event.timestamp.endswith("Z") for event in events)
    assert events[1].details["next_retry_at"] == utc_storage_string(task.next_retry_at)
    assert parse_utc_storage(events[0].timestamp).tzinfo is UTC
