"""Tests for Phase 2E opt-in parallel ready-list dispatch."""

import json
import sys
import threading
import time
from typing import Any, Dict

import pytest
import yaml

from workflow_scheduler.adapters import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.cli import WorkflowSchedulerCLI, main
from workflow_scheduler.execution import Executor
from workflow_scheduler.models import Task
from workflow_scheduler.repository import SQLiteRepository


class ConcurrencyTrackingAdapter(TaskAdapter):
    """Test double: records how many executions were in flight at once,
    and each task's [start, end) window, without relying on wall-clock
    timing comparisons in assertions (only used to force overlap)."""

    def __init__(self, hold_seconds: float = 0.05):
        self.hold_seconds = hold_seconds
        self._state_lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0
        self.windows: Dict[str, tuple] = {}

    def execute(self, task: Task) -> Dict[str, Any]:
        with self._state_lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        start = time.monotonic()
        try:
            time.sleep(self.hold_seconds)
            return {"success": True, "error": None, "output": {"task_id": task.id}}
        finally:
            end = time.monotonic()
            with self._state_lock:
                self.windows[task.id] = (start, end)
                self._in_flight -= 1


class MixedResultAdapter(TaskAdapter):
    """Test double: fails for task IDs in `failing_ids`, succeeds otherwise."""

    def __init__(self, failing_ids: set):
        self.failing_ids = failing_ids

    def execute(self, task: Task) -> Dict[str, Any]:
        if task.id in self.failing_ids:
            return {"success": False, "error": "boom", "is_transient": False}
        return {"success": True, "error": None, "output": {"task_id": task.id}}


def make_task(task_id: str = "task-1", **overrides) -> Task:
    """Build a plain (non-governed) task, matching test_retries.py's convention."""
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


def make_executor(repository, adapter, max_workers: int = 1) -> Executor:
    audit_logger = AuditLogger(repository=repository)
    return Executor(adapter=adapter, repository=repository, audit_logger=audit_logger, max_workers=max_workers)


def _write_workflow_yaml(tmp_path, workflow_id, tasks, filename="workflow.yaml"):
    workflow_data = {
        "workflow_id": workflow_id,
        "title": "Test Workflow",
        "created_by": "test",
        "mode": "Draft",
        "tasks": tasks,
    }
    yaml_path = tmp_path / filename
    with open(yaml_path, "w") as f:
        yaml.dump(workflow_data, f)
    return str(yaml_path)


def _task_def(task_id, **overrides):
    defaults = {
        "id": task_id,
        "type": "test",
        "owner": "system",
        "action": "test_action",
        "idempotency_key": f"key-{task_id}",
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def repository():
    return SQLiteRepository(":memory:")


class TestExecutorMaxWorkersConfig:
    """Executor(max_workers=...) construction and validation."""

    def test_default_max_workers_is_one(self, repository):
        executor = make_executor(repository, ConcurrencyTrackingAdapter())
        assert executor.max_workers == 1

    @pytest.mark.parametrize("invalid", [0, -1, -5])
    def test_max_workers_below_one_is_rejected(self, repository, invalid):
        with pytest.raises(ValueError, match="max_workers must be >= 1"):
            make_executor(repository, ConcurrencyTrackingAdapter(), max_workers=invalid)


class TestExecuteMany:
    """Executor.execute_many() dispatch behavior."""

    def test_returns_one_result_per_task(self, repository):
        executor = make_executor(repository, ConcurrencyTrackingAdapter(hold_seconds=0), max_workers=3)
        tasks = [make_task(f"task-{i}") for i in range(5)]
        for t in tasks:
            repository.create_task(t)

        results = executor.execute_many(tasks)

        assert set(results.keys()) == {t.id for t in tasks}
        assert all(r.success for r in results.values())

    def test_sequential_when_max_workers_one(self, repository):
        adapter = ConcurrencyTrackingAdapter(hold_seconds=0.05)
        executor = make_executor(repository, adapter, max_workers=1)
        tasks = [make_task(f"task-{i}") for i in range(5)]
        for t in tasks:
            repository.create_task(t)

        executor.execute_many(tasks)

        assert adapter.max_in_flight == 1

    def test_parallelizes_when_max_workers_greater_than_one(self, repository):
        adapter = ConcurrencyTrackingAdapter(hold_seconds=0.05)
        executor = make_executor(repository, adapter, max_workers=4)
        tasks = [make_task(f"task-{i}") for i in range(4)]
        for t in tasks:
            repository.create_task(t)

        executor.execute_many(tasks)

        assert adapter.max_in_flight > 1

    def test_max_workers_bounds_concurrency(self, repository):
        adapter = ConcurrencyTrackingAdapter(hold_seconds=0.05)
        executor = make_executor(repository, adapter, max_workers=3)
        tasks = [make_task(f"task-{i}") for i in range(12)]
        for t in tasks:
            repository.create_task(t)

        executor.execute_many(tasks)

        assert 1 < adapter.max_in_flight <= 3

    def test_isolates_per_task_adapter_failures(self, repository):
        failing = {"task-1", "task-3"}
        adapter = MixedResultAdapter(failing_ids=failing)
        executor = make_executor(repository, adapter, max_workers=4)
        tasks = [make_task(f"task-{i}") for i in range(5)]
        for t in tasks:
            repository.create_task(t)

        results = executor.execute_many(tasks)

        for task_id, result in results.items():
            if task_id in failing:
                assert result.success is False
                assert result.error == "boom"
            else:
                assert result.success is True


class TestCLIMaxWorkersWiring:
    """WorkflowSchedulerCLI / main() --max-workers propagation."""

    def test_cli_constructor_propagates_max_workers_to_executor(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"), max_workers=5)
        assert cli.executor.max_workers == 5

    def test_cli_default_max_workers_is_one(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        assert cli.executor.max_workers == 1

    def test_cli_rejects_invalid_max_workers(self, tmp_path):
        with pytest.raises(ValueError, match="max_workers must be >= 1"):
            WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"), max_workers=0)

    def test_main_run_with_max_workers_flag_end_to_end(self, tmp_path, monkeypatch, capsys):
        db = str(tmp_path / "test.db")
        yaml_path = _write_workflow_yaml(
            tmp_path,
            "wf-max-workers",
            [_task_def("task-1"), _task_def("task-2")],
        )

        monkeypatch.setattr(sys, "argv", ["workflow-scheduler", "create", yaml_path, "--db", db])
        with pytest.raises(SystemExit):
            main()
        capsys.readouterr()

        monkeypatch.setattr(
            sys, "argv", ["workflow-scheduler", "run", "wf-max-workers", "--db", db, "--max-workers", "3"]
        )
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "pass"
        assert result["completed"] == 2

    def test_main_rejects_invalid_max_workers_cleanly(self, tmp_path, monkeypatch, capsys):
        db = str(tmp_path / "test.db")
        yaml_path = _write_workflow_yaml(tmp_path, "wf-bad-workers", [_task_def("task-1")])

        monkeypatch.setattr(sys, "argv", ["workflow-scheduler", "create", yaml_path, "--db", db])
        with pytest.raises(SystemExit):
            main()
        capsys.readouterr()

        monkeypatch.setattr(
            sys, "argv", ["workflow-scheduler", "run", "wf-bad-workers", "--db", db, "--max-workers", "0"]
        )
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "fail"
        assert "max_workers must be >= 1" in result["error"]


class TestRunWorkflowParallelDispatch:
    """End-to-end run_workflow() behavior with max_workers > 1."""

    def test_independent_tasks_run_concurrently_through_cli(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"), max_workers=4)
        adapter = ConcurrencyTrackingAdapter(hold_seconds=0.05)
        cli.executor.adapter = adapter

        yaml_path = _write_workflow_yaml(
            tmp_path,
            "wf-independent",
            [_task_def(f"task-{i}") for i in range(4)],
        )
        cli.create_workflow(yaml_path)

        result = cli.run_workflow("wf-independent")

        assert result["status"] == "pass"
        assert result["completed"] == 4
        assert adapter.max_in_flight > 1

    def test_dependency_chain_still_runs_in_order_with_high_max_workers(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"), max_workers=4)
        adapter = ConcurrencyTrackingAdapter(hold_seconds=0.05)
        cli.executor.adapter = adapter

        yaml_path = _write_workflow_yaml(
            tmp_path,
            "wf-chain",
            [
                _task_def("task-1"),
                _task_def("task-2", depends_on=["task-1"]),
                _task_def("task-3", depends_on=["task-2"]),
            ],
        )
        cli.create_workflow(yaml_path)

        result = cli.run_workflow("wf-chain")

        assert result["status"] == "pass"
        assert result["completed"] == 3
        # A chain has exactly one task ready per pass, so even with
        # max_workers=4 the chain itself never overlaps -- each task's
        # window must fully finish before the next one starts.
        assert adapter.windows["task-1"][1] <= adapter.windows["task-2"][0]
        assert adapter.windows["task-2"][1] <= adapter.windows["task-3"][0]

    def test_downstream_task_waits_for_sibling_dependencies_under_parallelism(self, tmp_path):
        """Two independent roots (parallelizable) both gate one downstream
        task -- the downstream task must not start until both roots finish,
        even though the roots themselves ran concurrently."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"), max_workers=4)
        adapter = ConcurrencyTrackingAdapter(hold_seconds=0.05)
        cli.executor.adapter = adapter

        yaml_path = _write_workflow_yaml(
            tmp_path,
            "wf-fanin",
            [
                _task_def("root-a"),
                _task_def("root-b"),
                _task_def("downstream", depends_on=["root-a", "root-b"]),
            ],
        )
        cli.create_workflow(yaml_path)

        result = cli.run_workflow("wf-fanin")

        assert result["status"] == "pass"
        assert result["completed"] == 3
        assert adapter.windows["root-a"][1] <= adapter.windows["downstream"][0]
        assert adapter.windows["root-b"][1] <= adapter.windows["downstream"][0]
        # The two roots were dispatched in the same pass -- prove that pass
        # actually ran them concurrently, not just "correctly ordered".
        assert adapter.max_in_flight > 1

    def test_approval_gated_task_alongside_parallel_siblings(self, tmp_path):
        """A task requiring explicit approval must still land in
        approval_pending -- never dispatched to the adapter -- even when
        max_workers > 1 and it shares a ready-pass with normal tasks."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"), max_workers=4)

        yaml_path = _write_workflow_yaml(
            tmp_path,
            "wf-approval",
            [
                _task_def("normal-1"),
                _task_def("normal-2"),
                _task_def("gated", approval_required=True),
            ],
        )
        cli.create_workflow(yaml_path)

        result = cli.run_workflow("wf-approval")

        assert result["status"] == "blocked"
        assert result["completed"] == 2
        assert result["approval_pending"] == 1
        assert "gated" in result["approval_pending_task_ids"]

    def test_failure_and_success_coexist_in_same_parallel_pass(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"), max_workers=4)
        cli.executor.adapter = MixedResultAdapter(failing_ids={"task-2"})

        yaml_path = _write_workflow_yaml(
            tmp_path,
            "wf-mixed",
            [_task_def("task-1"), _task_def("task-2"), _task_def("task-3")],
        )
        cli.create_workflow(yaml_path)

        result = cli.run_workflow("wf-mixed")

        assert result["status"] == "fail"
        assert result["completed"] == 2
        assert result["failed"] == 1
