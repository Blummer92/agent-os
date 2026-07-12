"""Tests for SQLite repository."""

import pytest
from datetime import datetime

from workflow_scheduler.models import Task, TaskMode, TaskStatus, WorkflowPlan, WorkflowMode, WorkflowStatus
from workflow_scheduler.repository import SQLiteRepository


@pytest.fixture
def repository():
    """Create in-memory SQLite repository for testing."""
    return SQLiteRepository(":memory:")


class TestSQLiteRepository:
    """Tests for SQLiteRepository."""

    def test_workflow_create_and_retrieve(self, repository):
        """Test creating and retrieving workflow."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        repository.create_workflow(workflow)
        retrieved = repository.get_workflow("workflow-1")

        assert retrieved is not None
        assert retrieved.workflow_id == "workflow-1"
        assert retrieved.title == "Test Workflow"
        assert retrieved.status == WorkflowStatus.DRAFT

    def test_workflow_update(self, repository):
        """Test updating workflow."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        repository.create_workflow(workflow)

        workflow.mark_running()
        repository.update_workflow(workflow)

        retrieved = repository.get_workflow("workflow-1")
        assert retrieved.status == WorkflowStatus.RUNNING

    def test_task_create_and_retrieve(self, repository):
        """Test creating and retrieving task."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        repository.create_task(task)
        retrieved = repository.get_task("task-1")

        assert retrieved is not None
        assert retrieved.id == "task-1"
        assert retrieved.status == TaskStatus.DRAFT

    def test_task_update(self, repository):
        """Test updating task."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        repository.create_task(task)

        task.mark_approved()
        repository.update_task(task)

        retrieved = repository.get_task("task-1")
        assert retrieved.status == TaskStatus.APPROVED

    def test_list_workflow_tasks(self, repository):
        """Test listing workflow tasks."""
        for i in range(3):
            task = Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
                priority=i,
            )
            repository.create_task(task)

        tasks = repository.list_workflow_tasks("workflow-1")
        assert len(tasks) == 3

        # Tasks should be sorted by priority (descending)
        assert tasks[0].priority == 2

    def test_audit_log_events(self, repository):
        """Test logging and retrieving audit events."""
        repository.log_event(
            event_type="task_created",
            task_id="task-1",
            workflow_id="workflow-1",
            details={"action": "test"},
        )

        events = repository.get_audit_log(workflow_id="workflow-1")
        assert len(events) == 1
        assert events[0]["event_type"] == "task_created"

    def test_get_nonexistent_workflow(self, repository):
        """Test retrieving nonexistent workflow."""
        result = repository.get_workflow("nonexistent")
        assert result is None

    def test_get_nonexistent_task(self, repository):
        """Test retrieving nonexistent task."""
        result = repository.get_task("nonexistent")
        assert result is None

    def test_task_with_lease_lock(self, repository):
        """Test storing and retrieving task with lease lock."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        task.acquire_lease()
        repository.create_task(task)

        retrieved = repository.get_task("task-1")
        assert retrieved.lease_lock is not None
        assert retrieved.status == TaskStatus.RUNNING

    def test_close_connection(self, repository):
        """Test closing database connection."""
        # Create a workflow first
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test",
            created_by="user",
        )
        repository.create_workflow(workflow)

        # Close connection
        repository.close()
        assert repository._connection is None

        # Retrieving should still work (creates new connection, but in-memory DB is lost)
        # So we just verify close doesn't raise an error
        repository.close()  # Should not raise
