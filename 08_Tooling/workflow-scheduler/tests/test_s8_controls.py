"""Additional offline S8 recovery boundary controls, from separate CLI sessions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from workflow_scheduler.models import ApprovalDecision, TaskStatus, WorkflowStatus

from test_transition_controls import _create


class _SimulatedInterruption(Exception):
    pass


def _interrupt_before_wait_index(tmp_path, monkeypatch):
    driver, peer = _create(tmp_path, approval=True)
    execute_many = driver.executor.execute_many

    def interrupt(tasks, *args, **kwargs):
        results = execute_many(tasks, *args, **kwargs)
        if tasks and peer.repository.get_task("step").status is TaskStatus.APPROVAL_PENDING:
            raise _SimulatedInterruption
        return results

    monkeypatch.setattr(driver.executor, "execute_many", interrupt)
    with pytest.raises(_SimulatedInterruption):
        driver.run_workflow("wf")
    task = peer.repository.get_task("step")
    workflow = peer.repository.get_workflow("wf")
    approval = peer.repository.get_approval_request("step")
    assert task.status is TaskStatus.APPROVAL_PENDING
    assert workflow.status is WorkflowStatus.RUNNING
    assert "step" not in workflow.metadata.get("tasks_awaiting_approval", ())
    assert approval.decision is ApprovalDecision.PENDING
    assert not driver.adapter.execution_log and not peer.adapter.execution_log
    return driver, peer


def test_pre_index_approved_task_respects_parent_pause_until_explicit_resume(tmp_path, monkeypatch):
    _, peer = _interrupt_before_wait_index(tmp_path, monkeypatch)
    assert peer.pause_workflow("wf")["status"] == "pass"
    decision = peer.approve("step", "synthetic-reviewer")
    assert decision["status"] == "pass" and "continuation" not in decision
    assert peer.recover_pending_continuations("wf")["status"] == "blocked"
    assert peer.repository.get_task("step").status is TaskStatus.APPROVED
    assert not peer.adapter.execution_log

    assert peer.resume_workflow("wf")["status"] == "pass"
    resumed = peer.recover_pending_continuations("wf")
    assert resumed["status"] == "pass"
    assert peer.repository.get_task("step").status is TaskStatus.COMPLETED
    assert len(peer.adapter.execution_log) == 1


def test_pre_index_committed_approval_respects_later_workflow_cancellation(tmp_path, monkeypatch):
    driver, peer = _interrupt_before_wait_index(tmp_path, monkeypatch)
    assert peer.repository.try_decide_pending_approval("step", "synthetic-reviewer", ApprovalDecision.APPROVED)
    assert driver.cancel_workflow("wf", "synthetic stop")["status"] == "pass"
    recovered = peer.recover_pending_continuations("wf")
    assert recovered["status"] == "blocked"
    assert peer.repository.get_workflow("wf").status is WorkflowStatus.CANCELLED
    assert peer.repository.get_task("step").status is TaskStatus.CANCELLED
    assert not driver.adapter.execution_log and not peer.adapter.execution_log
    assert peer.repository.get_approval_request("step").decision is ApprovalDecision.APPROVED


@pytest.mark.parametrize("evidence", ["missing", "pending"])
def test_bare_approved_row_without_committed_approval_is_not_dispatch_authority(
    tmp_path, monkeypatch, evidence
):
    if evidence == "pending":
        _, peer = _interrupt_before_wait_index(tmp_path, monkeypatch)
    else:
        _, peer = _create(tmp_path, approval=True)
        plan = peer.repository.get_workflow("wf")
        plan.mark_running()
        assert peer.repository.update_workflow(plan)
    fixture_task = peer.repository.get_task("step")
    # Synthetic incomplete durable state: the status alone is not the record.
    fixture_task.status = TaskStatus.APPROVED
    assert peer.repository.update_task(fixture_task)
    record = peer.repository.get_approval_request("step")
    assert (record is None if evidence == "missing" else record.decision is ApprovalDecision.PENDING)
    result = peer.recover_pending_continuations("wf")
    assert result.get("recovered_task_ids", []) == []
    assert peer.repository.get_task("step").status is TaskStatus.APPROVED
    assert not peer.adapter.execution_log


def test_pre_index_racing_approvals_commit_and_dispatch_at_most_once(tmp_path, monkeypatch):
    driver, peer = _interrupt_before_wait_index(tmp_path, monkeypatch)
    barrier = Barrier(2)

    def approve(cli, reviewer):
        barrier.wait(timeout=3)
        return cli.approve("step", reviewer)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(approve, driver, "synthetic-reviewer-1")
        two = pool.submit(approve, peer, "synthetic-reviewer-2")
        approved = [one.result(timeout=8), two.result(timeout=8)]
    assert sorted(result["status"] for result in approved) == ["blocked", "pass"]
    receipt = peer.repository.get_approval_request("step")
    assert receipt.decision is ApprovalDecision.APPROVED
    assert receipt.approver in {"synthetic-reviewer-1", "synthetic-reviewer-2"}
    if peer.repository.get_task("step").status is not TaskStatus.COMPLETED:
        peer.recover_pending_continuations("wf")
    assert peer.repository.get_task("step").status is TaskStatus.COMPLETED
    assert len(driver.adapter.execution_log) + len(peer.adapter.execution_log) == 1


def test_post_approval_pre_claim_queue_interruption_keeps_recovery_possible(tmp_path, monkeypatch):
    driver, peer = _create(tmp_path, approval=True)
    assert driver.run_workflow("wf")["status"] == "blocked"
    assert driver.repository.try_decide_pending_approval("step", "synthetic-reviewer", ApprovalDecision.APPROVED)

    def interrupt_before_claim(tasks, *args, **kwargs):
        if tasks:
            assert peer.repository.get_task("step").status is TaskStatus.QUEUED
            assert peer.repository.get_task("step").lease_lock is None
            raise _SimulatedInterruption
        return {}

    monkeypatch.setattr(driver.executor, "execute_many", interrupt_before_claim)
    with pytest.raises(_SimulatedInterruption):
        driver.recover_pending_continuations("wf")
    assert not driver.adapter.execution_log
    assert peer.repository.get_approval_request("step").decision is ApprovalDecision.APPROVED
    assert peer.recover_pending_continuations("wf")["status"] == "pass"
    assert peer.repository.get_task("step").status is TaskStatus.COMPLETED
    assert len(peer.adapter.execution_log) == 1


@pytest.mark.parametrize("evidence", ["approved", "pending", "missing"])
def test_unindexed_approved_sibling_is_not_dispatched_by_automatic_continuation(tmp_path, evidence):
    from workflow_scheduler.models import ApprovalRequest, Task

    driver, peer = _create(tmp_path, approval=True)
    assert driver.run_workflow("wf")["status"] == "blocked"
    template = peer.repository.get_task("step")
    sibling = Task(
        id="other", workflow_id="wf", type=template.type, owner=template.owner,
        action=template.action, idempotency_key="other", approval_required=True,
        status=TaskStatus.APPROVAL_PENDING,
    )
    peer.repository.create_task(sibling)
    if evidence != "missing":
        peer.repository.create_approval_request(
            ApprovalRequest(id="other-request", task_id=sibling.id, requested_by="system")
        )
    if evidence == "approved":
        assert peer.repository.try_decide_pending_approval("other", "reviewer", ApprovalDecision.APPROVED)
    else:
        sibling.status = TaskStatus.APPROVED
        assert peer.repository.update_task(sibling)
        # A stale or diagnostic legacy list alone cannot make this eligible.
        plan = peer.repository.get_workflow("wf")
        plan.metadata["tasks_awaiting_approval"].append("other")
        assert peer.repository.update_workflow(plan)
    assert peer.approve("step", "reviewer")["status"] == "pass"
    assert peer.repository.get_task("step").status is TaskStatus.COMPLETED
    assert peer.repository.get_task("other").status is TaskStatus.APPROVED
    assert len(peer.adapter.execution_log) == 1


def test_metadata_cannot_reinstate_superseded_request_bound_wait(tmp_path):
    from datetime import timedelta
    from workflow_scheduler.models import ApprovalRequest

    driver, peer = _create(tmp_path, approval=True)
    assert driver.run_workflow("wf")["status"] == "blocked"
    assert "step" in peer.repository.get_workflow("wf").metadata["tasks_awaiting_approval"]
    old = peer.repository.get_approval_request("step")
    peer.repository.create_approval_request(ApprovalRequest(
        id="replacement", task_id="step", requested_by="system",
        created_at=old.created_at + timedelta(seconds=1),
    ))
    assert peer.repository.try_decide_pending_approval("step", "reviewer", ApprovalDecision.APPROVED)
    result = peer.recover_pending_continuations("wf")
    assert result["recovered_task_ids"] == []
    assert peer.repository.get_task("step").status is TaskStatus.APPROVED
    assert not peer.adapter.execution_log


@pytest.mark.parametrize("waiting", [True, False])
def test_additive_migration_preserves_old_approval_and_requires_legacy_association(tmp_path, waiting):
    import sqlite3
    from workflow_scheduler.cli import WorkflowSchedulerCLI

    driver, peer = _create(tmp_path, approval=True)
    assert driver.run_workflow("wf")["status"] == "blocked"
    if not waiting:
        plan = peer.repository.get_workflow("wf")
        plan.metadata.pop("tasks_awaiting_approval")
        assert peer.repository.update_workflow(plan)
    assert peer.repository.try_decide_pending_approval("step", "reviewer", ApprovalDecision.APPROVED)
    expected = peer.repository.get_approval_request("step")
    path = peer.repository.db_path
    driver.repository.close()
    peer.repository.close()
    with sqlite3.connect(path) as legacy:
        legacy.executescript("""
            ALTER TABLE approval_requests RENAME TO saved_approvals;
            CREATE TABLE approval_requests (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, requested_by TEXT NOT NULL,
                approver TEXT, decision TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL,
                decided_at TEXT, FOREIGN KEY (task_id) REFERENCES tasks(id)
            );
            INSERT INTO approval_requests SELECT
                id, task_id, requested_by, approver, decision, reason, created_at, decided_at
                FROM saved_approvals;
            DROP TABLE saved_approvals;
        """)
    reopened = WorkflowSchedulerCLI(db_path=path)
    assert reopened.repository.get_approval_request("step") == expected
    assert reopened.repository.workflow_approval_waits("wf") == (set(), set())
    result = reopened.recover_pending_continuations("wf")
    assert ("step" in result["recovered_task_ids"]) is waiting
    assert len(reopened.adapter.execution_log) == int(waiting)


def test_wait_provenance_survives_stale_end_of_pass_metadata_write(tmp_path, monkeypatch):
    driver, peer = _create(tmp_path, approval=True)
    execute_many = driver.executor.execute_many

    def write_metadata_before_end_of_pass(tasks, *args, **kwargs):
        results = execute_many(tasks, *args, **kwargs)
        if tasks:
            plan = peer.repository.get_workflow("wf")
            assert "step" not in plan.metadata.get("tasks_awaiting_approval", ())
            plan.metadata["producer_note"] = "keep"
            assert peer.repository.update_workflow(plan)
        return results

    monkeypatch.setattr(driver.executor, "execute_many", write_metadata_before_end_of_pass)
    assert driver.run_workflow("wf")["status"] == "blocked"
    assert peer.repository.get_workflow("wf").metadata["producer_note"] == "keep"
    assert peer.repository.try_decide_pending_approval("step", "reviewer", ApprovalDecision.APPROVED)
    assert peer.recover_pending_continuations("wf")["status"] == "pass"
    assert len(peer.adapter.execution_log) == 1


def test_recover_approval_committed_after_interrupted_first_wait(tmp_path, monkeypatch):
    _, peer = _interrupt_before_wait_index(tmp_path, monkeypatch)
    assert peer.repository.try_decide_pending_approval("step", "reviewer", ApprovalDecision.APPROVED)
    result = peer.recover_pending_continuations("wf")
    assert result["completed_task_ids"] == ["step"]
    assert peer.repository.get_task("step").status is TaskStatus.COMPLETED
    assert len(peer.adapter.execution_log) == 1


def test_mismatched_request_cannot_change_either_tasks_wait_state(tmp_path):
    from workflow_scheduler.models import ApprovalRequest

    driver, peer = _create(tmp_path, approval=True)
    task = driver.repository.get_task("step")
    original = task.status
    task.mark_approval_pending()
    request = ApprovalRequest(id="wrong", task_id="other", requested_by="system")
    with pytest.raises(ValueError, match="different task"):
        driver.repository.update_task(task, approval_request=request)
    assert peer.repository.get_task("step").status is original
    assert peer.repository.get_approval_request("step") is None
    assert peer.repository.get_approval_request("other") is None
