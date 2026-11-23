"""S8 QA regressions: real-process crash windows, cross-process migration, lost completion."""
import multiprocessing as mp
import os
import sqlite3
import sys

import pytest
import yaml

from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import TaskStatus, WorkflowStatus
from workflow_scheduler.repository import SQLiteRepository

posix_only = pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")


def _plan(tmp_path, ids=("t0",)):
    spec = {"workflow_id": "wf", "title": "qa", "created_by": "test", "mode": "Draft",
            "tasks": [{"id": i, "type": "test", "owner": "system", "action": "read:fixture",
                       "idempotency_key": i} for i in ids]}
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(spec))
    db = str(tmp_path / "s.sqlite")
    assert WorkflowSchedulerCLI(db_path=db).create_workflow(str(path))["status"] == "pass"
    return db


class _Adapter:
    def __init__(self, result):
        self.result, self.execution_log = result, []

    def execute(self, task):
        self.execution_log.append(task.id)
        return dict(self.result)


def _die_after_settled_persist(db, result):
    """Child process: persist a settled result, then die before any later commit."""
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child
        cli = WorkflowSchedulerCLI(db_path=db)
        cli.executor.adapter = _Adapter(result)
        original = cli.repository.update_claimed_task

        def persist_then_die(task, token, **kwargs):
            if original(task, token, **kwargs):
                os._exit(137)
            os._exit(3)

        cli.repository.update_claimed_task = persist_then_die
        cli.run_workflow("wf")
        os._exit(4)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 137


@posix_only
def test_crash_after_retry_persist_does_not_wedge_task(tmp_path):
    db = _plan(tmp_path)
    _die_after_settled_persist(db, {"success": False, "is_transient": True, "error": "x"})
    cli = WorkflowSchedulerCLI(db_path=db)
    task = cli.repository.get_task("t0")
    assert task.status is TaskStatus.RETRY_SCHEDULED and task.retry_count == 1
    assert task.lease_lock is None
    conn = cli.repository._get_connection()
    conn.execute("UPDATE tasks SET next_retry_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    cli.executor.adapter = _Adapter({"success": True, "output": {}})
    result = cli.run_workflow("wf")
    assert result["status"] == "pass", result
    assert cli.executor.adapter.execution_log == ["t0"]


@posix_only
def test_crash_after_approval_required_persist_keeps_task_approvable(tmp_path):
    db = _plan(tmp_path)
    _die_after_settled_persist(
        db, {"status": "approval-required", "message": "m", "approval_reason": "human"})
    cli = WorkflowSchedulerCLI(db_path=db)
    assert cli.repository.get_task("t0").status is TaskStatus.APPROVAL_PENDING
    assert cli.approve("t0", "reviewer")["status"] == "pass"


@posix_only
def test_crash_mid_execution_remains_fenced(tmp_path):
    """Negative control: an unsettled claim (side effect uncertain) is still never stolen."""
    db = _plan(tmp_path)
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child
        cli = WorkflowSchedulerCLI(db_path=db)
        cli.executor.adapter.execute = lambda task: os._exit(137)
        cli.run_workflow("wf")
        os._exit(4)
    os.waitpid(pid, 0)
    cli = WorkflowSchedulerCLI(db_path=db)
    cli.executor.lease_timeout_seconds = 0
    assert cli.run_workflow("wf")["blockers"] == ["tasks_executing_elsewhere"]
    assert cli.cancel_task("t0", "x")["status"] == "blocked"
    assert cli.repository.get_task("t0").status is TaskStatus.RUNNING


_MAIN_SCHEMA_TASKS = """CREATE TABLE tasks (id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
 type TEXT NOT NULL, owner TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL,
 status TEXT NOT NULL, mode TEXT NOT NULL, priority INTEGER NOT NULL, approval_required BOOLEAN NOT NULL,
 depends_on TEXT NOT NULL, payload TEXT NOT NULL, lease_lock TEXT, production_ready BOOLEAN NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0,
 next_retry_at TEXT, max_retries INTEGER NOT NULL DEFAULT 3, paused_from_status TEXT, batch_id TEXT)"""


def _open(db, barrier, queue):  # pragma: no cover - child
    try:
        barrier.wait(30)
        SQLiteRepository(db)
        queue.put("ok")
    except BaseException as exc:  # noqa: BLE001
        queue.put(f"{type(exc).__name__}: {exc}")


@posix_only
def test_concurrent_processes_upgrade_existing_schema_without_error(tmp_path):
    ctx = mp.get_context("fork")
    outcomes = []
    for trial in range(5):
        db = str(tmp_path / f"main-{trial}.sqlite")
        conn = sqlite3.connect(db)
        conn.execute(_MAIN_SCHEMA_TASKS)
        conn.commit()
        conn.close()
        barrier, queue = ctx.Barrier(8), ctx.Queue()
        procs = [ctx.Process(target=_open, args=(db, barrier, queue)) for _ in range(8)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
        outcomes += [queue.get() for _ in procs]
    assert set(outcomes) == {"ok"}, sorted(set(outcomes))


def test_runner_settles_work_finished_by_peer_after_observation(tmp_path):
    """Two runners each observe the other's task in flight; the later one must finish the workflow."""
    db = _plan(tmp_path, ids=("mine", "peer"))
    runner, peer = WorkflowSchedulerCLI(db_path=db), WorkflowSchedulerCLI(db_path=db)
    plan = peer.repository.get_workflow("wf")
    plan.mark_running()
    assert peer.repository.update_workflow(plan)
    token = peer.repository.try_claim_execution("peer")  # peer is mid-execution
    assert token
    original = runner.executor.execute_many

    def run_then_peer_finishes(tasks, *args, **kwargs):
        results = original(tasks, *args, **kwargs)
        done = peer.repository.get_task("peer")
        done.mark_completed()
        assert peer.repository.update_claimed_task(done, token)
        peer.repository.release_execution_claim("peer", token)
        return results

    runner.executor.execute_many = run_then_peer_finishes
    result = runner.run_workflow("wf")
    assert runner.repository.get_workflow("wf").status is WorkflowStatus.COMPLETED, result
    assert result["status"] == "pass"


def test_peer_metadata_write_does_not_strand_completion(tmp_path):
    """A peer's metadata-only workflow write (awaiting bookkeeping) must not block the finisher."""
    db = _plan(tmp_path)
    runner, peer = WorkflowSchedulerCLI(db_path=db), WorkflowSchedulerCLI(db_path=db)
    original = runner.executor.execute_many

    def execute_then_peer_bookkeeping(tasks, *args, **kwargs):
        results = original(tasks, *args, **kwargs)
        plan = peer.repository.get_workflow("wf")
        plan.metadata["tasks_awaiting_approval"] = []
        assert peer.repository.update_workflow(plan)
        return results

    runner.executor.execute_many = execute_then_peer_bookkeeping
    result = runner.run_workflow("wf")
    assert runner.repository.get_workflow("wf").status is WorkflowStatus.COMPLETED, result
    assert result["status"] == "pass"


@pytest.mark.parametrize("stop", ["pause", "cancel"])
def test_peer_stop_still_wins_over_finisher(tmp_path, stop):
    """Negative control: retrying the verdict never overrides a real pause/cancel."""
    db = _plan(tmp_path)
    runner, peer = WorkflowSchedulerCLI(db_path=db), WorkflowSchedulerCLI(db_path=db)
    original = runner.executor.execute_many

    def execute_then_stop(tasks, *args, **kwargs):
        results = original(tasks, *args, **kwargs)
        response = peer.pause_workflow("wf") if stop == "pause" else peer.cancel_workflow("wf", "x")
        assert response["status"] == "pass"
        return results

    runner.executor.execute_many = execute_then_stop
    result = runner.run_workflow("wf")
    expected = WorkflowStatus.PAUSED if stop == "pause" else WorkflowStatus.CANCELLED
    assert runner.repository.get_workflow("wf").status is expected
    assert result["status"] == "blocked"


def test_recovery_reconciles_already_completed_task_before_approval_scope_check(tmp_path, monkeypatch):
    # Start a real request-bound wait. The peer wins the task, but not the
    # workflow relabel, between the recovery runner's initial and second reads.
    from test_transition_controls import _create
    from workflow_scheduler.models import ApprovalDecision

    runner, peer = _create(tmp_path, approval=True)
    assert runner.run_workflow("wf")["status"] == "blocked"
    assert peer.repository.try_decide_pending_approval("step", "reviewer", ApprovalDecision.APPROVED)
    original = runner._workflow_approval_waits
    won = False

    def settle_before_second_observation(plan):
        nonlocal won
        if not won:
            token = peer.repository.try_claim_execution("step")
            assert token
            task = peer.repository.get_task("step")
            task.mark_completed()
            assert peer.repository.update_claimed_task(task, token)
            peer.repository.release_execution_claim(task.id, token)
            won = True
        return original(plan)

    monkeypatch.setattr(runner, "_workflow_approval_waits", settle_before_second_observation)
    result = runner.run_workflow("wf", _approval_continuation=True)
    assert won and result["status"] == "pass", result
    assert runner.repository.get_workflow("wf").status is WorkflowStatus.COMPLETED
    assert not runner.adapter.execution_log


def test_completion_refuses_to_overwrite_peer_plan_update(tmp_path, monkeypatch):
    db = _plan(tmp_path)
    runner, peer = WorkflowSchedulerCLI(db_path=db), WorkflowSchedulerCLI(db_path=db)
    original = runner.executor.execute_many

    def execute_then_peer_updates_plan(tasks, *args, **kwargs):
        results = original(tasks, *args, **kwargs)
        current = peer.repository.get_workflow("wf")
        current.dependencies["new-scope"] = []
        assert peer.repository.update_workflow(current)
        return results

    monkeypatch.setattr(runner.executor, "execute_many", execute_then_peer_updates_plan)
    result = runner.run_workflow("wf")
    current = peer.repository.get_workflow("wf")
    assert result["status"] == "blocked", result
    assert current.status is WorkflowStatus.RUNNING
    assert "new-scope" in current.dependencies


def test_completion_checks_for_unsettled_members_in_same_update(tmp_path, monkeypatch):
    from workflow_scheduler.models import Task

    db = _plan(tmp_path)
    runner, peer = WorkflowSchedulerCLI(db_path=db), WorkflowSchedulerCLI(db_path=db)
    original = runner.repository.update_workflow
    created = False

    def insert_task_before_completion(plan):
        nonlocal created
        if plan.status == WorkflowStatus.COMPLETED and not created:
            peer.repository.create_task(Task(
                id="later", workflow_id="wf", type="test", owner="system",
                action="read:fixture", idempotency_key="later",
            ))
            created = True
        return original(plan)

    monkeypatch.setattr(runner.repository, "update_workflow", insert_task_before_completion)
    result = runner.run_workflow("wf")
    assert created and result["status"] == "blocked", result
    assert peer.repository.get_workflow("wf").status is WorkflowStatus.RUNNING
    assert peer.repository.get_task("later").status is TaskStatus.DRAFT


def test_schema_transaction_covers_first_legacy_table_inspection(tmp_path):
    trace = []

    class TraceRepository(SQLiteRepository):
        def _get_connection(self):
            connection = super()._get_connection()
            connection.set_trace_callback(trace.append)
            return connection

    db = str(tmp_path / "legacy.sqlite")
    with sqlite3.connect(db) as legacy:
        legacy.execute(_MAIN_SCHEMA_TASKS)
    TraceRepository(db).close()
    ordered = [statement.lower() for statement in trace]
    begin = next(i for i, q in enumerate(ordered) if q.startswith("begin immediate"))
    first_task_check = next(i for i, q in enumerate(ordered) if "pragma table_info(tasks)" in q)
    assert begin < first_task_check
