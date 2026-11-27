"""Durable CLI audit history and immutable workflow attribution."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.models import Task, WorkflowPlan
from workflow_scheduler.repository import SQLiteRepository


def _task(workflow_id="audit-workflow", task_id="initialize"):
    return Task(
        id=task_id,
        workflow_id=workflow_id,
        type="test",
        owner="system",
        action="test_action",
        idempotency_key=f"audit-{task_id}",
    )


def _db_rows(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()


def _cli(db, *args):
    # The source-tree tests expose the same scheduler and contract packages as
    # an installation; each invocation is a separate real Python process.
    repo = Path(__file__).resolve().parents[3]
    source = repo / "08_Tooling/workflow-scheduler/src"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(map(str, (repo, repo / "src", source))),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "workflow_scheduler.cli", *map(str, args), "--db", str(db)],
        capture_output=True, text=True, timeout=20, env=env, cwd=db.parent,
    )
    return proc.returncode, json.loads(proc.stdout)


def test_audit_cli_reopens_evidence_without_reexecution_or_duplicate_writes(tmp_path):
    db = tmp_path / "audit.db"
    plan = tmp_path / "plan.json"
    workflow_id = "audit-workflow"
    plan.write_text(json.dumps({
        "workflow_id": workflow_id,
        "title": "Audit persistence fixture",
        "mode": "Draft",
        "tasks": [
            {"id": "initialize", "type": "test", "owner": "system",
             "action": "test_action", "idempotency_key": "audit-a"},
            {"id": "process", "type": "test", "owner": "system",
             "action": "test_action", "idempotency_key": "audit-b", "depends_on": ["initialize"]},
        ],
    }))
    assert _cli(db, "create", plan)[0] == 0
    code, result = _cli(db, "run", workflow_id)
    assert (code, result["completed"]) == (0, 2)
    code, result = _cli(db, "status", workflow_id)
    assert (code, result["workflow_status"]) == (0, "completed")

    rows = _db_rows(db)
    assert len(rows) == 7
    code, result = _cli(db, "audit", "--workflow-id", workflow_id)
    assert (code, result["event_count"]) == (0, 7)
    assert [e["event_type"] for e in result["events"]] == [
        "workflow_created", "workflow_started",
        "governance_check_passed", "task_completed",
        "governance_check_passed", "task_completed", "workflow_completed",
    ]
    assert all(e["workflow_id"] == workflow_id for e in result["events"])
    completed = [e for e in result["events"] if e["event_type"] == "task_completed"]
    assert [e["task_id"] for e in completed] == ["initialize", "process"]
    assert all(e["status_before"] == "running" and e["status_after"] == "completed" for e in completed)
    assert all(isinstance(e["details"]["result"], dict) for e in completed)
    assert all(e["timestamp"] for e in result["events"])
    assert _cli(db, "audit", "--workflow-id", workflow_id) == (0, result)

    code, task_view = _cli(db, "audit", "--task-id", "process")
    assert (code, task_view["event_count"]) == (0, 2)
    assert all(e["task_id"] == "process" for e in task_view["events"])
    assert _cli(db, "audit", "--workflow-id", workflow_id, "--task-id", "process") == (0, task_view)
    code, mismatch = _cli(db, "audit", "--workflow-id", "other", "--task-id", "process")
    assert (code, mismatch["status"], mismatch["events"]) == (0, "pass", [])

    code, terminal = _cli(db, "run", workflow_id)
    assert (code, terminal["blockers"]) == (1, ["workflow_terminal"])
    assert _db_rows(db) == rows


def test_legacy_rows_reopen_without_rewriting_history(tmp_path):
    db = tmp_path / "legacy.db"
    writer = SQLiteRepository(str(db))
    original = {
        "timestamp": "2026-11-26T11:00:00+00:00",
        "event_type": "task_completed",
        "task_id": "old",
        "workflow_id": None,
        "status_before": "running",
        "status_after": "completed",
        "details": {"result": {"answer": 3}},
    }
    writer.log_event("task_completed", task_id="old", details=original)
    writer.log_event("legacy_raw", workflow_id="audit-workflow", details={"count": 4})
    writer.close()
    before = _db_rows(db)
    reader = SQLiteRepository(str(db))
    try:
        log = AuditLogger(reader)
        events = log.get_events()
        assert [e.event_type for e in events] == ["task_completed", "legacy_raw"]
        assert events[0].to_dict() == original
        assert events[1].details == {"count": 4}
        assert events[1].status_after is None
        assert log.get_events(task_id="old")[0].workflow_id is None
        assert [e.event_type for e in log.get_events(workflow_id="audit-workflow")] == ["legacy_raw"]
        assert _db_rows(db) == before
    finally:
        reader.close()


def test_workflow_attribution_uses_task_owner_and_rejects_conflicts(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "identity.db"))
    workflow = WorkflowPlan(workflow_id="audit-workflow", title="QA", created_by="test")
    other = WorkflowPlan(workflow_id="other", title="QA", created_by="test")
    repo.create_workflow(workflow)
    repo.create_workflow(other)
    task = _task()
    repo.create_task(task)
    try:
        logger = AuditLogger(repo)
        logger.log_task_completed(task)
        assert [e.workflow_id for e in logger.get_events(workflow_id=workflow.workflow_id)] == [workflow.workflow_id]
        with pytest.raises(ValueError):
            logger._log("conflicting_workflow", task=task, workflow=other)
        with pytest.raises(ValueError):
            logger.log_task_completed(replace(task, workflow_id=""))
        with pytest.raises(ValueError):
            logger.log_task_completed(replace(task, workflow_id=other.workflow_id))
        assert len(repo.get_audit_log()) == 1
    finally:
        repo.close()


def test_failed_persistence_never_appears_in_logger_cache(tmp_path, monkeypatch):
    repo = SQLiteRepository(str(tmp_path / "failed.db"))
    logger = AuditLogger(repo)
    task = _task()
    calls = []
    def fail(**event):
        calls.append(event)
        raise OSError("injected local persistence failure")
    try:
        monkeypatch.setattr(repo, "log_event", fail)
        with pytest.raises(OSError, match="injected"):
            logger.log_task_completed(task)
        assert logger.events == []
        assert logger.get_events() == []
        assert len(calls) == 1
    finally:
        repo.close()


def test_cli_reports_read_failure_separately_from_empty_history(tmp_path):
    db = tmp_path / "corrupt.db"
    repo = SQLiteRepository(str(db))
    repo.close()
    code, empty = _cli(db, "audit")
    assert (code, empty["status"], empty["events"]) == (0, "pass", [])
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE audit_log")
        conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY)")
    code, broken = _cli(db, "audit")
    assert (code, broken["status"], broken["checks_failed"]) == (1, "fail", ["audit_log_read_failed"])
    assert "events" not in broken


def test_concurrent_reads_track_only_committed_distinct_events(tmp_path):
    db = tmp_path / "shared.db"
    repo = SQLiteRepository(str(db))
    reader = SQLiteRepository(str(db))
    logger = AuditLogger(repo)
    fresh = AuditLogger(reader)
    def write_and_read(i):
        task = _task(task_id=f"task-{i}")
        logger.log_task_created(task)
        ids = [e.task_id for e in fresh.get_events(workflow_id=task.workflow_id)]
        assert len(ids) == len(set(ids))
        assert task.id in ids

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write_and_read, range(20)))
        events = fresh.get_events(workflow_id="audit-workflow")
        assert len(events) == 20
        assert {e.task_id for e in events} == {f"task-{i}" for i in range(20)}
        assert len(_db_rows(db)) == 20
    finally:
        reader.close()
        repo.close()


@pytest.mark.parametrize("defect", ["missing-status", "conflicting-envelope", "invalid-json"])
def test_cli_does_not_present_corrupt_persisted_events_as_legacy_details(tmp_path, defect):
    db = tmp_path / "envelope.db"
    repo = SQLiteRepository(str(db))
    payload = {
        "timestamp": "2026-11-26T11:00:00+00:00",
        "event_type": "task_completed",
        "task_id": "old",
        "workflow_id": None,
        "status_before": "running",
        "status_after": "completed",
        "details": {},
    }
    if defect == "missing-status":
        del payload["status_after"]
    elif defect == "conflicting-envelope":
        payload["task_id"] = "other"
    repo.log_event("task_completed", task_id="old", details=payload)
    repo.close()
    if defect == "invalid-json":
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE audit_log SET details = ?", ("{",))
    before = _db_rows(db)
    code, result = _cli(db, "audit")
    assert (code, result["checks_failed"]) == (1, ["audit_log_read_failed"])
    assert "events" not in result
    assert _db_rows(db) == before
