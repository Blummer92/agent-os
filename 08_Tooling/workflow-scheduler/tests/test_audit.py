"""Tests for audit logger."""

import pytest

from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.models import Task, WorkflowPlan


class TestAuditLogger:
    """Tests for AuditLogger."""

    def test_log_task_created(self):
        """Test logging task creation."""
        logger = AuditLogger()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        logger.log_task_created(task)

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "task_created"
        assert events[0].task_id == "task-1"

    def test_log_task_approved(self):
        """Test logging task approval."""
        logger = AuditLogger()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        logger.log_task_approved(task, approved_by="reviewer")

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "task_approved"
        assert events[0].details["approved_by"] == "reviewer"

    def test_log_task_completed(self):
        """Test logging task completion."""
        logger = AuditLogger()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        result = {"output": "success"}
        logger.log_task_completed(task, result=result)

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "task_completed"
        assert events[0].details["result"] == result

    def test_log_task_failed(self):
        """Test logging task failure."""
        logger = AuditLogger()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        logger.log_task_failed(task, error="Test error", is_transient=False)

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "task_failed"
        assert events[0].details["error"] == "Test error"
        assert events[0].details["is_transient"] is False

    def test_log_task_paused(self):
        """Test logging task pause."""
        logger = AuditLogger()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        logger.log_task_paused(task)

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "task_paused"

    def test_log_task_cancelled(self):
        """Test logging task cancellation."""
        logger = AuditLogger()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        logger.log_task_cancelled(task, reason="User cancelled")

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "task_cancelled"
        assert events[0].details["reason"] == "User cancelled"

    def test_log_governance_blocked(self):
        """Test logging governance block."""
        logger = AuditLogger()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        blockers = ["ambiguous_target", "missing_authorization"]
        logger.log_governance_blocked(task, blockers=blockers, reason="Policy violation")

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "governance_blocked"
        assert events[0].details["blockers"] == blockers

    def test_log_workflow_created(self):
        """Test logging workflow creation."""
        logger = AuditLogger()
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        logger.log_workflow_created(workflow)

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "workflow_created"
        assert events[0].workflow_id == "workflow-1"

    def test_log_workflow_completed(self):
        """Test logging workflow completion."""
        logger = AuditLogger()
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        logger.log_workflow_completed(workflow)

        events = logger.get_events()
        assert len(events) == 1
        assert events[0].event_type == "workflow_completed"

    def test_filter_events_by_task_id(self):
        """Test filtering audit events by task ID."""
        logger = AuditLogger()

        task1 = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )
        task2 = Task(
            id="task-2",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-2",
        )

        logger.log_task_created(task1)
        logger.log_task_created(task2)

        task1_events = logger.get_events(task_id="task-1")
        assert len(task1_events) == 1
        assert task1_events[0].task_id == "task-1"

    def test_filter_events_by_workflow_id(self):
        """Test filtering audit events by workflow ID."""
        logger = AuditLogger()

        workflow1 = WorkflowPlan(workflow_id="workflow-1", title="Workflow 1", created_by="user")
        workflow2 = WorkflowPlan(workflow_id="workflow-2", title="Workflow 2", created_by="user")

        logger.log_workflow_created(workflow1)
        logger.log_workflow_created(workflow2)

        wf1_events = logger.get_events(workflow_id="workflow-1")
        assert len(wf1_events) == 1
        assert wf1_events[0].workflow_id == "workflow-1"

    def test_event_timestamps(self):
        """Test that events have timestamps."""
        logger = AuditLogger()
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        logger.log_task_created(task)

        events = logger.get_events()
        assert len(events[0].timestamp) > 0
