"""Execution tests for the Phase 2C lifecycle."""

from datetime import UTC, datetime, timedelta
from typing import Any, Dict

import yaml

from workflow_scheduler.adapters import TaskAdapter
from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import Task, TaskStatus, WorkflowStatus


class NeverCalledAdapter(TaskAdapter):
    def __init__(self):
        self.calls = 0

    def execute(self, task: Task) -> Dict[str, Any]:
        self.calls += 1
        raise AssertionError("Adapter.execute() should never be called for this task")


def make_task(task_id: str = "task-1", **overrides) -> Task:
    defaults = dict(
        id=task_id,
        workflow_id="workflow-1",
        type="test",
        owner="system",
        action="test_action",
        idempotency_key=f"key-{task_id}",
    )
    defaults.update(overrides)
    return Task(**defaults)


def write_workflow(tmp_path, workflow_id: str, title: str, action: str = "test_action") -> str:
    workflow_data = {
        "workflow_id": workflow_id,
        "title": title,
        "created_by": "test",
        "mode": "Draft",
        "tasks": [
            {
                "id": "task-1",
                "type": "test",
                "owner": "system",
                "action": action,
                "idempotency_key": "key-1",
            }
        ],
    }
    yaml_path = tmp_path / f"{workflow_id}.yaml"
    with open(yaml_path, "w") as handle:
        yaml.dump(workflow_data, handle)
    return str(yaml_path)


class TestReExecutionExclusionRegression:
    def test_cancelled_task_never_re_executed_on_rerun(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = NeverCalledAdapter()
        cli.executor.adapter = adapter
        cli.create_workflow(write_workflow(tmp_path, "lifecycle-workflow", "Lifecycle Workflow"))
        cli.cancel_task("task-1", reason="not needed")
        workflow = cli.repository.get_workflow("lifecycle-workflow")
        workflow.mark_running()
        cli.repository.update_workflow(workflow)
        result = cli.run_workflow("lifecycle-workflow")
        assert adapter.calls == 0
        assert cli.repository.get_task("task-1").status == TaskStatus.CANCELLED
        assert result["cancelled"] == 1

    def test_paused_task_never_re_executed_on_rerun(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = NeverCalledAdapter()
        cli.executor.adapter = adapter
        cli.create_workflow(write_workflow(tmp_path, "lifecycle-workflow", "Lifecycle Workflow"))
        cli.pause_task("task-1")
        result = cli.run_workflow("lifecycle-workflow")
        assert adapter.calls == 0
        assert cli.repository.get_task("task-1").status == TaskStatus.PAUSED
        assert result["status"] == "blocked"
        assert "tasks_paused" in result["blockers"]
        assert result["paused"] == 1

    def test_run_stays_resumable_while_task_paused_then_resume_completes(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        cli.create_workflow(write_workflow(tmp_path, "lifecycle-workflow", "Lifecycle Workflow"))
        cli.pause_task("task-1")
        first_run = cli.run_workflow("lifecycle-workflow")
        assert first_run["status"] == "blocked"
        assert "tasks_paused" in first_run["blockers"]
        assert not cli.repository.get_workflow("lifecycle-workflow").is_terminal()
        cli.resume_task("task-1")
        second_run = cli.run_workflow("lifecycle-workflow")
        assert second_run["status"] == "pass"
        assert cli.repository.get_task("task-1").status == TaskStatus.COMPLETED
        assert cli.repository.get_workflow("lifecycle-workflow").status == WorkflowStatus.COMPLETED


class TestWorkflowLevelPauseBlocksRun:
    def test_paused_workflow_blocks_run(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        cli.create_workflow(write_workflow(tmp_path, "pausable-workflow", "Pausable Workflow"))
        workflow = cli.repository.get_workflow("pausable-workflow")
        workflow.mark_running()
        cli.repository.update_workflow(workflow)
        assert cli.pause_workflow("pausable-workflow")["status"] == "pass"
        run_result = cli.run_workflow("pausable-workflow")
        assert run_result["status"] == "blocked"
        assert "workflow_paused" in run_result["blockers"]

    def test_resume_workflow_then_run_completes(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        cli.create_workflow(write_workflow(tmp_path, "pausable-workflow", "Pausable Workflow"))
        workflow = cli.repository.get_workflow("pausable-workflow")
        workflow.mark_running()
        cli.repository.update_workflow(workflow)
        cli.pause_workflow("pausable-workflow")
        resume_result = cli.resume_workflow("pausable-workflow")
        assert resume_result["status"] == "pass"
        assert cli.repository.get_workflow("pausable-workflow").status == WorkflowStatus.RUNNING
        run_result = cli.run_workflow("pausable-workflow")
        assert run_result["status"] == "pass"
        assert cli.repository.get_task("task-1").status == TaskStatus.COMPLETED
        assert cli.repository.get_workflow("pausable-workflow").status == WorkflowStatus.COMPLETED


class TestInteractionWithApprovalsAndRetries:
    def test_cancelling_approval_pending_task_makes_stray_approval_request_inert(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(approval_required=True)
        cli.repository.create_task(task)
        cli.executor.execute(task)
        cancel_result = cli.cancel_task(task.id, reason="scope removed")
        assert cancel_result["status"] == "pass"
        assert cli.repository.get_task(task.id).status == TaskStatus.CANCELLED
        approve_result = cli.approve(task.id, approver="alice")
        assert approve_result["status"] == "blocked"
        assert "task_not_awaiting_approval" in approve_result["blockers"]

    def test_pausing_retry_scheduled_task_preserves_retry_fields(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.RETRY_SCHEDULED, retry_count=2, max_retries=5)
        task.next_retry_at = datetime.now(UTC) + timedelta(seconds=60)
        cli.repository.create_task(task)
        cli.pause_task(task.id)
        paused = cli.repository.get_task(task.id)
        assert paused.status == TaskStatus.PAUSED
        assert paused.retry_count == 2
        assert paused.max_retries == 5
        cli.resume_task(task.id)
        resumed = cli.repository.get_task(task.id)
        assert resumed.status == TaskStatus.RETRY_SCHEDULED
        assert resumed.retry_count == 2
        assert resumed.next_retry_at is not None


class TestRunWorkflowAuditEventCorrectness:
    def test_completed_run_emits_workflow_completed_not_failed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        cli.create_workflow(write_workflow(tmp_path, "passing-workflow", "Passing Workflow"))
        result = cli.run_workflow("passing-workflow")
        assert result["status"] == "pass"
        event_types = [event.event_type for event in cli.audit_logger.get_events(workflow_id="passing-workflow")]
        assert "workflow_completed" in event_types
        assert "workflow_failed" not in event_types

    def test_governance_blocked_task_run_emits_workflow_failed_not_completed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        cli.create_workflow(write_workflow(tmp_path, "failing-workflow", "Failing Workflow", action=""))
        result = cli.run_workflow("failing-workflow")
        assert result["status"] == "fail"
        event_types = [event.event_type for event in cli.audit_logger.get_events(workflow_id="failing-workflow")]
        assert "workflow_failed" in event_types
        assert "workflow_completed" not in event_types

    def test_cancelled_task_run_emits_workflow_failed_not_completed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        cli.create_workflow(write_workflow(tmp_path, "cancelled-task-workflow", "Cancelled Task Workflow"))
        cli.cancel_task("task-1", reason="not needed")
        workflow = cli.repository.get_workflow("cancelled-task-workflow")
        workflow.mark_running()
        cli.repository.update_workflow(workflow)
        result = cli.run_workflow("cancelled-task-workflow")
        assert result["status"] == "fail"
        event_types = [
            event.event_type
            for event in cli.audit_logger.get_events(workflow_id="cancelled-task-workflow")
        ]
        assert "workflow_failed" in event_types
        assert "workflow_completed" not in event_types

    def test_resumable_blocked_run_emits_neither_completed_nor_failed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        cli.create_workflow(write_workflow(tmp_path, "paused-task-workflow", "Paused Task Workflow"))
        cli.pause_task("task-1")
        result = cli.run_workflow("paused-task-workflow")
        assert result["status"] == "blocked"
        event_types = [event.event_type for event in cli.audit_logger.get_events(workflow_id="paused-task-workflow")]
        assert "workflow_completed" not in event_types
        assert "workflow_failed" not in event_types
