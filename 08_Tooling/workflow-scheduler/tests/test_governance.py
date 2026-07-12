"""Tests for governance stop conditions."""

import pytest

from workflow_scheduler.governance import StopConditionChecker
from workflow_scheduler.models import Task, TaskMode


class TestStopConditions:
    """Tests for stop condition enforcement."""

    def test_approval_engine_deferred_production(self):
        """Test that production tasks are blocked with approval_engine_deferred."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="write:database",
            idempotency_key="key-1",
            production_ready=True,
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "approval_engine_deferred" in result.blockers

    def test_approval_engine_deferred_approval_required(self):
        """Test that approval_required tasks are blocked."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="approve:workflow",
            idempotency_key="key-1",
            approval_required=True,
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "approval_engine_deferred" in result.blockers

    def test_ambiguous_target_empty_action(self):
        """Test that tasks with empty action are blocked."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="",
            idempotency_key="key-1",
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "ambiguous_target" in result.blockers

    def test_valid_task_no_blocks(self):
        """Test that valid tasks pass all checks."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="execute:test",
            idempotency_key="key-1",
            production_ready=False,
            approval_required=False,
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is False
        assert len(result.blockers) == 0

    def test_missing_authorization_check(self):
        """Test missing authorization stop condition."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="user-1",
            action="write:restricted_system",
            idempotency_key="key-1",
        )

        ownership_registry = {
            "user-1": {"owned_systems": ["write:own_system", "read:restricted_system"]},
        }

        result = StopConditionChecker.check_all_stop_conditions(task, ownership_registry=ownership_registry)

        assert result.is_blocked is True
        assert "missing_authorization" in result.blockers

    def test_read_operations_not_blocked_by_authorization(self):
        """Test that read operations don't trigger authorization block."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="user-1",
            action="read:any_system",
            idempotency_key="key-1",
        )

        ownership_registry = {"user-1": {"owned_systems": []}}

        result = StopConditionChecker.check_all_stop_conditions(task, ownership_registry=ownership_registry)

        # Should not be blocked by authorization (read operations allowed)
        assert "missing_authorization" not in result.blockers

    def test_check_approval_required_helper(self):
        """Test approval_required helper method."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            approval_required=True,
        )

        result = StopConditionChecker.check_approval_required(task)
        assert result.is_blocked is True

        task2 = Task(
            id="task-2",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-2",
            approval_required=False,
        )

        result2 = StopConditionChecker.check_approval_required(task2)
        assert result2.is_blocked is False

    def test_check_production_mode_helper(self):
        """Test production_ready helper method."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            production_ready=True,
        )

        result = StopConditionChecker.check_production_mode(task)
        assert result.is_blocked is True

        task2 = Task(
            id="task-2",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-2",
            production_ready=False,
        )

        result2 = StopConditionChecker.check_production_mode(task2)
        assert result2.is_blocked is False

    def test_multiple_blockers(self):
        """Test that multiple blockers are collected."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="",  # Empty action = ambiguous
            idempotency_key="key-1",
            production_ready=True,  # Production = deferred
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "ambiguous_target" in result.blockers
        assert "approval_engine_deferred" in result.blockers
        assert len(result.blockers) >= 2
