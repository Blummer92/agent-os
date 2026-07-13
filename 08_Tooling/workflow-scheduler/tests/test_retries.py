"""Tests for the Phase 2B retry manager."""

from datetime import datetime, timedelta
from typing import Any, Dict

import pytest
import yaml

from workflow_scheduler.adapters import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.execution import Executor, RetryManager
from workflow_scheduler.models import Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


class AlwaysTransientAdapter(TaskAdapter):
    """Test double: every execution fails with a transient error."""

    def __init__(self):
        self.calls = 0

    def execute(self, task: Task) -> Dict[str, Any]:
        self.calls += 1
        return {"success": False, "error": "temporary glitch", "is_transient": True}


class AlwaysPermanentAdapter(TaskAdapter):
    """Test double: every execution fails with a non-retryable error."""

    def __init__(self):
        self.calls = 0

    def execute(self, task: Task) -> Dict[str, Any]:
        self.calls += 1
        return {"success": False, "error": "validation error", "is_transient": False}


class NeverCalledAdapter(TaskAdapter):
    """Test double that fails the test if it is ever invoked."""

    def execute(self, task: Task) -> Dict[str, Any]:
        raise AssertionError("Adapter.execute() should never be called for this task")


class FlakyThenSucceedsAdapter(TaskAdapter):
    """Test double: fails transiently `fail_times`, then succeeds."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0
        self.calls_by_task: Dict[str, int] = {}

    def execute(self, task: Task) -> Dict[str, Any]:
        self.calls += 1
        self.calls_by_task[task.id] = self.calls_by_task.get(task.id, 0) + 1
        if self.calls <= self.fail_times:
            return {"success": False, "error": "temporary glitch", "is_transient": True}
        return {"success": True, "error": None, "output": {"task_id": task.id}}


@pytest.fixture
def repository():
    """Create in-memory SQLite repository for testing."""
    return SQLiteRepository(":memory:")


def make_task(task_id: str = "task-1", **overrides) -> Task:
    """Build a plain (non-governed) task suitable for retry testing."""
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


def make_executor(repository, adapter):
    audit_logger = AuditLogger(repository=repository)
    return Executor(adapter=adapter, repository=repository, audit_logger=audit_logger)


class TestRetryManagerBackoff:
    """Tests for RetryManager.compute_delay."""

    def test_compute_delay_base_case(self):
        assert RetryManager.compute_delay(0) == 5.0

    def test_compute_delay_exponential_growth(self):
        assert RetryManager.compute_delay(1) == 10.0
        assert RetryManager.compute_delay(2) == 20.0
        assert RetryManager.compute_delay(3) == 40.0

    def test_compute_delay_capped_at_max(self):
        assert RetryManager.compute_delay(10) == 300.0

    def test_compute_delay_custom_params(self):
        delay = RetryManager.compute_delay(
            retry_count=2, base_delay_seconds=1.0, multiplier=3.0, max_delay_seconds=100.0
        )
        assert delay == 9.0

    def test_compute_delay_custom_cap_applies(self):
        delay = RetryManager.compute_delay(
            retry_count=5, base_delay_seconds=10.0, multiplier=2.0, max_delay_seconds=50.0
        )
        assert delay == 50.0


class TestRetryManagerEligibility:
    """Tests for RetryManager.should_retry and is_due."""

    def test_should_retry_true_under_max(self):
        task = make_task(retry_count=1, max_retries=3)
        assert RetryManager.should_retry(task) is True

    def test_should_retry_false_at_max(self):
        task = make_task(retry_count=3, max_retries=3)
        assert RetryManager.should_retry(task) is False

    def test_should_retry_false_over_max(self):
        task = make_task(retry_count=4, max_retries=3)
        assert RetryManager.should_retry(task) is False

    def test_is_due_true_when_next_retry_at_none(self):
        task = make_task(next_retry_at=None)
        assert RetryManager.is_due(task) is True

    def test_is_due_true_when_in_past(self):
        task = make_task(next_retry_at=datetime.utcnow() - timedelta(seconds=10))
        assert RetryManager.is_due(task) is True

    def test_is_due_false_when_in_future(self):
        task = make_task(next_retry_at=datetime.utcnow() + timedelta(seconds=600))
        assert RetryManager.is_due(task) is False

    def test_is_due_with_explicit_now(self):
        next_retry_at = datetime(2026, 1, 1, 12, 0, 0)
        task = make_task(next_retry_at=next_retry_at)

        assert RetryManager.is_due(task, now=datetime(2026, 1, 1, 11, 59, 0)) is False
        assert RetryManager.is_due(task, now=datetime(2026, 1, 1, 12, 0, 1)) is True


class TestTaskScheduleRetry:
    """Tests for Task.schedule_retry."""

    def test_schedule_retry_sets_fields(self):
        task = make_task()
        before = datetime.utcnow()

        task.schedule_retry(delay_seconds=10)

        assert task.retry_count == 1
        assert task.status == TaskStatus.RETRY_SCHEDULED
        assert task.next_retry_at is not None
        assert task.next_retry_at >= before + timedelta(seconds=9)

    def test_schedule_retry_increments_across_calls(self):
        task = make_task()
        task.schedule_retry(delay_seconds=5)
        task.schedule_retry(delay_seconds=10)

        assert task.retry_count == 2


class TestExecutorRetryFlow:
    """Tests for how the executor routes transient vs permanent failures."""

    def test_transient_failure_schedules_retry(self, repository):
        adapter = AlwaysTransientAdapter()
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is False
        assert result.status == "retry_scheduled"
        assert result.is_transient is True

        stored_task = repository.get_task(task.id)
        assert stored_task.status == TaskStatus.RETRY_SCHEDULED
        assert stored_task.retry_count == 1
        assert stored_task.next_retry_at is not None
        assert stored_task.next_retry_at > datetime.utcnow()

    def test_transient_failure_exhausts_retries_then_fails(self, repository):
        adapter = AlwaysTransientAdapter()
        executor = make_executor(repository, adapter)
        task = make_task(max_retries=2)
        repository.create_task(task)

        first = executor.execute(task)
        assert first.status == "retry_scheduled"
        task = repository.get_task(task.id)
        assert task.retry_count == 1

        second = executor.execute(task)
        assert second.status == "retry_scheduled"
        task = repository.get_task(task.id)
        assert task.retry_count == 2

        third = executor.execute(task)
        assert third.status == "fail"
        assert third.is_transient is False

        final_task = repository.get_task(task.id)
        assert final_task.status == TaskStatus.FAILED
        # retry_count is not incremented further once exhausted
        assert final_task.retry_count == 2

    def test_permanent_failure_fails_immediately_no_retry(self, repository):
        adapter = AlwaysPermanentAdapter()
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.status == "fail"
        assert result.is_transient is False

        stored_task = repository.get_task(task.id)
        assert stored_task.status == TaskStatus.FAILED
        assert stored_task.retry_count == 0
        assert stored_task.next_retry_at is None
        assert adapter.calls == 1

    def test_flaky_adapter_eventually_succeeds(self, repository):
        adapter = FlakyThenSucceedsAdapter(fail_times=2)
        executor = make_executor(repository, adapter)
        task = make_task(max_retries=3)
        repository.create_task(task)

        first = executor.execute(task)
        assert first.status == "retry_scheduled"

        task = repository.get_task(task.id)
        second = executor.execute(task)
        assert second.status == "retry_scheduled"

        task = repository.get_task(task.id)
        third = executor.execute(task)
        assert third.success is True

        final_task = repository.get_task(task.id)
        assert final_task.status == TaskStatus.COMPLETED


class TestGovernanceNeverRetries:
    """Regression coverage: governance/approval blocks must never reach the
    adapter and must never become RETRY_SCHEDULED, regardless of what a
    (hypothetical) adapter would have returned."""

    def test_governance_blocked_never_calls_adapter(self, repository):
        adapter = NeverCalledAdapter()
        executor = make_executor(repository, adapter)
        task = make_task(action="")  # ambiguous_target — hard governance block
        repository.create_task(task)

        result = executor.execute(task)

        assert result.status == "blocked"
        assert "ambiguous_target" in result.blockers

    def test_governance_blocked_never_becomes_retry_scheduled(self, repository):
        adapter = NeverCalledAdapter()
        executor = make_executor(repository, adapter)
        task = make_task(action="")
        repository.create_task(task)

        executor.execute(task)

        stored_task = repository.get_task(task.id)
        assert stored_task.status == TaskStatus.GOVERNANCE_BLOCKED
        assert stored_task.retry_count == 0
        assert stored_task.next_retry_at is None

    def test_approval_pending_never_calls_adapter(self, repository):
        adapter = NeverCalledAdapter()
        executor = make_executor(repository, adapter)
        task = make_task(approval_required=True)
        repository.create_task(task)

        result = executor.execute(task)

        assert result.status == "blocked"
        assert "approval_engine_deferred" in result.blockers

    def test_approval_pending_never_becomes_retry_scheduled(self, repository):
        adapter = NeverCalledAdapter()
        executor = make_executor(repository, adapter)
        task = make_task(approval_required=True)
        repository.create_task(task)

        executor.execute(task)

        stored_task = repository.get_task(task.id)
        assert stored_task.status == TaskStatus.APPROVAL_PENDING
        assert stored_task.retry_count == 0
        assert stored_task.next_retry_at is None


class TestRepositoryRetryPersistence:
    """Tests for retry field persistence and legacy-DB migration."""

    def test_create_and_get_task_persists_retry_fields(self, repository):
        task = make_task(retry_count=2, max_retries=5)
        task.next_retry_at = datetime.utcnow() + timedelta(seconds=30)
        repository.create_task(task)

        retrieved = repository.get_task(task.id)

        assert retrieved.retry_count == 2
        assert retrieved.max_retries == 5
        assert retrieved.next_retry_at is not None

    def test_update_task_persists_retry_fields(self, repository):
        task = make_task()
        repository.create_task(task)

        task.schedule_retry(delay_seconds=15)
        repository.update_task(task)

        retrieved = repository.get_task(task.id)
        assert retrieved.status == TaskStatus.RETRY_SCHEDULED
        assert retrieved.retry_count == 1
        assert retrieved.next_retry_at is not None

    def test_list_workflow_tasks_includes_retry_fields(self, repository):
        task = make_task(retry_count=1, max_retries=4)
        repository.create_task(task)

        tasks = repository.list_workflow_tasks("workflow-1")

        assert len(tasks) == 1
        assert tasks[0].retry_count == 1
        assert tasks[0].max_retries == 4

    def test_legacy_db_without_retry_columns_is_migrated(self, tmp_path):
        """A DB created before Phase 2B (no retry columns) must be
        auto-migrated on open, not require manual intervention."""
        import sqlite3

        db_path = str(tmp_path / "legacy.db")

        # Simulate a pre-2B database: tasks table without retry columns.
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                type TEXT NOT NULL,
                owner TEXT NOT NULL,
                action TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                priority INTEGER NOT NULL,
                approval_required BOOLEAN NOT NULL,
                depends_on TEXT NOT NULL,
                payload TEXT NOT NULL,
                lease_lock TEXT,
                production_ready BOOLEAN NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        # Opening the repository against this legacy DB must migrate it.
        repo = SQLiteRepository(db_path)

        task = make_task()
        repo.create_task(task)
        retrieved = repo.get_task(task.id)

        assert retrieved.retry_count == 0
        assert retrieved.max_retries == 3
        assert retrieved.next_retry_at is None

        task.schedule_retry(delay_seconds=5)
        repo.update_task(task)
        after_retry = repo.get_task(task.id)
        assert after_retry.retry_count == 1


class TestWorkflowRetryRerun:
    """End-to-end: a workflow blocked on a not-yet-due retry must be
    resumable, not terminal, and must not redo completed work."""

    def _write_workflow_yaml(self, tmp_path, second_task=False):
        tasks = [
            {
                "id": "task-1",
                "type": "test",
                "owner": "system",
                "action": "test_action",
                "idempotency_key": "key-1",
                "priority": 1,
            }
        ]
        if second_task:
            tasks.append(
                {
                    "id": "task-2",
                    "type": "test",
                    "owner": "system",
                    "action": "test_action",
                    "idempotency_key": "key-2",
                    "depends_on": ["task-1"],
                    "priority": 0,
                }
            )

        workflow_data = {
            "workflow_id": "retry-workflow",
            "title": "Retry Workflow",
            "created_by": "test",
            "mode": "Draft",
            "tasks": tasks,
        }

        yaml_path = tmp_path / "workflow.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        return str(yaml_path)

    def test_run_schedules_retry_then_stays_resumable_while_not_due(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = AlwaysTransientAdapter()
        cli.executor.adapter = adapter

        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

        first_run = cli.run_workflow("retry-workflow")
        assert first_run["status"] == "blocked"
        assert "tasks_awaiting_retry" in first_run["blockers"]

        workflow_after_first_run = cli.repository.get_workflow("retry-workflow")
        assert not workflow_after_first_run.is_terminal()

        task = cli.repository.get_task("task-1")
        assert task.status == TaskStatus.RETRY_SCHEDULED
        assert task.next_retry_at > datetime.utcnow()

        calls_after_first_run = adapter.calls

        # Rerun before the backoff window elapses: must not re-attempt.
        second_run = cli.run_workflow("retry-workflow")
        assert second_run["status"] == "blocked"
        assert "tasks_awaiting_retry" in second_run["blockers"]
        assert adapter.calls == calls_after_first_run

    def test_run_retries_and_completes_once_due(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = FlakyThenSucceedsAdapter(fail_times=1)
        cli.executor.adapter = adapter

        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

        first_run = cli.run_workflow("retry-workflow")
        assert first_run["status"] == "blocked"

        # Simulate the backoff window having elapsed.
        task = cli.repository.get_task("task-1")
        task.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        cli.repository.update_task(task)

        second_run = cli.run_workflow("retry-workflow")

        assert second_run["status"] == "pass"
        assert second_run["completed"] == 1
        assert cli.repository.get_task("task-1").status == TaskStatus.COMPLETED

        final_workflow = cli.repository.get_workflow("retry-workflow")
        assert final_workflow.status.value == "completed"

    def test_rerun_does_not_redo_completed_dependency(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = FlakyThenSucceedsAdapter(fail_times=1)
        cli.executor.adapter = adapter

        yaml_path = self._write_workflow_yaml(tmp_path, second_task=True)
        cli.create_workflow(yaml_path)

        cli.run_workflow("retry-workflow")

        task = cli.repository.get_task("task-1")
        task.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        cli.repository.update_task(task)

        second_run = cli.run_workflow("retry-workflow")

        assert second_run["status"] == "pass"
        assert second_run["completed"] == 2
        assert cli.repository.get_task("task-1").status == TaskStatus.COMPLETED
        assert cli.repository.get_task("task-2").status == TaskStatus.COMPLETED
        # task-1: 1 initial failure + 1 successful retry = 2 calls. It must
        # not be re-executed again once completed (e.g. when task-2 runs).
        assert adapter.calls_by_task["task-1"] == 2
        assert adapter.calls_by_task["task-2"] == 1

    def test_exhausted_retries_end_workflow_terminal_failed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = AlwaysTransientAdapter()
        cli.executor.adapter = adapter

        workflow_data = {
            "workflow_id": "exhaust-workflow",
            "title": "Exhaust Workflow",
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
        yaml_path = tmp_path / "exhaust.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        cli.create_workflow(str(yaml_path))

        # max_retries defaults to 3; set retry_count to the budget itself
        # (should_retry checks retry_count < max_retries) so the very next
        # failure is correctly treated as exhausted, without a long loop.
        task = cli.repository.get_task("task-1")
        task.retry_count = task.max_retries
        task.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        task.status = TaskStatus.RETRY_SCHEDULED
        cli.repository.update_task(task)

        result = cli.run_workflow("exhaust-workflow")

        assert result["status"] == "fail"
        final_task = cli.repository.get_task("task-1")
        assert final_task.status == TaskStatus.FAILED

        final_workflow = cli.repository.get_workflow("exhaust-workflow")
        assert final_workflow.is_terminal()

        # A subsequent run is correctly refused as terminal (unchanged
        # Phase 1 behavior — exhausted retries are a real, final failure).
        rerun = cli.run_workflow("exhaust-workflow")
        assert rerun["status"] == "blocked"
        assert "workflow_terminal" in rerun["blockers"]
