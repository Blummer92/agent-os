"""Deterministic offline protection controls using real temp SQLite and NoopAdapter."""
import yaml
import pytest

from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import ApprovalDecision, TaskStatus, WorkflowStatus


def _create(tmp_path, *, approval=False):
    plan = {
        "workflow_id": "wf", "title": "Synthetic scheduler control",
        "created_by": "test", "mode": "Draft", "tasks": [
            {"id": "step", "type": "test", "owner": "system", "action": "read:fixture",
             "idempotency_key": "test-step", "approval_required": approval},
        ],
    }
    plan_path = tmp_path / "test-plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))
    db_path = str(tmp_path / "test.sqlite")
    driver = WorkflowSchedulerCLI(db_path=db_path)
    assert driver.create_workflow(str(plan_path))["status"] == "pass"
    return driver, WorkflowSchedulerCLI(db_path=db_path)


@pytest.mark.parametrize("operation", ["pause", "cancel"])
def test_workflow_stop_winning_after_initial_read_prevents_dispatch(tmp_path, monkeypatch, operation):
    cli, other = _create(tmp_path)
    read = cli.repository.get_workflow
    invoked = False

    def read_with_stop(workflow_id):
        nonlocal invoked
        prior = read(workflow_id)
        if not invoked:
            invoked = True
            response = (
                other.pause_workflow(workflow_id) if operation == "pause"
                else other.cancel_workflow(workflow_id, "test stop")
            )
            assert response["status"] == "pass"
        return prior

    monkeypatch.setattr(cli.repository, "get_workflow", read_with_stop)
    result = cli.run_workflow("wf")
    assert invoked
    assert other.repository.get_workflow("wf").status is (
        WorkflowStatus.PAUSED if operation == "pause" else WorkflowStatus.CANCELLED
    )
    assert result["status"] == "blocked"
    assert not cli.adapter.execution_log
    assert "workflow_started" not in _event_types(other)


def test_refused_completion_does_not_report_or_log_success(tmp_path, monkeypatch):
    cli, other = _create(tmp_path)
    execute_many = cli.executor.execute_many

    def finish_then_pause(tasks, *args, **kwargs):
        results = execute_many(tasks, *args, **kwargs)
        assert cli.adapter.execution_log
        assert other.pause_workflow("wf")["status"] == "pass"
        return results

    monkeypatch.setattr(cli.executor, "execute_many", finish_then_pause)
    result = cli.run_workflow("wf")
    assert other.repository.get_workflow("wf").status is WorkflowStatus.PAUSED
    assert other.repository.get_task("step").status is TaskStatus.COMPLETED
    assert result["status"] != "pass" and result.get("final_status") != "completed"
    assert "workflow_completed" not in _event_types(other)


def test_stale_cancel_snapshot_does_not_overwrite_committed_approval(tmp_path, monkeypatch):
    cli, other = _create(tmp_path, approval=True)
    assert cli.run_workflow("wf")["status"] == "blocked"
    get_task = cli.repository.get_task
    invoked = False

    def read_with_approval(task_id):
        nonlocal invoked
        prior = get_task(task_id)
        if not invoked:
            invoked = True
            assert prior.status is TaskStatus.APPROVAL_PENDING
            assert other.repository.try_decide_pending_approval(task_id, "reviewer", ApprovalDecision.APPROVED)
        return prior

    monkeypatch.setattr(cli.repository, "get_task", read_with_approval)
    result = cli.cancel_task("step", "synthetic stale observation")
    assert invoked and result["status"] == "blocked"
    assert other.repository.get_task("step").status is TaskStatus.APPROVED
    assert other.repository.get_approval_request("step").decision is ApprovalDecision.APPROVED
    assert not cli.adapter.execution_log


def test_paused_task_does_not_report_execution_claim_elsewhere(tmp_path, monkeypatch):
    cli, other = _create(tmp_path)
    run = cli.executor.execute_many
    invoked = False

    def pause_before_claim(tasks, *args, **kwargs):
        nonlocal invoked
        if tasks and not invoked:
            invoked = True
            assert other.pause_task("step")["status"] == "pass"
        return run(tasks, *args, **kwargs)

    monkeypatch.setattr(cli.executor, "execute_many", pause_before_claim)
    result = cli.run_workflow("wf")
    assert invoked and result["status"] == "blocked"
    assert other.repository.get_task("step").status is TaskStatus.PAUSED
    assert "tasks_executing_elsewhere" not in result.get("blockers", [])
    assert result.get("in_flight_task_ids", []) == []
    assert not cli.adapter.execution_log


@pytest.mark.parametrize("freshness", ["ordinary", "expired"])
def test_recovery_reports_real_durable_claim_without_redispatch(tmp_path, freshness):
    cli, other = _create(tmp_path, approval=True)
    assert cli.run_workflow("wf")["status"] == "blocked"
    assert other.repository.try_decide_pending_approval("step", "reviewer", ApprovalDecision.APPROVED)
    claim = other.repository.try_claim_execution("step")
    assert claim and other.repository.get_task("step").status is TaskStatus.RUNNING
    if freshness == "expired":
        cli.executor.lease_timeout_seconds = 0
    result = cli.recover_pending_continuations("wf")
    assert result["status"] == "blocked"
    assert result["unresolved_claim_task_ids"] == ["step"]
    assert not result["recovered_task_ids"] and not cli.adapter.execution_log
    assert other.repository.get_task("step").status is TaskStatus.RUNNING


def test_refused_unclaimed_transition_is_not_reported_as_pending_approval(tmp_path):
    cli, other = _create(tmp_path, approval=True)
    stale = cli.repository.get_task("step")
    assert other.cancel_task("step", "synthetic stop")["status"] == "pass"
    result = cli.executor.execute(stale)
    assert other.repository.get_task("step").status is TaskStatus.CANCELLED
    assert "approval_engine_deferred" not in result.blockers
    assert other.repository.get_approval_request("step") is None
    assert "approval_requested" not in _event_types(other)
    assert not cli.adapter.execution_log


def test_successful_workflow_start_does_not_override_later_pause_at_claim(tmp_path, monkeypatch):
    cli, other = _create(tmp_path)
    run = cli.executor.execute_many
    invoked = False

    def pause_before_claim(tasks, *args, **kwargs):
        nonlocal invoked
        if tasks and not invoked:
            invoked = True
            assert other.repository.get_workflow("wf").status is WorkflowStatus.RUNNING
            assert other.pause_workflow("wf")["status"] == "pass"
        return run(tasks, *args, **kwargs)

    monkeypatch.setattr(cli.executor, "execute_many", pause_before_claim)
    result = cli.run_workflow("wf")
    assert invoked and result["status"] == "blocked"
    assert not cli.adapter.execution_log
    assert other.repository.get_workflow("wf").status is WorkflowStatus.PAUSED
    assert not other.repository.get_task("step").status == TaskStatus.COMPLETED


def _event_types(cli):
    return {event["event_type"] for event in cli.repository.get_audit_log(workflow_id="wf")}
