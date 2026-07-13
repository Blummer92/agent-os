"""Tests for the Phase 2C pause/resume/cancel lifecycle."""

from datetime import datetime, timedelta
from typing import Any, Dict

import pytest
import yaml

from workflow_scheduler.adapters import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.execution import Executor
from workflow_scheduler.models import Task, TaskStatus, WorkflowPlan, WorkflowStatus
from workflow_scheduler.repository import SQLiteRepository


class NeverCalledAdapter(TaskAdapter):
    """Test double that fails the test if it is ever invoked."""

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


def make_workflow(workflow_id: str = "workflow-1", **overrides) -> WorkflowPlan:
    defaults = dict(workflow_id=workflow_id, title="Test Workflow", created_by="test")
    defaults.update(overrides)
    return WorkflowPlan(**defaults)


class TestTaskPauseResume:
    """Task-level pause/resume round-trip behavior."""

    def test_mark_paused_stores_prior_status(self):
        task = make_task(status=TaskStatus.APPROVAL_PENDING)

        task.mark_paused()

        assert task.status == TaskStatus.PAUSED
        assert task.paused_from_status == "approval_pending"

    def test_resume_restores_exact_prior_status_draft(self):
        task = make_task(status=TaskStatus.DRAFT)
        task.mark_paused()

        task.resume()

        assert task.status == TaskStatus.DRAFT
        assert task.paused_from_status is None

    def test_resume_restores_exact_prior_status_approval_pending(self):
        task = make_task(status=TaskStatus.APPROVAL_PENDING)
        task.mark_paused()

        task.resume()

        assert task.status == TaskStatus.APPROVAL_PENDING
        assert task.paused_from_status is None

    def test_resume_restores_exact_prior_status_retry_scheduled(self):
        task = make_task(status=TaskStatus.RETRY_SCHEDULED, retry_count=2)
        task.mark_paused()

        task.resume()

        assert task.status == TaskStatus.RETRY_SCHEDULED
        # Retry fields are untouched by pause/resume.
        assert task.retry_count == 2

    def test_resume_clears_paused_from_status(self):
        task = make_task()
        task.mark_paused()
        assert task.paused_from_status is not None

        task.resume()

        assert task.paused_from_status is None

    def test_resume_rejects_if_not_paused(self):
        task = make_task(status=TaskStatus.DRAFT)

        with pytest.raises(ValueError):
            task.resume()

    def test_resume_rejects_if_paused_from_status_missing(self):
        task = make_task(status=TaskStatus.PAUSED, paused_from_status=None)

        with pytest.raises(ValueError):
            task.resume()

    def test_resume_rejects_if_paused_from_status_invalid(self):
        task = make_task(status=TaskStatus.PAUSED, paused_from_status="not_a_real_status")

        with pytest.raises(ValueError):
            task.resume()


class TestWorkflowPauseResume:
    """Workflow-level pause/resume model behavior."""

    def test_mark_paused_sets_status(self):
        workflow = make_workflow(status=WorkflowStatus.RUNNING)

        workflow.mark_paused()

        assert workflow.status == WorkflowStatus.PAUSED

    def test_paused_is_not_terminal(self):
        workflow = make_workflow(status=WorkflowStatus.PAUSED)

        assert workflow.is_terminal() is False

    def test_resume_restores_running(self):
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        workflow.mark_paused()

        workflow.resume()

        assert workflow.status == WorkflowStatus.RUNNING


class TestAuditStatusBeforeCorrectness:
    """Regression: audit events must capture the real prior status, not the
    already-mutated current status."""

    def test_log_task_paused_captures_explicit_previous_status(self):
        logger = AuditLogger()
        task = make_task(status=TaskStatus.APPROVAL_PENDING)
        previous_status = task.status.value

        task.mark_paused()  # task.status is now PAUSED
        logger.log_task_paused(task, previous_status=previous_status)

        events = logger.get_events()
        assert events[0].status_before == "approval_pending"
        assert events[0].status_after == "paused"

    def test_log_task_cancelled_captures_explicit_previous_status(self):
        logger = AuditLogger()
        task = make_task(status=TaskStatus.RETRY_SCHEDULED)
        previous_status = task.status.value

        task.mark_cancelled(reason="no longer needed")
        logger.log_task_cancelled(task, previous_status=previous_status, reason="no longer needed")

        events = logger.get_events()
        assert events[0].status_before == "retry_scheduled"
        assert events[0].status_after == "cancelled"

    def test_log_task_resumed_status_before_after(self):
        logger = AuditLogger()
        task = make_task(status=TaskStatus.APPROVAL_PENDING)
        task.mark_paused()
        task.resume()

        logger.log_task_resumed(task, restored_status=task.status.value)

        events = logger.get_events()
        assert events[0].status_before == "paused"
        assert events[0].status_after == "approval_pending"

    def test_log_workflow_paused_status_before_after(self):
        logger = AuditLogger()
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        workflow.mark_paused()

        logger.log_workflow_paused(workflow)

        events = logger.get_events()
        assert events[0].status_before == "running"
        assert events[0].status_after == "paused"

    def test_log_workflow_resumed_status_before_after(self):
        logger = AuditLogger()
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        workflow.mark_paused()
        workflow.resume()

        logger.log_workflow_resumed(workflow)

        events = logger.get_events()
        assert events[0].status_before == "paused"
        assert events[0].status_after == "running"

    def test_log_workflow_cancelled_captures_explicit_previous_status(self):
        logger = AuditLogger()
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        previous_status = workflow.status.value

        workflow.mark_cancelled(reason="no longer needed")
        logger.log_workflow_cancelled(workflow, previous_status=previous_status, reason="no longer needed")

        events = logger.get_events()
        assert events[0].status_before == "running"
        assert events[0].status_after == "cancelled"


class TestCLITaskPauseResume:
    """CLI-level pause-task/resume-task behavior."""

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
        task.acquire_lease()  # sets lease_lock to now, status RUNNING
        cli.repository.create_task(task)

        result = cli.pause_task(task.id)

        assert result["status"] == "blocked"
        assert "task_lease_active" in result["blockers"]

    def test_pause_task_allowed_after_lease_expires(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        task.acquire_lease()
        task.lease_lock = datetime.utcnow() - timedelta(seconds=cli.executor.lease_timeout_seconds + 10)
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
        """paused_from_status must survive a real SQLite round-trip, not
        just an in-memory object mutation."""
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
    """CLI-level cancel-task behavior."""

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
        stored = cli.repository.get_task(task.id)
        assert stored.status == TaskStatus.CANCELLED

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
    """CLI-level pause-workflow/resume-workflow behavior."""

    def test_pause_workflow_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        result = cli.pause_workflow("nonexistent")

        assert result["status"] == "fail"

    def test_pause_workflow_allowed_from_draft(self, tmp_path):
        """A not-yet-started workflow can be paused up front so a later
        `run` refuses to start it at all."""
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
        stored = cli.repository.get_workflow(workflow.workflow_id)
        assert stored.status == WorkflowStatus.PAUSED

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
        """The whole point of pausing before it starts: `run` must refuse."""
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
        stored = cli.repository.get_workflow(workflow.workflow_id)
        assert stored.status == WorkflowStatus.RUNNING


class TestCLIWorkflowCancelCascade:
    """CLI-level cancel-workflow cascade behavior."""

    def test_cancel_workflow_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        result = cli.cancel_workflow("nonexistent", reason="no")

        assert result["status"] == "fail"

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

        draft_task = make_task(task_id="task-draft", status=TaskStatus.DRAFT)
        approval_task = make_task(task_id="task-approval", status=TaskStatus.APPROVAL_PENDING)
        retry_task = make_task(task_id="task-retry", status=TaskStatus.RETRY_SCHEDULED)
        completed_task = make_task(task_id="task-completed", status=TaskStatus.COMPLETED)
        failed_task = make_task(task_id="task-failed", status=TaskStatus.FAILED)
        for t in (draft_task, approval_task, retry_task, completed_task, failed_task):
            cli.repository.create_task(t)

        result = cli.cancel_workflow(workflow.workflow_id, reason="scope change")

        assert result["status"] == "pass"
        assert cli.repository.get_workflow(workflow.workflow_id).status == WorkflowStatus.CANCELLED

        assert cli.repository.get_task("task-draft").status == TaskStatus.CANCELLED
        assert cli.repository.get_task("task-approval").status == TaskStatus.CANCELLED
        assert cli.repository.get_task("task-retry").status == TaskStatus.CANCELLED
        # Already-terminal tasks are left completely untouched.
        assert cli.repository.get_task("task-completed").status == TaskStatus.COMPLETED
        assert cli.repository.get_task("task-failed").status == TaskStatus.FAILED

        assert set(result["cancelled_task_ids"]) == {"task-draft", "task-approval", "task-retry"}
        assert result["cancelled_task_count"] == 3

    def test_cancel_workflow_cascade_is_sequential_not_batched(self, tmp_path):
        """Sanity check: cascade processes tasks one at a time via repeated
        repository calls, not a bulk/batch operation."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow = make_workflow(status=WorkflowStatus.RUNNING)
        cli.repository.create_workflow(workflow)
        for i in range(3):
            cli.repository.create_task(make_task(task_id=f"task-{i}", status=TaskStatus.DRAFT))

        cli.cancel_workflow(workflow.workflow_id, reason="cleanup")

        events = cli.audit_logger.get_events(workflow_id=None)
        task_cancelled_events = [e for e in events if e.event_type == "task_cancelled"]
        assert len(task_cancelled_events) == 3


class TestReExecutionExclusionRegression:
    """The core §7 correctness fix: cancelled and paused tasks must never
    be force-queued and re-invoked on a run_workflow rerun."""

    def _write_workflow_yaml(self, tmp_path):
        workflow_data = {
            "workflow_id": "lifecycle-workflow",
            "title": "Lifecycle Workflow",
            "created_by": "test",
            "mode": "Draft",
            "tasks": [
                {
                    "id": "task-1",
                    "type": "test",
                    "owner": "system",
                    "action": "test_action",
                    "idempotency_key": "key-1",
                }
            ],
        }
        yaml_path = tmp_path / "workflow.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        return str(yaml_path)

    def test_cancelled_task_never_re_executed_on_rerun(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = NeverCalledAdapter()
        cli.executor.adapter = adapter

        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

        cli.cancel_task("task-1", reason="not needed")
        # Workflow itself is still RUNNING-eligible (never started via `run`).
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

        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

        cli.pause_task("task-1")

        result = cli.run_workflow("lifecycle-workflow")

        assert adapter.calls == 0
        assert cli.repository.get_task("task-1").status == TaskStatus.PAUSED
        assert result["status"] == "blocked"
        assert "tasks_paused" in result["blockers"]
        assert result["paused"] == 1

    def test_run_stays_resumable_while_task_paused_then_resume_completes(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))

        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

        cli.pause_task("task-1")
        first_run = cli.run_workflow("lifecycle-workflow")

        assert first_run["status"] == "blocked"
        assert "tasks_paused" in first_run["blockers"]
        workflow_after_pause = cli.repository.get_workflow("lifecycle-workflow")
        assert not workflow_after_pause.is_terminal()

        cli.resume_task("task-1")
        second_run = cli.run_workflow("lifecycle-workflow")

        assert second_run["status"] == "pass"
        assert cli.repository.get_task("task-1").status == TaskStatus.COMPLETED
        assert cli.repository.get_workflow("lifecycle-workflow").status == WorkflowStatus.COMPLETED


class TestWorkflowLevelPauseBlocksRun:
    """Requirement: paused workflow blocks run; resume-workflow works;
    resumed workflow can run again."""

    def _write_workflow_yaml(self, tmp_path):
        workflow_data = {
            "workflow_id": "pausable-workflow",
            "title": "Pausable Workflow",
            "created_by": "test",
            "mode": "Draft",
            "tasks": [
                {
                    "id": "task-1",
                    "type": "test",
                    "owner": "system",
                    "action": "test_action",
                    "idempotency_key": "key-1",
                }
            ],
        }
        yaml_path = tmp_path / "workflow.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        return str(yaml_path)

    def test_paused_workflow_blocks_run(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

        # A workflow must be RUNNING before it can be paused; start it via
        # a pause on a task so the first `run` leaves it RUNNING+resumable,
        # matching real usage (pause-workflow only valid while RUNNING).
        workflow = cli.repository.get_workflow("pausable-workflow")
        workflow.mark_running()
        cli.repository.update_workflow(workflow)

        pause_result = cli.pause_workflow("pausable-workflow")
        assert pause_result["status"] == "pass"

        run_result = cli.run_workflow("pausable-workflow")

        assert run_result["status"] == "blocked"
        assert "workflow_paused" in run_result["blockers"]

    def test_resume_workflow_then_run_completes(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

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
    """Lifecycle must not break existing approval/retry behavior."""

    def test_cancelling_approval_pending_task_makes_stray_approval_request_inert(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(approval_required=True)
        cli.repository.create_task(task)
        cli.executor.execute(task)  # -> APPROVAL_PENDING, creates ApprovalRequest

        cancel_result = cli.cancel_task(task.id, reason="scope removed")
        assert cancel_result["status"] == "pass"
        assert cli.repository.get_task(task.id).status == TaskStatus.CANCELLED

        # The stray PENDING approval request is now unreachable: approve()
        # requires task.status == APPROVAL_PENDING, which no longer holds.
        approve_result = cli.approve(task.id, approver="alice")
        assert approve_result["status"] == "blocked"
        assert "task_not_awaiting_approval" in approve_result["blockers"]

    def test_pausing_retry_scheduled_task_preserves_retry_fields(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.RETRY_SCHEDULED, retry_count=2, max_retries=5)
        task.next_retry_at = datetime.utcnow() + timedelta(seconds=60)
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
    """Regression: run_workflow must emit the audit event matching the
    actual outcome — workflow_completed only on a real pass, workflow_failed
    on fail/blocked/cancelled — never workflow_completed regardless of
    outcome."""

    def test_completed_run_emits_workflow_completed_not_failed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow_data = {
            "workflow_id": "passing-workflow",
            "title": "Passing Workflow",
            "created_by": "test",
            "mode": "Draft",
            "tasks": [
                {
                    "id": "task-1",
                    "type": "test",
                    "owner": "system",
                    "action": "test_action",
                    "idempotency_key": "key-1",
                }
            ],
        }
        yaml_path = tmp_path / "passing.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        cli.create_workflow(str(yaml_path))

        result = cli.run_workflow("passing-workflow")

        assert result["status"] == "pass"
        event_types = [e.event_type for e in cli.audit_logger.get_events(workflow_id="passing-workflow")]
        assert "workflow_completed" in event_types
        assert "workflow_failed" not in event_types

    def test_governance_blocked_task_run_emits_workflow_failed_not_completed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow_data = {
            "workflow_id": "failing-workflow",
            "title": "Failing Workflow",
            "created_by": "test",
            "mode": "Draft",
            "tasks": [
                {
                    "id": "task-1",
                    "type": "test",
                    "owner": "system",
                    "action": "",  # ambiguous_target -> hard governance block
                    "idempotency_key": "key-1",
                }
            ],
        }
        yaml_path = tmp_path / "failing.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        cli.create_workflow(str(yaml_path))

        result = cli.run_workflow("failing-workflow")

        assert result["status"] == "fail"
        event_types = [e.event_type for e in cli.audit_logger.get_events(workflow_id="failing-workflow")]
        assert "workflow_failed" in event_types
        assert "workflow_completed" not in event_types

    def test_cancelled_task_run_emits_workflow_failed_not_completed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow_data = {
            "workflow_id": "cancelled-task-workflow",
            "title": "Cancelled Task Workflow",
            "created_by": "test",
            "mode": "Draft",
            "tasks": [
                {
                    "id": "task-1",
                    "type": "test",
                    "owner": "system",
                    "action": "test_action",
                    "idempotency_key": "key-1",
                }
            ],
        }
        yaml_path = tmp_path / "cancelled_task.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        cli.create_workflow(str(yaml_path))

        cli.cancel_task("task-1", reason="not needed")
        workflow = cli.repository.get_workflow("cancelled-task-workflow")
        workflow.mark_running()
        cli.repository.update_workflow(workflow)

        result = cli.run_workflow("cancelled-task-workflow")

        assert result["status"] == "fail"
        event_types = [e.event_type for e in cli.audit_logger.get_events(workflow_id="cancelled-task-workflow")]
        assert "workflow_failed" in event_types
        assert "workflow_completed" not in event_types

    def test_resumable_blocked_run_emits_neither_completed_nor_failed(self, tmp_path):
        """The approval/retry/paused resumable-blocked branch returns before
        reaching the completed/failed audit call at all."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        workflow_data = {
            "workflow_id": "paused-task-workflow",
            "title": "Paused Task Workflow",
            "created_by": "test",
            "mode": "Draft",
            "tasks": [
                {
                    "id": "task-1",
                    "type": "test",
                    "owner": "system",
                    "action": "test_action",
                    "idempotency_key": "key-1",
                }
            ],
        }
        yaml_path = tmp_path / "paused_task.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        cli.create_workflow(str(yaml_path))

        cli.pause_task("task-1")
        result = cli.run_workflow("paused-task-workflow")

        assert result["status"] == "blocked"
        event_types = [e.event_type for e in cli.audit_logger.get_events(workflow_id="paused-task-workflow")]
        assert "workflow_completed" not in event_types
        assert "workflow_failed" not in event_types
