"""Tests for task executor."""

import pytest

from workflow_scheduler.adapters import NoopAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import Executor
from workflow_scheduler.models import Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


@pytest.fixture
def executor_setup():
    """Set up executor with dependencies."""
    repository = SQLiteRepository(":memory:")
    audit_logger = AuditLogger(repository=repository)
    adapter = NoopAdapter()
    executor = Executor(
        adapter=adapter,
        repository=repository,
        audit_logger=audit_logger,
        lease_timeout_seconds=300,
    )
    return executor, repository, audit_logger


class TestExecutor:
    """Tests for Executor."""

    def test_execute_simple_task(self, executor_setup):
        """Test executing a simple task."""
        executor, repository, _ = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True
        assert result.error is None
        assert result.status == "pass"

    def test_execute_blocked_production_task(self, executor_setup):
        """Test that production tasks are blocked."""
        executor, repository, _ = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            production_ready=True,
        )
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is False
        assert result.status == "blocked"
        assert "approval_engine_deferred" in result.blockers

        # Task should be marked as governance_blocked
        updated_task = repository.get_task("task-1")
        assert updated_task.status == TaskStatus.GOVERNANCE_BLOCKED

    def test_execute_blocked_approval_required_task(self, executor_setup):
        """Test that approval_required tasks are blocked."""
        executor, repository, _ = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            approval_required=True,
        )
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is False
        assert result.status == "blocked"
        assert "approval_engine_deferred" in result.blockers

    def test_acquire_lease_lock(self, executor_setup):
        """Test that executor acquires lease lock."""
        executor, repository, _ = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )
        repository.create_task(task)

        # Before execution, no lease
        task_before = repository.get_task("task-1")
        assert task_before.lease_lock is None

        executor.execute(task)

        # After execution, lease should be released
        task_after = repository.get_task("task-1")
        assert task_after.lease_lock is None

    def test_concurrent_execution_prevention(self, executor_setup):
        """Test that concurrent execution is prevented via lease locks."""
        executor, repository, _ = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )
        repository.create_task(task)

        # Manually acquire lease (simulating concurrent execution)
        task.acquire_lease()
        repository.update_task(task)

        # Try to execute
        result = executor.execute(task)

        # Execution should fail due to active lease
        assert result.success is False
        assert result.is_transient is True

    def test_governance_check_logged(self, executor_setup):
        """Test that governance checks are logged."""
        executor, repository, audit_logger = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )
        repository.create_task(task)

        executor.execute(task)

        events = audit_logger.get_events()
        event_types = [e.event_type for e in events]

        assert "governance_check_passed" in event_types

    def test_task_completion_logged(self, executor_setup):
        """Test that task completion is logged."""
        executor, repository, audit_logger = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )
        repository.create_task(task)

        executor.execute(task)

        events = audit_logger.get_events()
        event_types = [e.event_type for e in events]

        assert "task_completed" in event_types

    def test_task_status_updated(self, executor_setup):
        """Test that task status is updated after execution."""
        executor, repository, _ = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )
        repository.create_task(task)

        executor.execute(task)

        updated_task = repository.get_task("task-1")
        assert updated_task.status == TaskStatus.COMPLETED

    def test_blocked_task_status_updated(self, executor_setup):
        """Test that blocked task status is updated."""
        executor, repository, _ = executor_setup

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            production_ready=True,
        )
        repository.create_task(task)

        executor.execute(task)

        updated_task = repository.get_task("task-1")
        assert updated_task.status == TaskStatus.GOVERNANCE_BLOCKED
