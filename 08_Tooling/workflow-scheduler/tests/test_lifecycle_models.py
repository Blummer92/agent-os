"""Model and audit tests for the Phase 2C lifecycle."""

from workflow_scheduler.audit import AuditLogger
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
        assert task.retry_count == 2

    def test_resume_clears_paused_from_status(self):
        task = make_task()
        task.mark_paused()
        assert task.paused_from_status is not None
        task.resume()
        assert task.paused_from_status is None

    def test_resume_rejects_if_not_paused(self):
        import pytest

        task = make_task(status=TaskStatus.DRAFT)
        with pytest.raises(ValueError):
            task.resume()

    def test_resume_rejects_if_paused_from_status_missing(self):
        import pytest

        task = make_task(status=TaskStatus.PAUSED, paused_from_status=None)
        with pytest.raises(ValueError):
            task.resume()

    def test_resume_rejects_if_paused_from_status_invalid(self):
        import pytest

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
    """Audit events must capture the real prior status."""

    def test_log_task_paused_captures_explicit_previous_status(self):
        logger = AuditLogger()
        task = make_task(status=TaskStatus.APPROVAL_PENDING)
        previous_status = task.status.value
        task.mark_paused()
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
