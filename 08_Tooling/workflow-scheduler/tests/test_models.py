"""Tests for workflow scheduler models."""

import pytest
from datetime import UTC, datetime

from workflow_scheduler.models import Task, TaskMode, TaskStatus, WorkflowPlan, WorkflowMode, WorkflowStatus


class TestTaskModel:
    """Tests for Task model."""

    def test_task_creation(self):
        """Test task creation with defaults."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test_action",
            idempotency_key="key-1",
        )

        assert task.id == "task-1"
        assert task.status == TaskStatus.DRAFT
        assert task.mode == TaskMode.DRAFT
        assert task.priority == 0
        assert task.approval_required is False
        assert task.production_ready is False
        assert task.lease_lock is None

    def test_task_mark_approved(self):
        """Test marking task as approved."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        task.mark_approved()
        assert task.status == TaskStatus.APPROVED

    def test_task_mark_completed(self):
        """Test marking task as completed."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        result = {"output": "success"}
        task.mark_completed(result=result)

        assert task.status == TaskStatus.COMPLETED
        assert task.payload["result"] == result

    def test_task_mark_failed(self):
        """Test marking task as failed."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        task.mark_failed(error="Test error", is_transient=False)
        assert task.status == TaskStatus.FAILED
        assert task.payload["error"] == "Test error"

        # Transient failure
        task2 = Task(
            id="task-2",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-2",
        )
        task2.mark_failed(error="Timeout", is_transient=True)
        assert task2.status == TaskStatus.RETRY_SCHEDULED

    def test_task_mark_paused(self):
        """Test marking task as paused."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        task.mark_paused()
        assert task.status == TaskStatus.PAUSED

    def test_task_mark_cancelled(self):
        """Test marking task as cancelled."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        task.mark_cancelled(reason="User cancelled")
        assert task.status == TaskStatus.CANCELLED
        assert task.payload["cancellation_reason"] == "User cancelled"

    def test_task_lease_lock(self):
        """Test lease lock acquisition and release."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        assert task.lease_lock is None
        task.acquire_lease()
        assert task.lease_lock is not None
        assert task.status == TaskStatus.RUNNING

        task.release_lease()
        assert task.lease_lock is None

    def test_task_has_active_lease(self):
        """Test checking for active lease."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        assert not task.has_active_lease()

        task.acquire_lease()
        assert task.has_active_lease(timeout_seconds=300)

        # Old lease (expired)
        task.lease_lock = datetime.now(UTC)
        import time

        time.sleep(0.01)
        assert not task.has_active_lease(timeout_seconds=0.001)

    def test_task_is_ready_to_run(self):
        """Test checking if task is ready to run."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        assert not task.is_ready_to_run()

        task.status = TaskStatus.APPROVED
        assert task.is_ready_to_run()

        task.acquire_lease()
        assert not task.is_ready_to_run()

    def test_task_is_completed(self):
        """Test checking if task is in terminal state."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        assert not task.is_completed()

        task.mark_completed()
        assert task.is_completed()

        task2 = Task(
            id="task-2",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-2",
        )
        task2.mark_failed("error")
        assert task2.is_completed()


class TestWorkflowPlanModel:
    """Tests for WorkflowPlan model."""

    def test_workflow_creation(self):
        """Test workflow creation."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        assert workflow.workflow_id == "workflow-1"
        assert workflow.title == "Test Workflow"
        assert workflow.status == WorkflowStatus.DRAFT
        assert len(workflow.tasks) == 0

    def test_workflow_add_task(self):
        """Test adding task to workflow."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        workflow.add_task("task-1")
        assert "task-1" in workflow.tasks

        # Add duplicate (should not duplicate)
        workflow.add_task("task-1")
        assert workflow.tasks.count("task-1") == 1

    def test_workflow_set_dependencies(self):
        """Test setting task dependencies."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        workflow.set_dependencies("task-1", ["task-0"])
        assert workflow.dependencies["task-1"] == ["task-0"]

    def test_workflow_mark_running(self):
        """Test marking workflow as running."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        workflow.mark_running()
        assert workflow.status == WorkflowStatus.RUNNING

    def test_workflow_mark_completed(self):
        """Test marking workflow as completed."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        workflow.mark_completed()
        assert workflow.status == WorkflowStatus.COMPLETED

    def test_workflow_mark_failed(self):
        """Test marking workflow as failed."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        workflow.mark_failed(reason="Test failure")
        assert workflow.status == WorkflowStatus.FAILED
        assert workflow.metadata["failure_reason"] == "Test failure"

    def test_workflow_mark_cancelled(self):
        """Test marking workflow as cancelled."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        workflow.mark_cancelled(reason="User cancelled")
        assert workflow.status == WorkflowStatus.CANCELLED
        assert workflow.metadata["cancellation_reason"] == "User cancelled"

    def test_workflow_mark_governance_blocked(self):
        """Test marking workflow as governance blocked."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        workflow.mark_governance_blocked(reason="Policy violation")
        assert workflow.status == WorkflowStatus.GOVERNANCE_BLOCKED
        assert workflow.metadata["governance_block_reason"] == "Policy violation"

    def test_workflow_is_terminal(self):
        """Test checking if workflow is in terminal state."""
        workflow = WorkflowPlan(
            workflow_id="workflow-1",
            title="Test Workflow",
            created_by="user",
        )

        assert not workflow.is_terminal()

        workflow.mark_completed()
        assert workflow.is_terminal()

        workflow2 = WorkflowPlan(
            workflow_id="workflow-2",
            title="Test Workflow 2",
            created_by="user",
        )
        workflow2.mark_failed()
        assert workflow2.is_terminal()
