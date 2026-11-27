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

    def test_workflow_mode_enum_hydration_draft(self, repository):
        """Test that workflow Draft mode is properly hydrated as enum."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test",
            created_by="user",
            mode=WorkflowMode.DRAFT,
        )

        repository.create_workflow(workflow)
        retrieved = repository.get_workflow("workflow-1")

        assert isinstance(retrieved.mode, WorkflowMode)
        assert retrieved.mode == WorkflowMode.DRAFT

    def test_workflow_mode_enum_hydration_gate(self, repository):
        """Test that workflow Gate mode is properly hydrated as enum."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test",
            created_by="user",
            mode=WorkflowMode.GATE,
        )

        repository.create_workflow(workflow)
        retrieved = repository.get_workflow("workflow-1")

        assert isinstance(retrieved.mode, WorkflowMode)
        assert retrieved.mode == WorkflowMode.GATE

    def test_workflow_mode_enum_hydration_production(self, repository):
        """Test that workflow Production mode is properly hydrated as enum."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test",
            created_by="user",
            mode=WorkflowMode.PRODUCTION,
        )

        repository.create_workflow(workflow)
        retrieved = repository.get_workflow("workflow-1")

        assert isinstance(retrieved.mode, WorkflowMode)
        assert retrieved.mode == WorkflowMode.PRODUCTION

    def test_task_mode_enum_hydration_draft(self, repository):
        """Test that task Draft mode is properly hydrated as enum."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            mode=TaskMode.DRAFT,
        )

        repository.create_task(task)
        retrieved = repository.get_task("task-1")

        assert isinstance(retrieved.mode, TaskMode)
        assert retrieved.mode == TaskMode.DRAFT

    def test_task_mode_enum_hydration_gate(self, repository):
        """Test that task Gate mode is properly hydrated as enum."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            mode=TaskMode.GATE,
        )

        repository.create_task(task)
        retrieved = repository.get_task("task-1")

        assert isinstance(retrieved.mode, TaskMode)
        assert retrieved.mode == TaskMode.GATE

    def test_task_mode_enum_hydration_production(self, repository):
        """Test that task Production mode is properly hydrated as enum."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            mode=TaskMode.PRODUCTION,
        )

        repository.create_task(task)
        retrieved = repository.get_task("task-1")

        assert isinstance(retrieved.mode, TaskMode)
        assert retrieved.mode == TaskMode.PRODUCTION

    def test_list_workflow_tasks_mode_hydration(self, repository):
        """Test that mode is properly hydrated in list_workflow_tasks."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            mode=TaskMode.GATE,
        )

        repository.create_task(task)
        tasks = repository.list_workflow_tasks("workflow-1")

        assert len(tasks) == 1
        assert isinstance(tasks[0].mode, TaskMode)
        assert tasks[0].mode == TaskMode.GATE


def test_pending_transition_round_trips_without_editing_wire_modes(repository):
    workflow = WorkflowPlan("pending-workflow", "Task plan", "owner", mode=WorkflowMode.PRODUCTION)
    repository.create_workflow(workflow)
    workflow.mark_pending()
    assert repository.update_workflow(workflow)
    observed = repository.get_workflow(workflow.workflow_id)
    assert observed.status is WorkflowStatus.PENDING
    assert observed.mode.value == "Production"


def test_completion_update_requires_independent_persisted_task_observation(repository):
    workflow = WorkflowPlan("no-task-row", "Task plan", "owner", tasks=["a"])
    repository.create_workflow(workflow)
    workflow.mark_running()
    assert repository.update_workflow(workflow)
    workflow.mark_completed(completed_task_ids={"a"})
    assert not repository.update_workflow(workflow)
    assert repository.get_workflow("no-task-row").status is WorkflowStatus.RUNNING


@pytest.mark.parametrize("rewrite_plan", [False, True])
def test_completion_rejects_same_count_of_different_persisted_tasks(repository, rewrite_plan):
    workflow = WorkflowPlan("wrong-task-set", "Task plan", "owner", tasks=["planned"])
    repository.create_workflow(workflow)
    workflow.mark_running()
    assert repository.update_workflow(workflow)
    repository.create_task(Task(
        id="different", workflow_id=workflow.workflow_id, type="test",
        owner="owner", action="read:test", idempotency_key="different",
    ))
    token = repository.try_claim_execution("different")
    assert token is not None
    task = repository.get_task("different")
    task.mark_completed({"observed": True})
    assert repository.update_claimed_task(task, token)
    if rewrite_plan:
        workflow = WorkflowPlan(workflow.workflow_id, "Replacement", "owner", tasks=["different"])
        workflow.mark_running()
    workflow.mark_completed(completed_task_ids=set(workflow.tasks))
    assert not repository.update_workflow(workflow)
    observed = repository.get_workflow(workflow.workflow_id)
    assert observed.status is WorkflowStatus.RUNNING and observed.tasks == ["planned"]
