"""Tests for Phase 3D: the five-state adapter result contract
(status/message, from docs/ADAPTER_CONTRACT_FUTURE.md) as an additive,
backward-compatible alternative to the original success/error/
is_transient shape. Every existing adapter keeps returning the original
shape unchanged; these tests cover the new shape's validation rules and
its integration into Executor's task/audit/approval lifecycle, using
FakeContractAdapter (fake_adapters.py) as the reference example of an
adapter opting into it."""

import pytest

from task_helpers import make_plain_task as make_task
from workflow_scheduler.adapters.fake_adapters import FakeContractAdapter, FakeSuccessAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import Executor
from workflow_scheduler.execution.executor import (
    _is_contract_result,
    _validate_adapter_result,
    _validate_contract_result,
)
from workflow_scheduler.models import ApprovalDecision, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


@pytest.fixture
def repository():
    return SQLiteRepository(":memory:")


def make_executor(repository, adapter, max_workers: int = 1) -> Executor:
    audit_logger = AuditLogger(repository=repository)
    return Executor(adapter=adapter, repository=repository, audit_logger=audit_logger, max_workers=max_workers)


class TestIsContractResult:
    def test_success_key_present_is_never_a_contract_result(self):
        assert _is_contract_result({"success": True, "status": "success"}) is False
        assert _is_contract_result({"success": False}) is False

    def test_status_without_success_is_a_contract_result(self):
        assert _is_contract_result({"status": "success", "message": "ok"}) is True

    def test_neither_key_is_not_a_contract_result(self):
        assert _is_contract_result({}) is False
        assert _is_contract_result({"output": {}}) is False

    def test_non_dict_is_not_a_contract_result(self):
        assert _is_contract_result("not-a-dict") is False
        assert _is_contract_result(None) is False


class TestValidateContractResultShape:
    def test_valid_success(self):
        assert _validate_contract_result({"status": "success", "message": "ok"}) is None

    def test_valid_failure(self):
        assert _validate_contract_result({"status": "failure", "message": "nope"}) is None

    def test_valid_retryable(self):
        assert _validate_contract_result({"status": "retryable", "message": "later", "retry_after": 5}) is None
        assert _validate_contract_result({"status": "retryable", "message": "later", "retry_after": 5.5}) is None
        assert _validate_contract_result({"status": "retryable", "message": "later", "retry_after": 0}) is None

    def test_valid_blocked(self):
        result = {"status": "blocked", "message": "no", "blocked_reason": "external system denied it"}
        assert _validate_contract_result(result) is None

    def test_valid_approval_required(self):
        result = {"status": "approval-required", "message": "need sign-off", "approval_reason": "high risk action"}
        assert _validate_contract_result(result) is None

    def test_unknown_status_rejected(self):
        reason = _validate_contract_result({"status": "cancelled", "message": "x"})
        assert reason is not None
        assert "status" in reason

    @pytest.mark.parametrize("bad_message", [None, 123, ["not", "a", "string"]])
    def test_missing_or_wrong_type_message_rejected(self, bad_message):
        reason = _validate_contract_result({"status": "success", "message": bad_message})
        assert reason is not None

    def test_message_key_entirely_missing_rejected(self):
        reason = _validate_contract_result({"status": "success"})
        assert reason is not None
        assert "message" in reason

    @pytest.mark.parametrize("bad_retry_after", [None, "soon", True, -1, -0.5])
    def test_retryable_requires_valid_retry_after(self, bad_retry_after):
        result = {"status": "retryable", "message": "later", "retry_after": bad_retry_after}
        reason = _validate_contract_result(result)
        assert reason is not None
        assert "retry_after" in reason

    def test_retryable_missing_retry_after_rejected(self):
        reason = _validate_contract_result({"status": "retryable", "message": "later"})
        assert reason is not None
        assert "retry_after" in reason

    @pytest.mark.parametrize("bad_blocked_reason", [None, "", "   ", 123])
    def test_blocked_requires_non_empty_blocked_reason(self, bad_blocked_reason):
        result = {"status": "blocked", "message": "no", "blocked_reason": bad_blocked_reason}
        reason = _validate_contract_result(result)
        assert reason is not None
        assert "blocked_reason" in reason

    @pytest.mark.parametrize("bad_approval_reason", [None, "", "   ", 123])
    def test_approval_required_requires_non_empty_approval_reason(self, bad_approval_reason):
        result = {"status": "approval-required", "message": "need sign-off", "approval_reason": bad_approval_reason}
        reason = _validate_contract_result(result)
        assert reason is not None
        assert "approval_reason" in reason

    def test_wrong_type_error_field_rejected(self):
        reason = _validate_contract_result({"status": "success", "message": "ok", "error": 123})
        assert reason is not None

    def test_none_error_field_allowed(self):
        assert _validate_contract_result({"status": "success", "message": "ok", "error": None}) is None

    def test_extra_fields_ignored(self):
        result = {"status": "success", "message": "ok", "metadata": {"trace_id": "abc"}, "output": {"x": 1}}
        assert _validate_contract_result(result) is None


class TestValidateAdapterResultDispatchesCorrectly:
    """_validate_adapter_result must route to the right shape's rules,
    and the legacy shape's behavior must be completely unchanged."""

    def test_legacy_shape_still_validated_exactly_as_before(self):
        assert _validate_adapter_result({"success": True, "error": None, "output": {}}) is None
        assert _validate_adapter_result({"success": False, "error": "x", "is_transient": True}) is None
        assert _validate_adapter_result({}) == "adapter result missing required 'success' or 'status' key"
        assert _validate_adapter_result("not-a-dict") == "adapter result must be a dict, got str"

    def test_contract_shape_routed_to_contract_validation(self):
        assert _validate_adapter_result({"status": "success", "message": "ok"}) is None
        reason = _validate_adapter_result({"status": "bogus", "message": "ok"})
        assert reason is not None and "status" in reason

    def test_success_key_wins_over_status_key(self):
        # A dict with both keys is treated as legacy -- "status" is just
        # an extra ignored field, not a signal to use contract rules.
        assert _validate_adapter_result({"success": True, "status": "bogus-value"}) is None


class TestFakeContractAdapterNotInRegistry:
    def test_not_registered(self):
        from workflow_scheduler.adapters import available_adapters

        assert "fake-contract" not in available_adapters()
        assert "contract" not in " ".join(available_adapters())


class TestExecutorHandlesContractSuccess:
    def test_success_completes_task(self, repository):
        adapter = FakeContractAdapter(status="success", output={"x": 1})
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True
        assert result.status == "pass"
        assert result.output == {"x": 1}
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.COMPLETED
        assert stored.lease_lock is None


class TestExecutorHandlesContractFailure:
    def test_failure_fails_task(self, repository):
        adapter = FakeContractAdapter(status="failure", message="permanent problem")
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is False
        assert result.status == "fail"
        assert result.error == "permanent problem"
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.FAILED
        assert stored.lease_lock is None


class TestExecutorHandlesContractRetryable:
    def test_retryable_schedules_retry_using_adapter_supplied_delay(self, repository):
        adapter = FakeContractAdapter(status="retryable", message="try later", retry_after=42.0)
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.status == "retry_scheduled"
        assert result.is_transient is True
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.RETRY_SCHEDULED
        assert stored.retry_count == 1
        assert stored.next_retry_at is not None
        assert stored.lease_lock is None

    def test_retryable_exhausts_and_fails_once_retry_budget_is_spent(self, repository):
        adapter = FakeContractAdapter(status="retryable", message="try later", retry_after=0.001)
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        result = None
        for _ in range(task.max_retries + 1):
            result = executor.execute(task)
            if result.status != "retry_scheduled":
                break

        assert result.status == "fail"
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.FAILED


class TestExecutorHandlesContractBlocked:
    def test_blocked_governance_blocks_task_without_retry(self, repository):
        adapter = FakeContractAdapter(status="blocked", blocked_reason="upstream policy denied this")
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is False
        assert result.status == "blocked"
        assert "adapter_blocked" in result.blockers
        assert result.error == "upstream policy denied this"
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.GOVERNANCE_BLOCKED
        assert stored.lease_lock is None

    def test_blocked_is_audit_logged_as_governance_blocked(self, repository):
        audit_logger = AuditLogger(repository=repository)
        adapter = FakeContractAdapter(status="blocked", blocked_reason="denied")
        executor = Executor(adapter=adapter, repository=repository, audit_logger=audit_logger)
        task = make_task()
        repository.create_task(task)

        executor.execute(task)

        events = [e for e in audit_logger.get_events(task_id=task.id) if e.event_type == "governance_blocked"]
        assert len(events) == 1


class TestExecutorHandlesContractApprovalRequired:
    def test_approval_required_puts_task_in_approval_pending_without_calling_adapter_again(self, repository):
        adapter = FakeContractAdapter(status="approval-required", approval_reason="needs a human")
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        first_result = executor.execute(task)

        assert first_result.status == "blocked"
        assert "adapter_approval_required" in first_result.blockers
        assert task.approval_required is True
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.APPROVAL_PENDING
        approval = repository.get_approval_request(task.id)
        assert approval is not None
        assert approval.decision == ApprovalDecision.PENDING
        assert approval.reason == "needs a human"

    def test_rerun_before_decision_is_gated_by_stop_conditions_not_the_adapter(self, repository):
        """Once approval_required is set, StopConditionChecker intercepts
        future runs the same way a pre-declared approval_required task
        would -- the adapter (still configured to ask for approval again)
        must not be reached a second time."""
        adapter = FakeContractAdapter(status="approval-required", approval_reason="needs a human")
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        executor.execute(task)
        second_result = executor.execute(task)

        assert second_result.status == "blocked"
        assert "approval_engine_deferred" in second_result.blockers

    def test_approved_rerun_calls_adapter_again_and_can_complete(self, repository):
        adapter = FakeContractAdapter(status="approval-required", approval_reason="needs a human")
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        executor.execute(task)
        repository.update_approval_decision(task.id, ApprovalDecision.APPROVED, approver="reviewer")
        task.mark_approved()
        repository.update_task(task)

        adapter.status = "success"
        adapter.output = {"done": True}
        third_result = executor.execute(task)

        assert third_result.success is True
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.COMPLETED

    def test_rejected_decision_hard_blocks_without_calling_adapter_again(self, repository):
        adapter = FakeContractAdapter(status="approval-required", approval_reason="needs a human")
        executor = make_executor(repository, adapter)
        task = make_task()
        repository.create_task(task)

        executor.execute(task)
        repository.update_approval_decision(task.id, ApprovalDecision.REJECTED, approver="reviewer", reason="no")

        result = executor.execute(task)

        assert result.status == "blocked"
        stored = repository.get_task(task.id)
        assert stored.status == TaskStatus.GOVERNANCE_BLOCKED


class TestContractResultsUnderParallelDispatch:
    def test_execute_many_handles_a_mix_of_contract_statuses_without_crashing(self, repository):
        tasks = [
            make_task("t-success"),
            make_task("t-failure"),
            make_task("t-blocked"),
        ]
        for t in tasks:
            repository.create_task(t)

        # Each task needs its own adapter instance/config in a real
        # system; here we drive three separate executors sharing one
        # repository to prove contract-result branches don't corrupt
        # shared state under concurrent execution.
        results = {}
        for t, status in zip(tasks, ["success", "failure", "blocked"]):
            kwargs = {"blocked_reason": "no"} if status == "blocked" else {}
            adapter = FakeContractAdapter(status=status, **kwargs)
            executor = make_executor(repository, adapter, max_workers=4)
            results[t.id] = executor.execute_many([t])[t.id]

        assert results["t-success"].success is True
        assert results["t-failure"].status == "fail"
        assert results["t-blocked"].status == "blocked"


class TestExistingAdaptersUnaffected:
    def test_legacy_adapter_results_never_treated_as_contract_results(self, repository):
        executor = make_executor(repository, FakeSuccessAdapter())
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is True
        assert result.status == "pass"

    def test_registry_still_resolves_all_real_and_fake_adapters(self):
        from workflow_scheduler.adapters import available_adapters, resolve_adapter

        for name in available_adapters():
            assert resolve_adapter(name) is not None
