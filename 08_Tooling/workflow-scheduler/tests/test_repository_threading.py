"""Tests for SQLiteRepository thread-safety hardening (Phase 2E)."""

import concurrent.futures
import threading

import pytest

from workflow_scheduler.models import (
    ApprovalDecision,
    ApprovalRequest,
    Task,
    WorkflowPlan,
)
from workflow_scheduler.repository import SQLiteRepository


def _make_task(task_id: str, workflow_id: str = "workflow-1", **overrides) -> Task:
    defaults = dict(
        id=task_id,
        workflow_id=workflow_id,
        type="test",
        owner="system",
        action="test_action",
        idempotency_key=f"key-{task_id}",
    )
    defaults.update(overrides)
    return Task(**defaults)


class TestConnectionThreadSafety:
    """Direct verification of check_same_thread=False + lock discipline."""

    def test_repository_usable_from_a_different_thread_than_constructor(self, tmp_path):
        """Without check_same_thread=False this raises sqlite3.ProgrammingError."""
        repo = SQLiteRepository(str(tmp_path / "test.db"))
        errors = []

        def worker():
            try:
                workflow = WorkflowPlan(workflow_id="wf-1", title="T", created_by="tester")
                repo.create_workflow(workflow)
                assert repo.get_workflow("wf-1") is not None
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        assert errors == []

    def test_lock_is_reentrant_rlock(self):
        repo = SQLiteRepository(":memory:")
        assert isinstance(repo._lock, type(threading.RLock()))
        # RLock allows the owning thread to acquire it again without
        # deadlocking (exercised for real by update_approval_decision,
        # which calls get_approval_request while still holding the lock).
        with repo._lock:
            with repo._lock:
                pass


class TestConcurrentReadsAndWrites:
    """Concurrent same-process access across distinct rows."""

    def test_concurrent_task_creation_and_retrieval(self, tmp_path):
        repo = SQLiteRepository(str(tmp_path / "test.db"))
        num_threads = 20

        def worker(i):
            task = _make_task(f"task-{i}")
            repo.create_task(task)
            fetched = repo.get_task(f"task-{i}")
            assert fetched is not None
            assert fetched.id == f"task-{i}"
            return i

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            results = [f.result() for f in [executor.submit(worker, i) for i in range(num_threads)]]

        assert sorted(results) == list(range(num_threads))
        for i in range(num_threads):
            assert repo.get_task(f"task-{i}") is not None

    def test_concurrent_writes_to_same_row_do_not_raise(self, tmp_path):
        """Contention on the identical row: no exception/corruption,
        last-write-wins is acceptable, a crash is not."""
        repo = SQLiteRepository(str(tmp_path / "test.db"))
        workflow = WorkflowPlan(workflow_id="wf-shared", title="Shared", created_by="tester")
        repo.create_workflow(workflow)

        errors = []

        def worker(i):
            try:
                wf = repo.get_workflow("wf-shared")
                wf.metadata[f"writer_{i}"] = True
                repo.update_workflow(wf)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert repo.get_workflow("wf-shared") is not None


class TestConcurrentAuditLogging:
    def test_concurrent_audit_logging_no_lost_events(self, tmp_path):
        repo = SQLiteRepository(str(tmp_path / "test.db"))
        num_events = 30

        def worker(i):
            repo.log_event(event_type="stress", task_id=f"task-{i}", workflow_id="wf-1", details={"i": i})

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_events) as executor:
            futures = [executor.submit(worker, i) for i in range(num_events)]
            for f in futures:
                f.result()

        events = repo.get_audit_log(workflow_id="wf-1")
        assert len(events) == num_events


class TestConcurrentApprovals:
    def test_concurrent_approval_create_and_update(self, tmp_path):
        repo = SQLiteRepository(str(tmp_path / "test.db"))
        num_threads = 20

        def worker(i):
            task_id = f"task-{i}"
            approval = ApprovalRequest(id=f"approval-{i}", task_id=task_id, requested_by="tester")
            repo.create_approval_request(approval)
            updated = repo.update_approval_decision(
                task_id=task_id, decision=ApprovalDecision.APPROVED, approver="tester"
            )
            assert updated.decision == ApprovalDecision.APPROVED
            return i

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            results = [f.result() for f in [executor.submit(worker, i) for i in range(num_threads)]]

        assert sorted(results) == list(range(num_threads))
        for i in range(num_threads):
            approval = repo.get_approval_request(f"task-{i}")
            assert approval is not None
            assert approval.decision == ApprovalDecision.APPROVED


class TestSimultaneousClose:
    def test_simultaneous_close_calls_do_not_raise(self, tmp_path):
        repo = SQLiteRepository(str(tmp_path / "test.db"))
        errors = []

        def worker():
            try:
                repo.close()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert repo._connection is None

    def test_repository_usable_after_concurrent_close(self, tmp_path):
        """close() lazily recreates the connection on next use (existing
        single-threaded semantics, unchanged)."""
        repo = SQLiteRepository(str(tmp_path / "test.db"))

        threads = [threading.Thread(target=repo.close) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        workflow = WorkflowPlan(workflow_id="wf-after-close", title="T", created_by="tester")
        repo.create_workflow(workflow)
        assert repo.get_workflow("wf-after-close") is not None


class TestMixedConcurrentOperationsStress:
    """10-50 threads combining mixed read/write, audit logging, approvals,
    workflow/task updates, and concurrent close() calls."""

    def test_stress_mixed_operations_across_many_threads(self, tmp_path):
        # File-backed DB: closing and reopening the connection must not
        # lose data (unlike :memory:, where a fresh connection is a fresh
        # empty database) -- this test intentionally interleaves close().
        repo = SQLiteRepository(str(tmp_path / "stress.db"))
        num_threads = 30

        def worker(i):
            workflow_id = f"wf-{i}"
            task_id = f"task-{i}"

            workflow = WorkflowPlan(workflow_id=workflow_id, title="Stress", created_by="tester")
            repo.create_workflow(workflow)

            task = _make_task(task_id, workflow_id=workflow_id)
            repo.create_task(task)

            fetched = repo.get_task(task_id)
            assert fetched is not None and fetched.id == task_id

            # priority is set only at creation (update_task doesn't persist
            # it, by design -- it's immutable after creation like
            # type/owner/action); use payload to exercise update_task.
            fetched.payload["worker_index"] = i
            repo.update_task(fetched)

            repo.log_event(event_type="stress_test", task_id=task_id, workflow_id=workflow_id, details={"i": i})

            approval = ApprovalRequest(id=f"approval-{i}", task_id=task_id, requested_by="tester")
            repo.create_approval_request(approval)
            repo.update_approval_decision(task_id=task_id, decision=ApprovalDecision.APPROVED, approver="tester")

            fetched_workflow = repo.get_workflow(workflow_id)
            fetched_workflow.metadata["touched_by"] = i
            repo.update_workflow(fetched_workflow)

            if i % 5 == 0:
                repo.close()

            return i

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            results = [f.result() for f in futures]  # re-raises any worker exception

        assert sorted(results) == list(range(num_threads))

        for i in range(num_threads):
            task = repo.get_task(f"task-{i}")
            assert task is not None
            assert task.payload["worker_index"] == i

            approval = repo.get_approval_request(f"task-{i}")
            assert approval is not None
            assert approval.decision == ApprovalDecision.APPROVED

            events = repo.get_audit_log(task_id=f"task-{i}")
            assert len(events) == 1

            workflow = repo.get_workflow(f"wf-{i}")
            assert workflow is not None
            assert workflow.metadata["touched_by"] == i

    def test_stress_50_threads_pure_read_write_no_close(self, tmp_path):
        """Upper end of the required 10-50 thread range, no close()
        interleaving, to isolate pure read/write contention behavior."""
        repo = SQLiteRepository(str(tmp_path / "stress50.db"))
        num_threads = 50

        def worker(i):
            task = _make_task(f"task-{i}")
            repo.create_task(task)
            repo.log_event(event_type="stress50", task_id=f"task-{i}")
            return repo.get_task(f"task-{i}") is not None

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            results = [f.result() for f in [executor.submit(worker, i) for i in range(num_threads)]]

        assert all(results)
        assert len(results) == num_threads
