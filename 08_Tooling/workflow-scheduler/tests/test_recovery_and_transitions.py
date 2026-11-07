"""Repair A (durable post-approval recovery) and Repair B (protected
state-transition integrity) for the automatic-continuation candidate.

These tests use only existing scheduler primitives: the approval
decision transaction, workflow metadata, the single-winner execution
claim, and conditional repository updates. No new service or scheduler
is introduced by the code under test.
"""

from concurrent.futures import ThreadPoolExecutor

import yaml

from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import (
    ApprovalDecision,
    Task,
    TaskStatus,
    WorkflowStatus,
)
from workflow_scheduler.repository import SQLiteRepository


def prepare(tmp_path, two_approvals=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = str(tmp_path / "recovery.sqlite")
    cli = WorkflowSchedulerCLI(db_path=db)
    tasks = [{
        "id": "first", "type": "test", "owner": "system",
        "action": "read:first", "idempotency_key": "first",
        "approval_required": True,
    }]
    tasks.append({
        "id": "second", "type": "test", "owner": "system",
        "action": "read:second", "idempotency_key": "second",
        "depends_on": ["first"],
        "approval_required": two_approvals,
    })
    plan = {
        "workflow_id": "recovery", "title": "Recovery",
        "created_by": "test", "mode": "Draft", "tasks": tasks,
    }
    path = tmp_path / "workflow.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(plan))
    assert cli.create_workflow(str(path))["status"] == "pass"
    assert cli.run_workflow("recovery")["status"] == "blocked"
    return cli, db


def test_approval_committed_before_dispatch_recovers_without_second_approval(tmp_path):
    # Simulate a crash between the approval transaction and dispatch:
    # commit the decision directly, never call approve(), then recover.
    cli, _ = prepare(tmp_path)
    assert cli.repository.try_decide_pending_approval(
        "first", "owner", ApprovalDecision.APPROVED
    )
    assert cli.repository.get_task("first").status == TaskStatus.APPROVED
    assert len(cli.adapter.execution_log) == 0

    recovered = cli.recover_pending_continuations("recovery")
    assert recovered["status"] == "pass"
    assert recovered["recovered_task_ids"] == ["first"]
    assert len(cli.adapter.execution_log) == 2
    assert cli.repository.get_task("first").status == TaskStatus.COMPLETED
    assert cli.repository.get_task("second").status == TaskStatus.COMPLETED
    assert cli.repository.get_workflow("recovery").status.value == "completed"
    # Recovery is idempotent: nothing left to recover afterwards.
    again = cli.recover_pending_continuations("recovery")
    assert again["status"] == "blocked"  # workflow is now terminal, not running
    assert len(cli.adapter.execution_log) == 2


def test_recovery_does_not_dispatch_paused_workflow_then_resumes(tmp_path):
    cli, _ = prepare(tmp_path)
    assert cli.pause_workflow("recovery")["status"] == "pass"
    decision = cli.approve("first", approver="owner")
    assert decision["status"] == "pass"
    assert "continuation" not in decision
    assert len(cli.adapter.execution_log) == 0

    blocked = cli.recover_pending_continuations("recovery")
    assert blocked["status"] == "blocked"
    assert blocked["blockers"] == ["workflow_not_running"]
    assert len(cli.adapter.execution_log) == 0

    assert cli.resume_workflow("recovery")["status"] == "pass"
    recovered = cli.recover_pending_continuations("recovery")
    assert recovered["status"] == "pass"
    assert len(cli.adapter.execution_log) == 2


def test_interrupted_executor_with_unresolved_claim_is_not_stolen(tmp_path):
    # Simulate an executor that claimed a claimable task and then died:
    # the claim (token + lease) is durable, the adapter may or may not
    # have run, and a second executor must not steal or re-execute it.
    from workflow_scheduler.audit import AuditLogger
    from workflow_scheduler.execution import Executor
    from workflow_scheduler.adapters import NoopAdapter

    db = str(tmp_path / "crash.db")
    repo = SQLiteRepository(db)
    task = Task(id="crash-task", workflow_id="crash", type="test",
                owner="system", action="read:x", idempotency_key="crash-task")
    repo.create_task(task)
    assert repo.try_claim_execution("crash-task") is not None
    assert repo.try_claim_execution("crash-task") is None
    assert repo.get_task("crash-task").status == TaskStatus.RUNNING

    adapter = NoopAdapter()
    executor = Executor(adapter, repo, AuditLogger(repository=repo))
    result = executor.execute(repo.get_task("crash-task"))
    assert "lease_acquisition" in result.checks_failed
    assert len(adapter.execution_log) == 0
    assert repo.get_task("crash-task").status == TaskStatus.RUNNING
    assert repo.try_claim_execution("crash-task") is None


def test_two_concurrent_approvals_execute_only_once(tmp_path):
    cli, db = prepare(tmp_path)
    other = WorkflowSchedulerCLI(db_path=db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(cli.approve, "first", "owner-a")
        b = pool.submit(other.approve, "first", "owner-b")
        responses = [a.result(timeout=20), b.result(timeout=20)]
    assert sorted(x["status"] for x in responses) == ["blocked", "pass"]
    calls = len(cli.adapter.execution_log) + len(other.adapter.execution_log)
    assert calls == 2
    assert cli.repository.get_task("first").status == TaskStatus.COMPLETED


def test_two_independent_runners_do_not_duplicate_or_fail_workflow(tmp_path):
    # Approval-free workflow with two independent tasks, raced by two
    # separate CLI instances over the same database file.
    db = str(tmp_path / "runners.sqlite")
    cli = WorkflowSchedulerCLI(db_path=db)
    tasks = [
        {"id": "a", "type": "test", "owner": "system",
         "action": "read:a", "idempotency_key": "a"},
        {"id": "b", "type": "test", "owner": "system",
         "action": "read:b", "idempotency_key": "b"},
    ]
    plan = {"workflow_id": "runners", "title": "Runners",
            "created_by": "test", "mode": "Draft", "tasks": tasks}
    path = tmp_path / "runners.yaml"
    path.write_text(yaml.safe_dump(plan))
    assert cli.create_workflow(str(path))["status"] == "pass"
    other = WorkflowSchedulerCLI(db_path=db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(cli.run_workflow, "runners")
        b = pool.submit(other.run_workflow, "runners")
        responses = [a.result(timeout=20), b.result(timeout=20)]
    # Losing a claim must not terminally fail the workflow, and total
    # adapter executions must not exceed one per task.
    calls = len(cli.adapter.execution_log) + len(other.adapter.execution_log)
    assert calls == 2
    assert cli.repository.get_workflow("runners").status.value == "completed"
    assert not any(r["status"] == "fail" and "tasks_failed" in r.get("checks_failed", [])
                   for r in responses)


def test_stale_updates_cannot_reverse_protected_task_states(tmp_path):
    cli, _ = prepare(tmp_path)
    repo = cli.repository

    # COMPLETED: complete via approval, then try to requeue the snapshot.
    cli.approve("first", approver="owner")
    completed = repo.get_task("first")
    assert completed.status == TaskStatus.COMPLETED
    stale = repo.get_task("first")
    stale.status = TaskStatus.QUEUED
    assert repo.update_task(stale) is False
    assert repo.get_task("first").status == TaskStatus.COMPLETED

    # CANCELLED (via rejection) and PAUSED reversals.
    cli2, _ = prepare(tmp_path / "second")
    cli2.reject("first", approver="owner", reason="declined")
    assert cli2.repository.get_task("first").status == TaskStatus.CANCELLED
    stale = cli2.repository.get_task("first")
    stale.status = TaskStatus.QUEUED
    assert cli2.repository.update_task(stale) is False
    assert cli2.repository.get_task("first").status == TaskStatus.CANCELLED

    cli3, _ = prepare(tmp_path / "third")
    # Pause the approval-pending task is not allowed from approval
    # pending? Pause works from any non-terminal, non-paused status.
    assert cli3.pause_task("first")["status"] == "pass"
    assert cli3.repository.get_task("first").status == TaskStatus.PAUSED
    stale = cli3.repository.get_task("first")
    stale.status = TaskStatus.QUEUED
    assert cli3.repository.update_task(stale) is False
    assert cli3.repository.get_task("first").status == TaskStatus.PAUSED
    # Legitimate resume restores the recorded prior status.
    assert cli3.resume_task("first")["status"] == "pass"
    assert cli3.repository.get_task("first").status == TaskStatus.APPROVAL_PENDING


def test_stale_workflow_snapshot_cannot_reverse_workflow(tmp_path):
    cli, _ = prepare(tmp_path)
    cli.approve("first", approver="owner")
    workflow = cli.repository.get_workflow("recovery")
    assert workflow.status.value == "completed"
    workflow.status = WorkflowStatus.RUNNING
    assert cli.repository.update_workflow(workflow) is False
    assert cli.repository.get_workflow("recovery").status.value == "completed"


def test_retry_state_cannot_move_backwards(tmp_path):
    db = str(tmp_path / "retry.db")
    repo = SQLiteRepository(db)
    task = Task(id="retry", workflow_id="retry", type="test", owner="system",
                action="read:x", idempotency_key="retry")
    task.retry_count = 2
    repo.create_task(task)
    stale = repo.get_task("retry")
    stale.retry_count = 0
    assert repo.update_task(stale) is False
    assert repo.get_task("retry").retry_count == 2
    # Legitimate forward movement still works.
    fresh = repo.get_task("retry")
    fresh.retry_count = 3
    fresh.status = TaskStatus.RETRY_SCHEDULED
    assert repo.update_task(fresh) is True
    assert repo.get_task("retry").retry_count == 3


def test_legitimate_retry_resume_and_cancel_transitions(tmp_path):
    cli, _ = prepare(tmp_path)
    repo = cli.repository
    # Retry: an approval-pending task can be moved to retry_scheduled
    # and then queued again by a run.
    task = repo.get_task("first")
    task.status = TaskStatus.RETRY_SCHEDULED
    task.retry_count = 1
    assert repo.update_task(task) is True
    # Cancel: a non-terminal task can be cancelled, and the cancel sticks.
    assert cli.cancel_task("second", reason="no longer needed")["status"] == "pass"
    assert repo.get_task("second").status == TaskStatus.CANCELLED
    stale = repo.get_task("second")
    stale.status = TaskStatus.QUEUED
    assert repo.update_task(stale) is False


def test_cancel_workflow_does_not_claim_claimed_task_cancelled(tmp_path):
    # QA defect D1 reproduction: a claimed (in-flight) task must not
    # appear in cancelled_task_ids, and the response must not be a
    # pass claiming a full cancel.
    cli, db = prepare(tmp_path)
    repo = SQLiteRepository(db)
    assert repo.try_decide_pending_approval("first", "owner", ApprovalDecision.APPROVED)
    assert repo.try_claim_execution("first") is not None
    assert repo.get_task("first").status == TaskStatus.RUNNING
    response = cli.cancel_workflow("recovery", reason="stop")
    assert response["status"] == "blocked"
    assert "first" not in response["cancelled_task_ids"]
    assert response["refused_task_ids"] == ["first"]
    assert repo.get_task("first").status == TaskStatus.RUNNING
    # The workflow itself was cancelled; only the task claim was refused.
    assert repo.get_workflow("recovery").status.value == "cancelled"


def test_cancel_and_pause_with_expired_lease_but_live_claim_are_refused(tmp_path):
    # Expired lease timestamp bypasses has_active_lease, but the claim
    # token guard must still refuse — and the caller must report it.
    cli, db = prepare(tmp_path)
    repo = SQLiteRepository(db)
    assert repo.try_decide_pending_approval("first", "owner", ApprovalDecision.APPROVED)
    assert repo.try_claim_execution("first") is not None
    cli.executor.lease_timeout_seconds = 0
    cancelled = cli.cancel_task("first", reason="stop")
    assert cancelled["status"] == "blocked"
    assert cancelled["blockers"] == ["task_update_refused"]
    assert repo.get_task("first").status == TaskStatus.RUNNING
    paused = cli.pause_task("first")
    assert paused["status"] == "blocked"
    assert paused["blockers"] == ["task_update_refused"]
    assert repo.get_task("first").status == TaskStatus.RUNNING


def test_multi_task_multi_approval_workflow(tmp_path):
    cli, _ = prepare(tmp_path, two_approvals=True)
    first = cli.approve("first", approver="owner")
    assert first["status"] == "pass"
    assert first["continuation"]["status"] == "blocked"
    assert cli.repository.get_task("second").status == TaskStatus.APPROVAL_PENDING
    assert len(cli.adapter.execution_log) == 1
    second = cli.approve("second", approver="owner")
    assert second["status"] == "pass"
    assert second["continuation"]["status"] == "pass"
    assert len(cli.adapter.execution_log) == 2
    assert cli.repository.get_workflow("recovery").status.value == "completed"
