"""Tests for task adapters."""

import pytest

from workflow_scheduler.adapters import NoopAdapter
from workflow_scheduler.models import Task


class TestNoopAdapter:
    """Tests for NoopAdapter."""

    def test_execute_returns_success(self):
        """Test that noop adapter always returns success."""
        adapter = NoopAdapter()

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        result = adapter.execute(task)

        assert result["success"] is True
        assert result["error"] is None
        assert "output" in result

    def test_execute_echoes_task_details(self):
        """Test that noop adapter echoes task details."""
        adapter = NoopAdapter()

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test_type",
            owner="test_owner",
            action="test_action",
            idempotency_key="key-1",
        )

        result = adapter.execute(task)

        assert result["output"]["task_id"] == "task-1"
        assert result["output"]["action"] == "test_action"
        assert result["output"]["idempotency_key"] == "key-1"

    def test_execute_logging_enabled(self):
        """Test that adapter logs executions when enabled."""
        adapter = NoopAdapter(log_output=True)

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        adapter.execute(task)

        log = adapter.get_execution_log()
        assert len(log) == 1
        assert log[0]["task_id"] == "task-1"

    def test_execute_logging_disabled(self):
        """Test that adapter doesn't log when disabled."""
        adapter = NoopAdapter(log_output=False)

        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
        )

        adapter.execute(task)

        log = adapter.get_execution_log()
        assert len(log) == 0

    def test_multiple_executions_logged(self):
        """Test that multiple executions are logged."""
        adapter = NoopAdapter(log_output=True)

        for i in range(3):
            task = Task(
                id=f"task-{i}",
                workflow_id="workflow-1",
                type="test",
                owner="system",
                action="test",
                idempotency_key=f"key-{i}",
            )
            adapter.execute(task)

        log = adapter.get_execution_log()
        assert len(log) == 3

    def test_empty_execution_log(self):
        """Test getting execution log when empty."""
        adapter = NoopAdapter()

        log = adapter.get_execution_log()
        assert len(log) == 0
        assert isinstance(log, list)
