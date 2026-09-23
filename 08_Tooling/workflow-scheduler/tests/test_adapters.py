"""Tests for the local no-op adapter."""

from workflow_scheduler.adapters import NoopAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import Executor
from workflow_scheduler.models import Task
from workflow_scheduler.repository import SQLiteRepository


def make_task(task_id="task-1"):
    return Task(
        id=task_id,
        workflow_id="workflow-1",
        type="test",
        owner="system",
        action="test",
        idempotency_key=f"key-{task_id}",
    )


def run_adapter(adapter, task):
    repository = SQLiteRepository(":memory:")
    repository.create_task(task)
    runner = Executor(
        adapter=adapter,
        repository=repository,
        audit_logger=AuditLogger(),
        run_id="run-test",
    )
    return runner.execute(task)


class TestNoopAdapter:
    def test_returns_success(self):
        result = run_adapter(NoopAdapter(), make_task())
        assert result.success is True
        assert result.error is None
        assert result.output is not None

    def test_echoes_request_details(self):
        result = run_adapter(NoopAdapter(), make_task())
        assert result.output["task_id"] == "task-1"
        assert result.output["workflow_id"] == "workflow-1"
        assert result.output["owner"] == "system"

    def test_logging_enabled(self):
        adapter = NoopAdapter(log_output=True)
        run_adapter(adapter, make_task())
        assert len(adapter.get_execution_log()) == 1
        assert adapter.get_execution_log()[0]["task_id"] == "task-1"

    def test_logging_disabled(self):
        adapter = NoopAdapter(log_output=False)
        run_adapter(adapter, make_task())
        assert adapter.get_execution_log() == []

    def test_multiple_calls_logged(self):
        adapter = NoopAdapter(log_output=True)
        for index in range(3):
            run_adapter(adapter, make_task(f"task-{index}"))
        assert len(adapter.get_execution_log()) == 3

    def test_empty_log(self):
        log = NoopAdapter().get_execution_log()
        assert log == []
        assert isinstance(log, list)
