import os

import pytest

from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import TaskStatus, WorkflowStatus

from test_s8_qa_regressions import _Adapter, _plan


def _defer():
    return _Adapter({"status": "approval-required", "message": "review",
                     "approval_reason": "human approval required"})


def test_adapter_deferral_continues_once_after_approval(tmp_path):
    db = _plan(tmp_path, ("t0", "t1"))
    cli = WorkflowSchedulerCLI(db_path=db)
    plan = cli.repository.get_workflow("wf")
    plan.set_dependencies("t1", ["t0"])
    assert cli.repository.update_workflow(plan)
    assert cli.repository.get_workflow("wf").dependencies["t1"] == ["t0"]
    cli.executor.adapter = _defer()
    wait = cli.run_workflow("wf")
    assert wait["blockers"] == ["tasks_awaiting_approval"]
    assert cli.executor.adapter.execution_log == ["t0"]
    reader = WorkflowSchedulerCLI(db_path=db)
    assert reader.repository.get_task("t0").approval_required
    assert reader.repository.workflow_approval_waits("wf") == ({"t0"}, {"t0"})
    reader.executor.adapter = _Adapter({"success": True, "output": {}})
    assert reader.run_workflow("wf")["blockers"] == ["tasks_awaiting_approval"]
    assert reader.executor.adapter.execution_log == []
    assert reader.approve("t0", "reviewer")["continuation"]["status"] == "pass"
    assert reader.executor.adapter.execution_log == ["t0", "t1"]
    assert reader.repository.get_workflow("wf").status is WorkflowStatus.COMPLETED
    assert "continuation" not in reader.approve("t0", "reviewer")
    reader.recover_pending_continuations("wf")
    assert reader.executor.adapter.execution_log == ["t0", "t1"]


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
def test_crash_after_adapter_wait_commit_preserves_exact_pending_request(tmp_path):
    db = _plan(tmp_path)
    pid = os.fork()
    if pid == 0:
        cli = WorkflowSchedulerCLI(db_path=db)
        cli.executor.adapter = _defer()
        original = cli.repository.update_claimed_task
        def crash(*args, **kwargs):
            os._exit(77 if original(*args, **kwargs) else 3)
        cli.repository.update_claimed_task = crash
        cli.run_workflow("wf")
        os._exit(4)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 77
    cli = WorkflowSchedulerCLI(db_path=db)
    task = cli.repository.get_task("t0")
    assert task.status is TaskStatus.APPROVAL_PENDING
    assert task.approval_required and task.lease_lock is None
    assert cli.repository.workflow_approval_waits("wf") == ({"t0"}, {"t0"})
    cli.executor.adapter = _Adapter({"success": True, "output": {}})
    assert cli.recover_pending_continuations("wf")["still_pending_task_ids"] == ["t0"]
    assert cli.executor.adapter.execution_log == []
    assert cli.approve("t0", "reviewer")["continuation"]["status"] == "pass"
    assert cli.executor.adapter.execution_log == ["t0"]


def test_request_persistence_error_rolls_back_deferral_and_retains_claim(tmp_path, monkeypatch):
    db = _plan(tmp_path)
    cli = WorkflowSchedulerCLI(db_path=db)
    cli.executor.adapter = _defer()
    insert = cli.repository._insert_approval_request
    def broken_insert(*args, **kwargs):
        insert(*args, **kwargs)
        raise OSError("request persistence failed")
    monkeypatch.setattr(cli.repository, "_insert_approval_request", broken_insert)
    with pytest.raises(OSError, match="request persistence failed"):
        cli.run_workflow("wf")
    other = WorkflowSchedulerCLI(db_path=db)
    assert other.repository.get_approval_request("t0") is None
    row = other.repository.get_task("t0")
    assert row.status is TaskStatus.RUNNING and row.lease_lock is not None
    assert other.repository.try_claim_execution("t0") is None
    assert other.repository.get_workflow("wf").status is WorkflowStatus.RUNNING


def test_second_adapter_deferral_cannot_be_reapproved_by_a_delayed_task_id(tmp_path):
    db = _plan(tmp_path)
    cli = WorkflowSchedulerCLI(db_path=db)
    cli.executor.adapter = _defer()
    cli.run_workflow("wf")
    first = cli.repository.get_approval_request("t0").id
    assert cli.approve("t0", "reviewer")["continuation"]["status"] == "fail"
    current = cli.repository.get_approval_request("t0")
    assert current.id == first and current.decision.value == "approved"
    assert cli.repository.get_task("t0").status is TaskStatus.GOVERNANCE_BLOCKED
    assert cli.approve("t0", "delayed reviewer")["blockers"] == ["task_not_awaiting_approval"]
    assert cli.executor.adapter.execution_log == ["t0", "t0"]


def test_racing_request_rolls_back_claimed_deferral(tmp_path, monkeypatch):
    from workflow_scheduler.models import ApprovalDecision, ApprovalRequest

    db = _plan(tmp_path)
    cli = WorkflowSchedulerCLI(db_path=db)
    cli.executor.adapter = _defer()
    other = WorkflowSchedulerCLI(db_path=db)
    persist = cli.repository.update_claimed_task
    def race(*args, **kwargs):
        other.repository.create_approval_request(ApprovalRequest(
            id="other-request", task_id="t0", requested_by="system",
            decision=ApprovalDecision.PENDING,
        ))
        return persist(*args, **kwargs)
    monkeypatch.setattr(cli.repository, "update_claimed_task", race)
    with pytest.raises(RuntimeError, match="task update refused"):
        cli.run_workflow("wf")
    assert other.repository.get_approval_request("t0").id == "other-request"
    assert other.repository.workflow_approval_waits("wf") == (set(), set())
    assert other.repository.get_task("t0").lease_lock is not None
    assert other.repository.try_claim_execution("t0") is None


def test_adapter_wait_does_not_resume_paused_workflow(tmp_path):
    db = _plan(tmp_path)
    cli = WorkflowSchedulerCLI(db_path=db)
    cli.executor.adapter = _defer()
    cli.run_workflow("wf")
    assert cli.pause_workflow("wf")["status"] == "pass"
    cli.executor.adapter = _Adapter({"success": True, "output": {}})
    recovery = cli.recover_pending_continuations("wf")
    assert recovery["blockers"] == ["workflow_not_running"]
    assert "continuation" not in cli.approve("t0", "reviewer")
    assert cli.executor.adapter.execution_log == []
    assert cli.repository.get_workflow("wf").status is WorkflowStatus.PAUSED
