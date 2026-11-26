"""S8 adapter-deferral contract controls; run this file without sibling QA tests."""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

import s8_deferral_support as support
from workflow_scheduler.models import ApprovalDecision, ApprovalRequest, TaskStatus, WorkflowStatus
from workflow_scheduler.repository import SQLiteRepository


def expect_blockers(result, *expected):
    """The documented blocker set for this scenario; duplicate/order not semantic."""
    assert set(result["blockers"]) == set(expected)


def assert_held_without_dispatch(repo, task_id="t0"):
    """Read only; this assertion never attempts to take an execution claim."""
    task = repo.get_task(task_id)
    assert task.status is TaskStatus.RUNNING and task.lease_lock is not None
    assert repo.get_workflow("wf").status is WorkflowStatus.RUNNING
    with closing(sqlite3.connect(repo.db_path)) as conn:
        row = conn.execute("SELECT execution_claim_token FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row and row[0]


def claim_observation(path):
    """Return the exact SQLite ownership pair without altering it."""
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            "SELECT execution_claim_token, lease_lock FROM tasks WHERE id = 't0'"
        ).fetchone()


def test_adapter_deferral_continues_once_after_approval(tmp_path):
    db = support.make_plan(tmp_path, dependent=True)
    deferrer = support.RecordingAdapter(support.DEFER)
    with support.open_cli(db, deferrer) as cli:
        wait = cli.run_workflow("wf")
        expect_blockers(wait, "tasks_awaiting_approval")
        assert deferrer.calls == ["t0"]
        assert cli.repository.get_workflow("wf").dependencies["t1"] == ["t0"]

    worker = support.RecordingAdapter(support.SUCCESS)
    with support.open_cli(db, worker) as reader:
        request = reader.repository.get_approval_request("t0")
        assert request.decision is ApprovalDecision.PENDING
        assert request.reason == support.DEFER["approval_reason"]
        assert reader.repository.workflow_approval_waits("wf") == ({"t0"}, {"t0"})
        no_dispatch = reader.run_workflow("wf")
        expect_blockers(no_dispatch, "tasks_awaiting_approval")
        assert not worker.calls

        approved = reader.approve("t0", "reviewer")
        assert approved["continuation"]["status"] == "pass"
        assert worker.calls == ["t0", "t1"]
        assert reader.repository.get_workflow("wf").status is WorkflowStatus.COMPLETED

        repeat = reader.approve("t0", "reviewer")
        expect_blockers(repeat, "task_not_awaiting_approval")
        assert "continuation" not in repeat
        terminal = reader.recover_pending_continuations("wf")
        expect_blockers(terminal, "workflow_not_running")
        assert terminal.get("still_pending_task_ids", []) == []
        assert worker.calls == ["t0", "t1"]


def run_crash(db, receipt, mode):
    root = Path(__file__).resolve().parents[3]
    package = root / "08_Tooling/workflow-scheduler/src"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(str, (root, root / "src", package)))}
    return subprocess.run([sys.executable, "-B", support.__file__, str(db), str(receipt), mode],
                          cwd=root, env=env, capture_output=True, text=True, timeout=30, check=False)


def test_crash_after_adapter_wait_commit_preserves_exact_pending_request(tmp_path):
    db = support.make_plan(tmp_path)
    receipt = tmp_path / "attempted-request.json"
    child = run_crash(db, receipt, "after")
    assert child.returncode == support.COMMITTED, child.stderr
    expected = json.loads(receipt.read_text(encoding="utf-8"))
    assert expected["id"] and expected["created_at"]
    assert expected["task_id"] == "t0" and expected["requested_by"] == "test-owner"
    assert expected["decision"] == "pending" and expected["reason"] == support.DEFER["approval_reason"]
    assert expected["approver"] is None and expected["decided_at"] is None
    worker = support.RecordingAdapter(support.SUCCESS)
    with support.open_cli(db, worker) as cli:
        task = cli.repository.get_task("t0")
        pending = cli.repository.get_approval_request("t0")
        assert pending is not None and support.request_fields(pending) == expected
        assert task.status is TaskStatus.APPROVAL_PENDING and task.approval_required
        assert task.lease_lock is None
        assert cli.repository.workflow_approval_waits("wf") == ({"t0"}, {"t0"})
        waiting = cli.recover_pending_continuations("wf")
        expect_blockers(waiting)
        assert set(waiting["still_pending_task_ids"]) == {"t0"}
        assert waiting["recovered_task_ids"] == [] and not worker.calls
        approval = cli.approve("t0", "reviewer")
        assert approval["continuation"]["status"] == "pass" and worker.calls == ["t0"]


@pytest.mark.parametrize("mode,exit_code", [("before", support.BEFORE), ("truthy", support.NONBOOL)])
def test_precommit_or_nonboolean_crash_cannot_claim_commit(tmp_path, mode, exit_code):
    db = support.make_plan(tmp_path)
    receipt = tmp_path / "attempted-request.json"
    child = run_crash(db, receipt, mode)
    assert child.returncode == exit_code, child.stderr
    assert json.loads(receipt.read_text(encoding="utf-8"))["decision"] == "pending"
    with support.open_cli(db) as cli:
        assert cli.repository.get_approval_request("t0") is None
        assert_held_without_dispatch(cli.repository)
        recovered = cli.recover_pending_continuations("wf")
        expect_blockers(recovered, "unresolved_execution_claim")
        assert recovered["unresolved_claim_task_ids"] == ["t0"]
        assert recovered["recovered_task_ids"] == recovered["still_pending_task_ids"] == []


def test_request_persistence_error_rolls_back_deferral_and_retains_claim(tmp_path):
    db = support.make_plan(tmp_path)
    # SQLite executes the row insert then rejects its statement inside the same
    # guarded transaction as the task transition and claim release.
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("""CREATE TRIGGER reject_pending AFTER INSERT ON approval_requests
                        BEGIN SELECT RAISE(ABORT, 's8 injected insert failure'); END""")
        conn.commit()
    observations = []

    class ObservingAdapter(support.RecordingAdapter):
        def execute(self, task):
            observations.append(claim_observation(db))
            return super().execute(task)

    adapter = ObservingAdapter(support.DEFER)
    with support.open_cli(db, adapter) as cli:
        result = cli.run_workflow("wf")
        assert result["status"] == "blocked"
        expect_blockers(result, "tasks_executing_elsewhere")
        assert adapter.calls == ["t0"] and len(observations) == 1
        assert cli.repository.get_approval_request("t0") is None
        # Check the writer before close can implicitly roll back and mask a bug.
        assert_held_without_dispatch(cli.repository)
        assert claim_observation(db) == observations[0]
    with support.open_cli(db) as other:
        assert other.repository.get_approval_request("t0") is None
        assert other.repository.workflow_approval_waits("wf") == (set(), set())
        assert_held_without_dispatch(other.repository)
        # Mutating challenge is a labeled action, not an assertion expression.
        denied_claim = other.repository.try_claim_execution("t0")
        assert denied_claim is None


def test_second_adapter_deferral_cannot_be_reapproved_by_a_delayed_task_id(tmp_path):
    db = support.make_plan(tmp_path)
    adapter = support.RecordingAdapter(support.DEFER)
    with support.open_cli(db, adapter) as cli:
        wait = cli.run_workflow("wf")
        expect_blockers(wait, "tasks_awaiting_approval")
        first = cli.repository.get_approval_request("t0")
        approved = cli.approve("t0", "reviewer")
        failed = approved["continuation"]
        assert failed["status"] == "fail"
        expect_blockers(failed, "adapter_approval_repeated")
        current = cli.repository.get_approval_request("t0")
        assert current.id == first.id and current.decision is ApprovalDecision.APPROVED
        assert cli.repository.get_task("t0").status is TaskStatus.GOVERNANCE_BLOCKED
        assert cli.repository.get_workflow("wf").status is WorkflowStatus.FAILED
        logs = cli.repository.get_audit_log(task_id="t0")
        details = [json.loads(row["details"])["details"] for row in logs
                   if row["event_type"] == "governance_blocked"]
        assert any("adapter_approval_repeated" in item["blockers"] for item in details)
        with closing(sqlite3.connect(db)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM approval_requests WHERE task_id = 't0'").fetchone()
        assert count == (1,)

        replay = cli.approve("t0", "delayed reviewer")
        expect_blockers(replay, "task_not_awaiting_approval")
        rerun = cli.run_workflow("wf")
        assert rerun["status"] == "blocked"
        recovery = cli.recover_pending_continuations("wf")
        expect_blockers(recovery, "workflow_not_running")
        assert not recovery.get("still_pending_task_ids", [])
        assert adapter.calls == ["t0", "t0"]  # no third attempt
        assert support.request_fields(cli.repository.get_approval_request("t0")) == support.request_fields(current)


@pytest.mark.parametrize("same_id", [False, True], ids=["different-id", "same-id"])
def test_racing_request_rolls_back_claimed_deferral(tmp_path, same_id):
    db = support.make_plan(tmp_path)
    inserted = []
    adapter = support.RecordingAdapter(support.DEFER)
    with support.open_cli(db) as peer:
        class RacingRepository(SQLiteRepository):
            def update_claimed_task(self, task, token, *, approval_request=None):
                if approval_request is not None:
                    request = ApprovalRequest(
                        id=approval_request.id if same_id else "racing-request",
                        task_id=task.id, requested_by="peer", reason="competing unbound request",
                    )
                    peer.repository.create_approval_request(request)
                    inserted.append(support.request_fields(request))
                return super().update_claimed_task(task, token, approval_request=approval_request)

        with support.open_cli(db, adapter, repository_type=RacingRepository) as cli:
            result = cli.run_workflow("wf")
            assert result["status"] == "blocked"
            expect_blockers(result, "tasks_executing_elsewhere")
            assert adapter.calls == ["t0"] and len(inserted) == 1
            assert_held_without_dispatch(peer.repository)
            visible = peer.repository.get_approval_request("t0")
            assert visible is not None and support.request_fields(visible) == inserted[0]
            # Visible durable request, but not an authorized workflow wait.
            # Only the atomic claimed transition may bind that eligibility.
            assert peer.repository.workflow_approval_waits("wf") == (set(), set())
            blocked = peer.approve("t0", "reviewer")
            expect_blockers(blocked, "task_not_awaiting_approval")
            assert "continuation" not in blocked
            assert support.request_fields(peer.repository.get_approval_request("t0")) == inserted[0]
            recovery = peer.recover_pending_continuations("wf")
            expect_blockers(recovery, "unresolved_execution_claim")
            assert recovery["unresolved_claim_task_ids"] == ["t0"]
            assert recovery["recovered_task_ids"] == recovery["still_pending_task_ids"] == []
            assert claim_observation(db)[0]


@pytest.mark.parametrize("approve_while_paused", [False, True])
def test_adapter_wait_does_not_resume_paused_workflow(tmp_path, approve_while_paused):
    db = support.make_plan(tmp_path)
    with support.open_cli(db, support.RecordingAdapter(support.DEFER)) as cli:
        waiting = cli.run_workflow("wf")
        expect_blockers(waiting, "tasks_awaiting_approval")
        first = cli.repository.get_approval_request("t0")
        paused = cli.pause_workflow("wf")
        assert paused["status"] == "pass"

    worker = support.RecordingAdapter(support.SUCCESS)
    with support.open_cli(db, worker) as cli:
        before = cli.repository.get_approval_request("t0")
        assert support.request_fields(before) == support.request_fields(first)
        if approve_while_paused:
            approved = cli.approve("t0", "reviewer")
            assert approved["status"] == "pass" and "continuation" not in approved
        blocked = cli.recover_pending_continuations("wf")
        expect_blockers(blocked, "workflow_not_running")
        assert not blocked.get("still_pending_task_ids", []) and not worker.calls
        assert cli.repository.get_workflow("wf").status is WorkflowStatus.PAUSED
        current = cli.repository.get_approval_request("t0")
        assert current.id == first.id
        assert current.decision is (ApprovalDecision.APPROVED if approve_while_paused else ApprovalDecision.PENDING)

        resumed = cli.resume_workflow("wf")
        assert resumed["status"] == "pass"
        assert cli.repository.get_workflow("wf").status is WorkflowStatus.RUNNING
        recovered = cli.recover_pending_continuations("wf")
        expect_blockers(recovered)
        assert set(recovered["still_pending_task_ids"]) == (set() if approve_while_paused else {"t0"})
        if not approve_while_paused:
            assert recovered["recovered_task_ids"] == [] and not worker.calls
            approved = cli.approve("t0", "reviewer")
            assert approved["continuation"]["status"] == "pass"
        else:
            assert recovered["completed_task_ids"] == ["t0"]
        assert worker.calls == ["t0"]
        assert cli.repository.get_workflow("wf").status is WorkflowStatus.COMPLETED


def test_two_cli_contexts_close_every_opened_handle(tmp_path, monkeypatch):
    db = support.make_plan(tmp_path)
    opened = []
    real_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        close_count = 0

        def close(self):
            self.close_count += 1
            super().close()

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs, factory=TrackedConnection)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    with support.open_cli(db) as first, support.open_cli(db) as second:
        assert first.repository.get_workflow("wf").workflow_id == second.repository.get_workflow("wf").workflow_id
        assert len(opened) == 2
    assert all(c.close_count == 1 for c in opened)
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
