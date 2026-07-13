"""Tests for the Phase 2D batching."""

import sqlite3
from datetime import datetime
from typing import Any, Dict, List

import pytest
import yaml

from workflow_scheduler.adapters import NoopAdapter, TaskAdapter
from workflow_scheduler.cli import WorkflowSchedulerCLI, _compute_batch_rollup
from workflow_scheduler.models import Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


class OrderRecordingAdapter(TaskAdapter):
    """Test double: always succeeds, records dispatch order."""

    def __init__(self):
        self.order: List[str] = []

    def execute(self, task: Task) -> Dict[str, Any]:
        self.order.append(task.id)
        return {"success": True, "error": None, "output": {"task_id": task.id}}


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


class TestBatchValidation:
    """Creation-time batch dependency validation."""

    def test_direct_dependency_inside_same_batch_is_rejected(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A"),
            _task_def("task-2", batch_id="batch-A", depends_on=["task-1"]),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-direct", tasks)

        result = cli.create_workflow(yaml_path)

        assert result["status"] == "fail"
        assert "batch_spans_dependency" in result["checks_failed"]

    def test_transitive_dependency_inside_same_batch_is_rejected(self, tmp_path):
        """task-3 transitively depends on task-1 via a non-batch
        intermediary (task-2); both task-1 and task-3 are in batch-A."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A"),
            _task_def("task-2", depends_on=["task-1"]),  # not in any batch
            _task_def("task-3", batch_id="batch-A", depends_on=["task-2"]),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-transitive", tasks)

        result = cli.create_workflow(yaml_path)

        assert result["status"] == "fail"
        assert "batch_spans_dependency" in result["checks_failed"]

    def test_sibling_batch_with_no_dependency_relationship_is_accepted(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A"),
            _task_def("task-2", batch_id="batch-A"),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-valid", tasks)

        result = cli.create_workflow(yaml_path)

        assert result["status"] == "pass"

    def test_failed_batch_validation_leaves_no_partial_writes(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A"),
            _task_def("task-2", batch_id="batch-A", depends_on=["task-1"]),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-partial", tasks)

        result = cli.create_workflow(yaml_path)
        assert result["status"] == "fail"

        assert cli.repository.get_workflow("wf-partial") is None
        assert cli.repository.get_task("task-1") is None
        assert cli.repository.get_task("task-2") is None
        assert cli.repository.list_workflow_tasks("wf-partial") == []

    def test_batch_with_single_member_is_allowed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [_task_def("task-1", batch_id="batch-solo")]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-solo", tasks)

        result = cli.create_workflow(yaml_path)

        assert result["status"] == "pass"

    def test_no_batch_ids_skips_validation_entirely(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1"),
            _task_def("task-2", depends_on=["task-1"]),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-none", tasks)

        result = cli.create_workflow(yaml_path)

        assert result["status"] == "pass"


class TestBatchIdPersistence:
    """SQLite persistence and legacy-DB migration for batch_id."""

    @pytest.fixture
    def repository(self):
        return SQLiteRepository(":memory:")

    def _make_task(self, task_id="task-1", **overrides):
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

    def test_create_and_get_task_persists_batch_id(self, repository):
        task = self._make_task(batch_id="batch-A")
        repository.create_task(task)

        retrieved = repository.get_task(task.id)

        assert retrieved.batch_id == "batch-A"

    def test_get_task_batch_id_defaults_to_none(self, repository):
        task = self._make_task()
        repository.create_task(task)

        retrieved = repository.get_task(task.id)

        assert retrieved.batch_id is None

    def test_list_workflow_tasks_includes_batch_id(self, repository):
        task = self._make_task(batch_id="batch-B")
        repository.create_task(task)

        tasks = repository.list_workflow_tasks("workflow-1")

        assert tasks[0].batch_id == "batch-B"

    def test_update_task_persists_batch_id(self, repository):
        task = self._make_task()
        repository.create_task(task)

        task.batch_id = "batch-C"
        repository.update_task(task)

        retrieved = repository.get_task(task.id)
        assert retrieved.batch_id == "batch-C"

    def test_legacy_db_without_batch_id_column_is_migrated(self, tmp_path):
        """A DB created before Phase 2D (no batch_id column) must be
        auto-migrated on open, not require manual intervention."""
        db_path = str(tmp_path / "legacy.db")

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
                updated_at TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at TEXT,
                max_retries INTEGER NOT NULL DEFAULT 3,
                paused_from_status TEXT
            )
            """
        )
        conn.commit()
        conn.close()

        repo = SQLiteRepository(db_path)

        task = self._make_task(batch_id="batch-A")
        repo.create_task(task)
        retrieved = repo.get_task(task.id)

        assert retrieved.batch_id == "batch-A"


class TestNoBatchBackwardCompatibility:
    """Workflows with no batch_id must dispatch in exactly pre-2D order."""

    def test_ungrouped_tasks_dispatch_in_original_ready_list_order(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = OrderRecordingAdapter()
        cli.executor.adapter = adapter

        tasks = [
            _task_def("task-1", priority=3),
            _task_def("task-2", priority=2),
            _task_def("task-3", priority=1),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-order", tasks)
        cli.create_workflow(yaml_path)

        result = cli.run_workflow("wf-order")

        assert result["status"] == "pass"
        assert adapter.order == ["task-1", "task-2", "task-3"]


class TestBatchDispatchOrdering:
    """Batch members dispatch sequentially, in deterministic, grouped order."""

    def test_batch_members_grouped_contiguously_first_seen_order(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        adapter = OrderRecordingAdapter()
        cli.executor.adapter = adapter

        # Ready-list order (by priority desc): task-1, task-2, task-3, task-4
        # task-2 and task-4 share batch-A -> grouped at task-2's position.
        tasks = [
            _task_def("task-1", priority=4),
            _task_def("task-2", priority=3, batch_id="batch-A"),
            _task_def("task-3", priority=2),
            _task_def("task-4", priority=1, batch_id="batch-A"),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-batch-order", tasks)
        cli.create_workflow(yaml_path)

        result = cli.run_workflow("wf-batch-order")

        assert result["status"] == "pass"
        assert adapter.order == ["task-1", "task-2", "task-4", "task-3"]

    def test_no_adapter_interface_change(self):
        """Batching dispatches through the existing single-task execute()
        path only — no execute_batch method exists on the adapter."""
        assert not hasattr(TaskAdapter, "execute_batch")
        assert not hasattr(NoopAdapter, "execute_batch")


class TestBatchSiblingContinuation:
    """A blocked/resumable batch member must not halt sibling dispatch."""

    def test_sibling_still_executes_after_member_becomes_approval_pending(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-blocked", batch_id="batch-A", approval_required=True, priority=2),
            _task_def("task-sibling", batch_id="batch-A", priority=1),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-sibling", tasks)
        cli.create_workflow(yaml_path)

        cli.run_workflow("wf-sibling")

        assert cli.repository.get_task("task-blocked").status == TaskStatus.APPROVAL_PENDING
        assert cli.repository.get_task("task-sibling").status == TaskStatus.COMPLETED

    def test_batching_is_not_transactional_no_auto_action_on_siblings(self, tmp_path):
        """Batch membership must never auto-cancel/pause/approve/retry a
        sibling because another member blocked."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-blocked", batch_id="batch-A", approval_required=True, priority=2),
            _task_def("task-sibling", batch_id="batch-A", priority=1),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-no-auto", tasks)
        cli.create_workflow(yaml_path)

        cli.run_workflow("wf-no-auto")

        # The sibling completed on its own — nothing paused/cancelled it,
        # and the blocked task wasn't auto-approved.
        assert cli.repository.get_task("task-sibling").status == TaskStatus.COMPLETED
        assert cli.repository.get_task("task-blocked").status == TaskStatus.APPROVAL_PENDING
        assert cli.repository.get_approval_request("task-blocked").decision.value == "pending"


class TestBatchRollupStatus:
    """_compute_batch_rollup and end-to-end rollup correctness."""

    def test_rollup_all_completed(self):
        assert _compute_batch_rollup([TaskStatus.COMPLETED, TaskStatus.COMPLETED]) == "completed"

    def test_rollup_any_failed_wins_over_completed(self):
        assert _compute_batch_rollup([TaskStatus.FAILED, TaskStatus.COMPLETED]) == "failed"

    def test_rollup_governance_blocked_counts_as_failed(self):
        assert _compute_batch_rollup([TaskStatus.GOVERNANCE_BLOCKED, TaskStatus.COMPLETED]) == "failed"

    def test_rollup_cancelled_counts_as_failed(self):
        assert _compute_batch_rollup([TaskStatus.CANCELLED, TaskStatus.COMPLETED]) == "failed"

    def test_rollup_mixed_resumable_is_partial(self):
        assert _compute_batch_rollup([TaskStatus.APPROVAL_PENDING, TaskStatus.COMPLETED]) == "partial"

    def test_rollup_all_not_started(self):
        assert _compute_batch_rollup([TaskStatus.DRAFT, TaskStatus.DRAFT]) == "not_started"

    def test_rollup_mixed_completed_and_not_attempted_is_partial(self):
        assert _compute_batch_rollup([TaskStatus.COMPLETED, TaskStatus.DRAFT]) == "partial"

    def test_end_to_end_rollup_all_completed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A"),
            _task_def("task-2", batch_id="batch-A"),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-rollup-complete", tasks)
        cli.create_workflow(yaml_path)
        cli.run_workflow("wf-rollup-complete")

        status = cli.get_workflow_status("wf-rollup-complete")
        assert status["batch_statuses"]["batch-A"]["status"] == "completed"
        assert set(status["batch_statuses"]["batch-A"]["task_ids"]) == {"task-1", "task-2"}

    def test_end_to_end_rollup_failed_beats_completed(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-bad", batch_id="batch-A", action=""),  # ambiguous_target
            _task_def("task-good", batch_id="batch-A"),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-rollup-failed", tasks)
        cli.create_workflow(yaml_path)
        cli.run_workflow("wf-rollup-failed")

        status = cli.get_workflow_status("wf-rollup-failed")
        assert status["batch_statuses"]["batch-A"]["status"] == "failed"

    def test_end_to_end_rollup_partial_with_approval_pending(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-blocked", batch_id="batch-A", approval_required=True),
            _task_def("task-done", batch_id="batch-A"),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-rollup-partial", tasks)
        cli.create_workflow(yaml_path)
        cli.run_workflow("wf-rollup-partial")

        status = cli.get_workflow_status("wf-rollup-partial")
        assert status["batch_statuses"]["batch-A"]["status"] == "partial"

    def test_end_to_end_rollup_not_started_before_any_run(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A"),
            _task_def("task-2", batch_id="batch-A"),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-rollup-not-started", tasks)
        cli.create_workflow(yaml_path)

        status = cli.get_workflow_status("wf-rollup-not-started")

        assert status["batch_statuses"]["batch-A"]["status"] == "not_started"

    def test_end_to_end_rollup_partial_when_one_member_not_yet_ready(self, tmp_path):
        """task-2 (batch-A) depends on an unrelated, unbatched task-3 that
        hasn't completed; task-1 (batch-A, no deps) completes on its own."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A", priority=2),
            _task_def("task-2", batch_id="batch-A", depends_on=["task-3"], priority=1),
            _task_def("task-3", approval_required=True),  # never completes this run
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-rollup-waiting", tasks)
        cli.create_workflow(yaml_path)
        cli.run_workflow("wf-rollup-waiting")

        assert cli.repository.get_task("task-1").status == TaskStatus.COMPLETED
        assert cli.repository.get_task("task-2").status == TaskStatus.DRAFT

        status = cli.get_workflow_status("wf-rollup-waiting")
        assert status["batch_statuses"]["batch-A"]["status"] == "partial"


class TestBatchStatusOutput:
    """status command surfaces batch_statuses for non-batched workflows too."""

    def test_status_output_has_empty_batch_statuses_when_no_batches(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [_task_def("task-1")]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-no-batches", tasks)
        cli.create_workflow(yaml_path)

        status = cli.get_workflow_status("wf-no-batches")

        assert status["batch_statuses"] == {}


class TestFullRegressionWithBatching:
    """Confirm batching code paths coexist correctly with approval/retry/
    lifecycle features from 2A-2C."""

    def test_batch_member_pause_does_not_affect_sibling(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A"),
            _task_def("task-2", batch_id="batch-A"),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-pause-sibling", tasks)
        cli.create_workflow(yaml_path)

        cli.pause_task("task-1")
        result = cli.run_workflow("wf-pause-sibling")

        assert cli.repository.get_task("task-1").status == TaskStatus.PAUSED
        assert cli.repository.get_task("task-2").status == TaskStatus.COMPLETED
        assert result["status"] == "blocked"
        assert "tasks_paused" in result["blockers"]

    def test_batch_member_cancel_does_not_affect_sibling(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        tasks = [
            _task_def("task-1", batch_id="batch-A"),
            _task_def("task-2", batch_id="batch-A"),
        ]
        yaml_path = _write_workflow_yaml(tmp_path, "wf-cancel-sibling", tasks)
        cli.create_workflow(yaml_path)

        cli.cancel_task("task-1", reason="not needed")
        workflow = cli.repository.get_workflow("wf-cancel-sibling")
        workflow.mark_running()
        cli.repository.update_workflow(workflow)

        cli.run_workflow("wf-cancel-sibling")

        assert cli.repository.get_task("task-1").status == TaskStatus.CANCELLED
        assert cli.repository.get_task("task-2").status == TaskStatus.COMPLETED
