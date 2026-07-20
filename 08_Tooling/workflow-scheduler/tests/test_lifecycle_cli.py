"""CLI tests for the Phase 2C lifecycle."""

from datetime import UTC, datetime, timedelta

from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import Task, TaskStatus, WorkflowPlan, WorkflowStatus


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


def make_workflow(workflow_id: str = "workflow-1", **overrides) -> WorkflowPlan:
    defaults = dict(workflow_id=workflow_id, title="Test Workflow", created_by="test")
    defaults.update(overrides)
    return WorkflowPlan(**defaults)


class TestCLITaskPauseResume:
    def test_pause_task_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        result = cli.pause_task("nonexistent")
        assert result["status"] == "fail"
        assert "not found" in result["error"]

    def test_pause_task_success(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.DRAFT)
        cli.repository.create_task(task)
        result = cli.pause_task(task.id)
        assert result["status"] == "pass"
        stored = cli.repository.get_task(task.id)
        assert stored.status == TaskStatus.PAUSED
        assert stored.paused_from_status == "draft"

    def test_pause_task_refused_when_terminal(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        task.mark_completed()
        cli.repository.create_task(task)
        result = cli.pause_task(task.id)
        assert result["status"] == "blocked"
        assert "task_not_pausable" in result["blockers"]

    def test_pause_task_refused_when_already_paused(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)
        cli.pause_task(task.id)
        result = cli.pause_task(task.id)
        assert result["status"] == "blocked"
        assert "task_not_pausable" in result["blockers"]

    def test_pause_task_refused_with_active_lease(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        task.acquire_lease()
        cli.repository.create_task(task)
        result = cli.pause_task(task.id)
        assert result["status"] == "blocked"
        assert "task_lease_active" in result["blockers"]

    def test_pause_task_allowed_after_lease_expires(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        task.acquire_lease()
        task.lease_lock = datetime.now(UTC) - timedelta(seconds=cli.executor.lease_timeout_seconds + 10)
        cli.repository.create_task(task)
        result = cli.pause_task(task.id)
        assert result["status"] == "pass"

    def test_resume_task_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        result = cli.resume_task("nonexistent")
        assert result["status"] == "fail"

    def test_resume_task_refused_when_not_paused(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.DRAFT)
        cli.repository.create_task(task)
        result = cli.resume_task(task.id)
        assert result["status"] == "blocked"
        assert "task_not_paused" in result["blockers"]

    def test_resume_task_success_restores_status(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.APPROVAL_PENDING)
        cli.repository.create_task(task)
        cli.pause_task(task.id)
        result = cli.resume_task(task.id)
        assert result["status"] == "pass"
        assert result["restored_status"] == "approval_pending"
        stored = cli.repository.get_task(task.id)
        assert stored.status == TaskStatus.APPROVAL_PENDING
        assert stored.paused_from_status is None

    def test_pause_then_resume_round_trip_persists_through_sqlite(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.RETRY_SCHEDULED, retry_count=1)
        cli.repository.create_task(task)
        cli.pause_task(task.id)
        reloaded = cli.repository.get_task(task.id)
        assert reloaded.status == TaskStatus.PAUSED
        assert reloaded.paused_from_status == "retry_scheduled"
        cli.resume_task(task.id)
        final = cli.repository.get_task(task.id)
        assert final.status == TaskStatus.RETRY_SCHEDULED
        assert final.paused_from_status is None
        assert final.retry_count == 1


class TestCLITaskCancel:
    def test_cancel_task_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        result = cli.cancel_task("nonexistent", reason="no")
        assert result["status"] == "fail"

    def test_cancel_task_success(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)
        result = cli.cancel_task(task.id, reason="not needed anymore")
        assert result["status"] == "pass"
        assert cli.repository.get_task(task.id).status == TaskStatus.CANCELLED

    def test_cancel_task_refused_when_already_terminal(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        task.mark_completed()
        cli.repository.create_task(task)
        result = cli.cancel_task(task.id, reason="no")
        assert result["status"] == "blocked"
        assert "task_not_cancellable" in result["blockers"]

    def test_cancel_task_double_cancel_refused(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)
        cli.cancel_task(task.id, reason="first")
        result = cli.cancel_task(task.id, reason="second")
        assert result["status"] == "blocked"
        assert "task_not_cancellable" in result["blockers"]

    def test_cancel_task_refused_with_active_lease(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        task.acquire_lease()
        cli.repository.create_task(task)
        result = cli.cancel_task(task.id, reason="no")
        assert result["status"] == "blocked"
        assert "task_lease_active" in result["blockers"]

    def test_cancel_task_from_paused_status(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)
        cli.pause_task(task.id)
        result = cli.cancel_task(task.id, reason="no longer needed")
        assert result["status"] == "pass"
        assert cli.repository.get_task(task.id).status == TaskStatus.CANCELLED


class TestCLIWorkflowPauseResume:
    def test_pause_workflow_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        assert cli.pause_workflow("nonexistent")["status"] == "fail"

    def test_pause_workflow_allowed_from_draft(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.DRAFT)
        cli.repository.create_workflow(workflow)
        result = cli.pause_workflow(workflow.workflow_id)
        assert result["status"] == "pass"
        assert cli.repository.get_workflow(workflow.workflow_id).status == WorkflowStatus.PAUSED

    def test_pause_workflow_allowed_from_pending(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.PENDING)
        cli.repository.create_workflow(workflow)
        result = cli.pause_workflow(workflow.workflow_id)
        assert result["status"] == "pass"
        assert cli.repository.get_workflow(workflow.workflow_id).status == WorkflowStatus.PAUSED

    def test_pause_workflow_success_from_running(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        cli.repository.create_workflow(workflow)
        result = cli.pause_workflow(workflow.workflow_id)
        assert result["status"] == "pass"
        assert cli.repository.get_workflow(workflow.workflow_id).status == WorkflowStatus.PAUSED

    def test_pause_workflow_refused_when_terminal(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.COMPLETED)
        cli.repository.create_workflow(workflow)
        result = cli.pause_workflow(workflow.workflow_id)
        assert result["status"] == "blocked"
        assert "workflow_terminal" in result["blockers"]

    def test_pause_workflow_refused_when_already_paused(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        cli.repository.create_workflow(workflow)
        cli.pause_workflow(workflow.workflow_id)
        result = cli.pause_workflow(workflow.workflow_id)
        assert result["status"] == "blocked"
        assert "workflow_already_paused" in result["blockers"]

    def test_pause_workflow_from_draft_then_run_is_blocked(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.DRAFT)
        workflow.add_task("task-1")
        cli.repository.create_workflow(workflow)
        cli.repository.create_task(make_task(status=TaskStatus.DRAFT))
        cli.pause_workflow(workflow.workflow_id)
        result = cli.run_workflow(workflow.workflow_id)
        assert result["status"] == "blocked"
        assert "workflow_paused" in result["blockers"]

    def test_resume_workflow_refused_when_not_paused(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        cli.repository.create_workflow(workflow)
        result = cli.resume_workflow(workflow.workflow_id)
        assert result["status"] == "blocked"
        assert "workflow_not_paused" in result["blockers"]

    def test_resume_workflow_success(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        cli.repository.create_workflow(workflow)
        cli.pause_workflow(workflow.workflow_id)
        result = cli.resume_workflow(workflow.workflow_id)
        assert result["status"] == "pass"
        assert cli.repository.get_workflow(workflow.workflow_id).status == WorkflowStatus.RUNNING


class TestCLIWorkflowCancelCascade:
    def test_cancel_workflow_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        assert cli.cancel_workflow("nonexistent", reason="no")["status"] == "fail"

    def test_cancel_workflow_refused_when_terminal(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.COMPLETED)
        cli.repository.create_workflow(workflow)
        result = cli.cancel_workflow(workflow.workflow_id, reason="no")
        assert result["status"] == "blocked"
        assert "workflow_terminal" in result["blockers"]

    def test_cancel_workflow_cascades_to_non_terminal_tasks(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        cli.repository.create_workflow(workflow)
        tasks = (
            make_task(task_id="task-draft", status=TaskStatus.DRAFT),
            make_task(task_id="task-approval", status=TaskStatus.APPROVAL_PENDING),
            make_task(task_id="task-retry", status=TaskStatus.RETRY_SCHEDULED),
            make_task(task_id="task-completed", status=TaskStatus.COMPLETED),
            make_task(task_id="task-failed", status=TaskStatus.FAILED),
        )
        for task in tasks:
            cli.repository.create_task(task)
        result = cli.cancel_workflow(workflow.workflow_id, reason="scope change")
        assert result["status"] == "pass"
        assert cli.repository.get_workflow(workflow.workflow_id).status == WorkflowStatus.CANCELLED
        assert cli.repository.get_task("task-draft").status == TaskStatus.CANCELLED
        assert cli.repository.get_task("task-approval").status == TaskStatus.CANCELLED
        assert cli.repository.get_task("task-retry").status == TaskStatus.CANCELLED
        assert cli.repository.get_task("task-completed").status == TaskStatus.COMPLETED
        assert cli.repository.get_task("task-failed").status == TaskStatus.FAILED
        assert set(result["cancelled_task_ids"]) == {"task-draft", "task-approval", "task-retry"}
        assert result["cancelled_task_count"] == 3

    def test_cancel_workflow_cascade_is_sequential_not_batched(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        cli.repository.create_workflow(workflow)
        for index in range(3):
            cli.repository.create_task(make_task(task_id=f"task-{index}", status=TaskStatus.DRAFT))
        cli.cancel_workflow(workflow.workflow_id, reason="cleanup")
        events = cli.audit_logger.get_events(workflow_id=None)
        task_cancelled_events = [event for event in events if event.event_type == "task_cancelled"]
        assert len(task_cancelled_events) == 3
