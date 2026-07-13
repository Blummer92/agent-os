"""Tests for Phase 2F: adapter result validation, the fake adapter
registry, and the fake adapters themselves exercising the scheduler's
major execution flows."""

import pytest

from workflow_scheduler.adapters import (
    FakeFailureAdapter,
    FakeMalformedReturnAdapter,
    FakeNeverCalledAdapter,
    FakeRaisingAdapter,
    FakeRetryableAdapter,
    FakeSlowAdapter,
    FakeSuccessAdapter,
    NoopAdapter,
    TaskAdapter,
    available_adapters,
    resolve_adapter,
)
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import Executor
from workflow_scheduler.models import Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


def make_task(task_id: str = "task-1", **overrides) -> Task:
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


@pytest.fixture
def repository():
    return SQLiteRepository(":memory:")


class TestAdapterRegistry:
    """The local fake-adapter resolver/registry."""

    def test_resolve_noop(self):
        assert isinstance(resolve_adapter("noop"), NoopAdapter)

    @pytest.mark.parametrize(
        "name,expected_type",
        [
            ("fake-success", FakeSuccessAdapter),
            ("fake-failure", FakeFailureAdapter),
            ("fake-retryable", FakeRetryableAdapter),
            ("fake-never-called", FakeNeverCalledAdapter),
            ("fake-slow", FakeSlowAdapter),
            ("fake-malformed", FakeMalformedReturnAdapter),
            ("fake-raising", FakeRaisingAdapter),
        ],
    )
    def test_resolve_each_fake_adapter(self, name, expected_type):
        adapter = resolve_adapter(name)
        assert isinstance(adapter, expected_type)
        assert isinstance(adapter, TaskAdapter)

    def test_resolve_unknown_adapter_fails_cleanly(self):
        with pytest.raises(ValueError, match="Unknown adapter"):
            resolve_adapter("does-not-exist")

    def test_resolve_unknown_adapter_lists_available_names_in_error(self):
        with pytest.raises(ValueError, match="fake-success"):
            resolve_adapter("does-not-exist")

    def test_available_adapters_includes_noop_and_fakes(self):
        names = available_adapters()
        assert "noop" in names
        assert "fake-success" in names
        assert "fake-failure" in names
        assert "fake-retryable" in names
        assert names == sorted(names)

    def test_registry_returns_fresh_instance_each_call(self):
        a = resolve_adapter("fake-slow")
        b = resolve_adapter("fake-slow")
        assert a is not b


class TestAdapterResultValidation:
    """Executor rejects malformed/exception-raising adapter results safely."""

    def test_valid_success_result_accepted(self, repository):
        executor = make_executor(repository, FakeSuccessAdapter())
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True
        assert result.status == "pass"
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.COMPLETED

    @pytest.mark.parametrize(
        "malformed_value",
        [
            "not-a-dict",
            ["also", "not", "a", "dict"],
            None,
            42,
            {},  # missing required "success" key
            {"success": "yes"},  # wrong type for "success"
            {"success": False, "error": 12345},  # wrong type for "error"
            {"success": False, "is_transient": "sort of"},  # wrong type for "is_transient"
        ],
    )
    def test_malformed_result_rejected_cleanly(self, repository, malformed_value):
        adapter = FakeMalformedReturnAdapter(malformed_value=malformed_value)
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)  # must not raise

        assert result.success is False
        assert result.status == "fail"
        assert "adapter_result_invalid" in result.checks_failed
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.FAILED

    def test_malformed_result_is_audit_logged(self, repository):
        audit_logger = AuditLogger(repository=repository)
        executor = Executor(adapter=FakeMalformedReturnAdapter(), repository=repository, audit_logger=audit_logger)
        task = make_task()
        repository.create_task(task)

        executor.execute(task)

        events = [e for e in audit_logger.get_events(task_id=task.id) if e.event_type == "adapter_result_invalid"]
        assert len(events) == 1
        assert "adapter result must be a dict" in events[0].details["reason"]

    def test_adapter_raising_exception_does_not_crash_executor(self, repository):
        executor = make_executor(repository, FakeRaisingAdapter(RuntimeError("boom")))
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)  # must not raise

        assert result.success is False
        assert result.status == "fail"
        assert "adapter_result_invalid" in result.checks_failed
        assert "boom" in result.error
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.FAILED

    def test_adapter_raising_exception_still_releases_lease(self, repository):
        executor = make_executor(repository, FakeRaisingAdapter())
        task = make_task()
        repository.create_task(task)

        executor.execute(task)

        stored = repository.get_task(task.id)
        assert stored.lease_lock is None

    def test_raising_adapter_does_not_crash_execute_many_under_parallel_dispatch(self, repository):
        """The pre-Phase-2F risk: one task's adapter exception used to
        propagate out of execute_many's future.result() and abort
        collection of the rest of the pass's results. Confirm it no
        longer does, with max_workers > 1."""
        executor = make_executor(repository, FakeRaisingAdapter(), max_workers=4)
        tasks = [make_task(f"task-{i}") for i in range(5)]
        for t in tasks:
            repository.create_task(t)

        results = executor.execute_many(tasks)  # must not raise

        assert set(results.keys()) == {t.id for t in tasks}
        assert all(r.success is False and r.status == "fail" for r in results.values())


class TestFakeAdapterFlows:
    """Fake adapters exercising the scheduler's major execution flows."""

    def test_fake_success_completes(self, repository):
        executor = make_executor(repository, resolve_adapter("fake-success"))
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True
        assert repository.get_task(task.id).status == TaskStatus.COMPLETED

    def test_fake_failure_fails(self, repository):
        executor = make_executor(repository, resolve_adapter("fake-failure"))
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is False
        assert result.status == "fail"
        assert repository.get_task(task.id).status == TaskStatus.FAILED

    def test_fake_retryable_enters_existing_retry_flow(self, repository):
        executor = make_executor(repository, resolve_adapter("fake-retryable"))
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.status == "retry_scheduled"
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.RETRY_SCHEDULED
        assert stored.retry_count == 1
        assert stored.next_retry_at is not None

    def test_fake_approval_required_enters_existing_approval_flow(self, repository):
        """approval_required is intercepted by governance before the
        adapter is ever reached -- pairing it with FakeNeverCalledAdapter
        proves the interception, not an adapter-level return value."""
        executor = make_executor(repository, resolve_adapter("fake-never-called"))
        task = make_task(approval_required=True)
        repository.create_task(task)

        result = executor.execute(task)  # must not raise (adapter never called)

        assert result.status == "blocked"
        assert "approval_engine_deferred" in result.blockers
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.APPROVAL_PENDING
        approval = repository.get_approval_request(task.id)
        assert approval is not None

    def test_fake_blocked_enters_existing_governance_flow(self, repository):
        """Same interception principle for a hard governance block
        (ambiguous_target: empty action) -- not approval-resumable."""
        executor = make_executor(repository, resolve_adapter("fake-never-called"))
        task = make_task(action="")
        repository.create_task(task)

        result = executor.execute(task)  # must not raise (adapter never called)

        assert result.status == "blocked"
        assert "ambiguous_target" in result.blockers
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.GOVERNANCE_BLOCKED

    def test_fake_slow_adapter_works_under_max_workers_greater_than_one(self, repository):
        adapter = resolve_adapter("fake-slow")
        executor = make_executor(repository, adapter, max_workers=4)
        tasks = [make_task(f"task-{i}") for i in range(4)]
        for t in tasks:
            repository.create_task(t)

        results = executor.execute_many(tasks)

        assert all(r.success for r in results.values())
        assert adapter.max_in_flight > 1  # actually overlapped, not just accepted the flag
        assert adapter.max_in_flight <= 4

    def test_fake_slow_adapter_stays_sequential_at_default_max_workers(self, repository):
        adapter = resolve_adapter("fake-slow")
        executor = make_executor(repository, adapter)  # max_workers=1 default
        tasks = [make_task(f"task-{i}") for i in range(4)]
        for t in tasks:
            repository.create_task(t)

        executor.execute_many(tasks)

        assert adapter.max_in_flight == 1
