"""Executor API regressions against real durable claims and isolated adapters."""

from dataclasses import replace
from datetime import timedelta
import json
import sqlite3

import pytest

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution import Executor
from workflow_scheduler.execution.executor import ExecutionResult
from workflow_scheduler.governance import StopConditionChecker
from workflow_scheduler.models import ApprovalDecision, ApprovalRequest, Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


class Adapter(TaskAdapter):
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, task):
        self.calls.append(task)
        return self.result(task) if callable(self.result) else self.result


class ObservedRepository(SQLiteRepository):
    """Record the row seen by each public audit/claim/settlement operation."""

    def __init__(self, path):
        super().__init__(path)
        self.claims = []
        self.settlements = []
        self.events = []
        self.unclaimed_writes = []

    def try_claim_execution(self, task_id, **options):
        token = super().try_claim_execution(task_id, **options)
        self.claims.append((task_id, token))
        return token

    def update_claimed_task(self, task, token, *, approval_request=None):
        self.settlements.append((task.id, token, task.status))
        return super().update_claimed_task(task, token, approval_request=approval_request)

    def update_task(self, task, **options):
        self.unclaimed_writes.append(task.status)
        return super().update_task(task, **options)

    def log_event(self, *, event_type, task_id=None, workflow_id=None, details=None):
        row = self.get_task(task_id) if task_id else None
        self.events.append((event_type, row.status if row else None))
        return super().log_event(event_type=event_type, task_id=task_id,
                                 workflow_id=workflow_id, details=details)


@pytest.fixture
def open_repo(tmp_path):
    repos = []

    def open_one(kind=ObservedRepository):
        repo = kind(str(tmp_path / "scheduler.sqlite"))
        repos.append(repo)
        return repo

    yield open_one
    for repo in reversed(repos):
        repo.close()


def task_for(repo, task_id="task", **kwargs):
    task = Task(id=task_id, workflow_id="workflow", type="test", owner="owner",
                action="read:test", idempotency_key=task_id, **kwargs)
    repo.create_task(task)
    return task


def run_with(repo, task, raw):
    adapter = Adapter(raw)
    result = Executor(adapter, repo, AuditLogger(repo)).execute(task)
    return result, adapter


SUCCESS = {"success": True, "output": {"value": 1}}
CONTRACT_SUCCESS = {"status": "success", "message": "ok", "output": {"value": 1}}
FAILURE = {"success": False, "error": "failed"}
CONTRACT_FAILURE = {"status": "failure", "message": "failed"}
BLOCKED = {"status": "blocked", "message": "denied", "blocked_reason": "policy"}
RETRY = {"status": "retryable", "message": "later", "retry_after": 3}
DEFERRAL = {"status": "approval-required", "message": "review", "approval_reason": "review this"}


@pytest.mark.parametrize("raw", [
    pytest.param(None, id="null"),
    pytest.param({}, id="empty"),
    pytest.param([], id="non-object"),
    pytest.param({"success": 1}, id="one"),
    pytest.param({"success": 0}, id="zero"),
    pytest.param({"status": [] ,"message": "no"}, id="unhashable-status"),
    pytest.param({"status": "success", "message": ""}, id="empty-message"),
    pytest.param({"status": "success", "message": " "}, id="blank-message"),
    pytest.param({"status": "success", "message": None}, id="null-message"),
    pytest.param({"status": "success"}, id="missing-message"),
    pytest.param(dict(RETRY, retry_after=float("nan")), id="nan"),
    pytest.param(dict(RETRY, retry_after=float("inf")), id="infinity"),
    pytest.param(dict(RETRY, retry_after=10**1000), id="overflow"),
    pytest.param(dict(RETRY, retry_after=None), id="null-delay"),
    pytest.param(dict(RETRY, retry_after=True), id="boolean-delay"),
    pytest.param(dict(SUCCESS, output=[]), id="legacy-output-list"),
    pytest.param(dict(CONTRACT_SUCCESS, output=42), id="contract-output-number"),
    pytest.param(dict(SUCCESS, output={"bad": object()}), id="unserializable-output"),
    pytest.param(dict(SUCCESS, output={"bad": float("nan")}), id="nonfinite-output"),
    pytest.param(dict(SUCCESS, error="not-success"), id="legacy-success-error"),
    pytest.param(dict(CONTRACT_SUCCESS, error="not-success"), id="contract-success-error"),
    pytest.param(dict(SUCCESS, is_transient=True), id="legacy-success-transient"),
    pytest.param(dict(CONTRACT_SUCCESS, is_transient=True), id="contract-success-transient"),
    pytest.param(dict(BLOCKED, blocked_reason=""), id="empty-block-reason"),
    pytest.param(dict(DEFERRAL, approval_reason=None), id="null-approval-reason"),
])
def test_invalid_result_is_a_durable_failure_not_pass(open_repo, raw):
    repo = open_repo()
    result, adapter = run_with(repo, task_for(repo), raw)
    assert result.status == "fail"
    assert result.success is False and result.checks_failed == ["adapter_result_invalid"]
    assert result.output is None and not result.is_transient
    row = repo.get_task("task")
    assert row.status is TaskStatus.FAILED and row.lease_lock is None
    assert row.payload["error"] == result.error
    assert len(adapter.calls) == len(repo.claims) == len(repo.settlements) == 1
    assert ("adapter_result_invalid", TaskStatus.FAILED) in repo.events
    assert not any(name == "task_completed" for name, _ in repo.events)


@pytest.mark.parametrize("raw,status", [
    ({"success": False}, "fail"),
    ({"success": True, "error": None, "is_transient": False}, "pass"),
    ({"success": True, "status": "legacy metadata", "output": {}}, "pass"),
    ({"success": False, "status": "success", "message": "ignored legacy metadata"}, "fail"),
])
def test_documented_legacy_shape_does_not_switch_on_extra_status(open_repo, raw, status):
    repo = open_repo()
    result, _ = run_with(repo, task_for(repo), raw)
    assert result.status == status
    assert result.checks_failed == (["execution"] if status == "fail" else [])
    assert repo.get_task("task").status is (TaskStatus.COMPLETED if status == "pass" else TaskStatus.FAILED)


def test_result_never_defaults_failure_to_pass_or_aliases_metadata():
    lists = [["block"], ["pass-check"], ["fail-check"]]
    output = {"data": ["original"]}
    result = ExecutionResult(False, "reason", output, blockers=lists[0],
                             checks_passed=lists[1], checks_failed=lists[2])
    for values in lists:
        values.clear()
    output["data"].append("later")
    peer = ExecutionResult(True, None, None)
    assert result.status == "fail" and peer.status == "pass"
    assert (result.blockers, result.checks_passed, result.checks_failed) == (
        ["block"], ["pass-check"], ["fail-check"])
    assert result.output == {"data": ["original"]}
    assert peer.blockers == peer.checks_failed == peer.checks_passed == []


@pytest.mark.parametrize("raw, event, status", [
    (SUCCESS, "task_completed", TaskStatus.COMPLETED),
    (CONTRACT_SUCCESS, "task_completed", TaskStatus.COMPLETED),
    (FAILURE, "task_failed", TaskStatus.FAILED),
    (CONTRACT_FAILURE, "task_failed", TaskStatus.FAILED),
    (BLOCKED, "governance_blocked", TaskStatus.GOVERNANCE_BLOCKED),
    (RETRY, "retry_scheduled", TaskStatus.RETRY_SCHEDULED),
    (DEFERRAL, "approval_requested", TaskStatus.APPROVAL_PENDING),
])
def test_audit_reads_committed_transition(open_repo, raw, event, status):
    repo = open_repo()
    caller = task_for(repo)
    result, _ = run_with(repo, caller, raw)
    assert result.success is (status is TaskStatus.COMPLETED)
    readback = repo.get_task(caller.id)
    assert caller.status is readback.status is status
    assert caller.lease_lock is readback.lease_lock is None
    assert [pair for pair in repo.events if pair[0] == event] == [(event, status)]
    assert len(repo.settlements) == 1


@pytest.mark.parametrize("receipt", [False, 1, None, "raise"])
@pytest.mark.parametrize("raw", [SUCCESS, CONTRACT_SUCCESS, FAILURE, CONTRACT_FAILURE,
                                  BLOCKED, RETRY, DEFERRAL, None])
def test_unproven_settlement_keeps_fence_and_has_no_outcome_audit(open_repo, receipt, raw):
    class Refusing(ObservedRepository):
        def update_claimed_task(self, task, token, *, approval_request=None):
            self.settlements.append((task.id, token, task.status))
            if receipt == "raise":
                raise sqlite3.OperationalError("synthetic-private-diagnostic")
            return receipt

    repo = open_repo(Refusing)
    caller = task_for(repo)
    result, adapter = run_with(repo, caller, raw)
    assert result.status == "blocked" and result.success is False
    assert result.blockers == result.checks_failed == ["task_state_conflict"]
    assert "synthetic-private-diagnostic" not in result.error
    durable = repo.get_task(caller.id)
    assert caller.status is durable.status is TaskStatus.RUNNING
    assert durable.lease_lock is not None and caller.lease_lock == durable.lease_lock
    assert durable.payload == caller.payload == {}
    assert repo.events == [("governance_check_passed", TaskStatus.DRAFT)]
    assert repo.get_approval_request(caller.id) is None
    assert len(adapter.calls) == len(repo.claims) == len(repo.settlements) == 1
    assert repo.claims[0][1] == repo.settlements[0][1]
    peer = open_repo()
    competing = peer.try_claim_execution(caller.id)
    assert competing is None


def test_missing_claim_readback_blocks_without_dispatch_or_unsafe_release(open_repo):
    class MissingReadback(ObservedRepository):
        def get_task(self, task_id):
            if self.claims:
                return None
            return super().get_task(task_id)

    repo = open_repo(MissingReadback)
    caller = task_for(repo)
    result, adapter = run_with(repo, caller, SUCCESS)
    assert result.status == "blocked" and result.blockers == ["task_state_conflict"]
    assert not adapter.calls and not repo.settlements
    assert len(repo.claims) == 1 and repo.claims[0][1]
    peer = open_repo()
    held = peer.get_task(caller.id)
    assert held.status is TaskStatus.RUNNING and held.lease_lock is not None


def test_claim_uses_durable_fields_and_detaches_adapter_input(open_repo):
    repo = open_repo()
    original = task_for(repo, payload={"items": ["durable"]}, depends_on=["other"], priority=9,
                        retry_count=1, max_retries=2, batch_id="B")
    stale = replace(original, payload={"items": ["caller"]}, priority=10, depends_on=["caller"])
    seen = []

    def inspect_adapter(given):
        row = repo.get_task(given.id)
        seen.append((given.updated_at, given.lease_lock, row.updated_at, row.lease_lock))
        assert given == row
        assert given.payload == {"items": ["durable"]}
        given.payload["items"].append("adapter-only")
        given.depends_on.append("adapter-only")
        given.mark_failed("adapter should not control scheduler state")
        return SUCCESS

    result, adapter = run_with(repo, stale, inspect_adapter)
    assert result.status == "pass" and len(adapter.calls) == 1
    assert len(seen) == 1 and seen[0][0:2] == seen[0][2:4] and seen[0][1] is not None
    saved = repo.get_task(stale.id)
    assert saved.status is TaskStatus.COMPLETED
    assert saved.payload == {"items": ["durable"], "result": {"value": 1}}
    assert saved.depends_on == ["other"] and saved.priority == 9


def test_durable_approval_flag_cannot_be_bypassed_by_local_task(open_repo):
    repo = open_repo()
    real = task_for(repo, approval_required=True)
    result, adapter = run_with(repo, replace(real, approval_required=False), SUCCESS)
    assert result.status == "blocked" and result.blockers == ["approval_engine_deferred"]
    assert not adapter.calls and not repo.claims
    assert repo.get_approval_request(real.id).decision is ApprovalDecision.PENDING


def test_stale_or_wrong_task_identity_never_reaches_adapter(open_repo):
    repo = open_repo()
    original = task_for(repo)
    forged = replace(original, workflow_id="wrong-workflow")
    result, adapter = run_with(repo, forged, SUCCESS)
    assert result.status == "blocked" and result.blockers == ["task_state_conflict"]
    assert not adapter.calls and not repo.claims
    assert repo.get_task(original.id).status is TaskStatus.DRAFT


def test_reentrant_execute_cannot_reacquire_live_claim(open_repo):
    repo = open_repo()
    caller = task_for(repo)
    nested = []

    def respond(_):
        nested.append(executor.execute(repo.get_task(caller.id)))
        return SUCCESS

    adapter = Adapter(respond)
    executor = Executor(adapter, repo, AuditLogger(repo))
    result = executor.execute(caller)
    assert result.success is True
    assert len(nested) == 1 and nested[0].checks_failed == ["lease_acquisition"]
    assert len(adapter.calls) == len(repo.claims) == len(repo.settlements) == 1
    assert repo.claims[0][1] and repo.claims[0][1] == repo.settlements[0][1]


@pytest.mark.parametrize("prior", list(ApprovalDecision))
def test_adapter_deferral_never_reuses_or_replaces_prior_approval(open_repo, prior):
    repo = open_repo()
    task = task_for(repo)
    old = ApprovalRequest(id="old", task_id=task.id, requested_by=task.owner,
                          reason="prior exact request", decision=prior)
    repo.create_approval_request(old)
    result, adapter = run_with(repo, task, DEFERRAL)
    assert result.status == "blocked" and result.blockers == ["adapter_approval_repeated"]
    assert len(adapter.calls) == 1 and repo.get_approval_request(task.id) == old
    row = repo.get_task(task.id)
    assert row.status is TaskStatus.GOVERNANCE_BLOCKED and row.lease_lock is None
    assert ("governance_blocked", TaskStatus.GOVERNANCE_BLOCKED) in repo.events
    assert not any(event == "approval_requested" for event, _ in repo.events)


def test_rejected_cancelled_task_preserves_terminal_state(open_repo):
    repo = open_repo()
    task = task_for(repo, approval_required=True)
    task.mark_cancelled("review rejected")
    wrote = repo.update_task(task)
    assert wrote
    repo.create_approval_request(ApprovalRequest(id="decision", task_id=task.id, requested_by="owner",
                                                 decision=ApprovalDecision.REJECTED))
    result, adapter = run_with(repo, task, SUCCESS)
    assert result.status == "blocked" and result.success is False
    assert task.status is repo.get_task(task.id).status is TaskStatus.CANCELLED
    assert not adapter.calls and not repo.claims and not repo.settlements
    assert repo.events == []
    assert repo.unclaimed_writes == [TaskStatus.CANCELLED]


@pytest.mark.parametrize("count,seconds", [(0, 5), (1, 10)])
def test_legacy_retry_debits_once_and_uses_prior_count(open_repo, count, seconds):
    repo = open_repo()
    task = task_for(repo, retry_count=count)
    result, _ = run_with(repo, task, {"success": False, "error": "retry me", "is_transient": True})
    saved = repo.get_task(task.id)
    assert result.status == "retry_scheduled" and result.error == "retry me"
    assert saved.retry_count == count + 1 and saved.lease_lock is None
    assert saved.payload == {"error": "retry me"}
    # Task.schedule_retry reads the clock twice; compare the observable backoff
    # without sleeping or relying on exact scheduling latency.
    assert saved.next_retry_at <= saved.updated_at + timedelta(seconds=seconds)
    events = repo.get_audit_log(task_id=task.id)
    assert [json.loads(e["details"])["details"]["delay_seconds"]
            for e in events if e["event_type"] == "retry_scheduled"] == [seconds]
    assert len(repo.claims) == len(repo.settlements) == 1


@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.parametrize("same_object", [False, True])
def test_batch_refuses_duplicate_ids_before_any_dispatch(open_repo, workers, same_object):
    repo = open_repo()
    task = task_for(repo)
    another = task if same_object else replace(task)
    adapter = Adapter(SUCCESS)
    executor = Executor(adapter, repo, AuditLogger(repo), max_workers=workers)
    with pytest.raises(ValueError, match="duplicate task id"):
        executor.execute_many([task, another])
    assert not repo.claims and not adapter.calls
    assert repo.get_task(task.id).status is TaskStatus.DRAFT


@pytest.mark.parametrize("workers", [1, 2])
def test_batch_retains_all_ids_after_one_task_raises(open_repo, workers):
    class OneReadFailure(ObservedRepository):
        def get_task(self, task_id):
            if task_id == "bad":
                raise RuntimeError("synthetic-private-diagnostic")
            return super().get_task(task_id)

    repo = open_repo(OneReadFailure)
    bad, good = task_for(repo, "bad"), task_for(repo, "good")
    adapter = Adapter(SUCCESS)
    results = Executor(adapter, repo, AuditLogger(repo), max_workers=workers).execute_many([bad, good])
    assert set(results) == {"good", "bad"}
    assert results["good"].success is True
    assert results["bad"].status == "blocked" and results["bad"].blockers == ["executor_error"]
    assert "synthetic-private-diagnostic" not in results["bad"].error
    assert [task.id for task in adapter.calls] == ["good"]
    assert repo.get_task("good").status is TaskStatus.COMPLETED


@pytest.mark.parametrize("workers", [1, 2])
def test_empty_batch_has_no_results_or_side_effects(open_repo, workers):
    repo = open_repo()
    adapter = Adapter(SUCCESS)
    result = Executor(adapter, repo, AuditLogger(repo), max_workers=workers).execute_many([])
    assert result == {}  # zero outcomes is not an aggregate success verdict
    assert not repo.claims and not adapter.calls and not repo.events


def test_postcommit_audit_failure_cannot_report_pass(open_repo):
    class AuditFailure(ObservedRepository):
        def log_event(self, *, event_type, **kwargs):
            if event_type == "task_completed":
                raise sqlite3.OperationalError("synthetic-private-diagnostic")
            return super().log_event(event_type=event_type, **kwargs)

    repo = open_repo(AuditFailure)
    task = task_for(repo)
    result, adapter = run_with(repo, task, SUCCESS)
    assert result.success is False and result.blockers == ["audit_persistence_failed"]
    assert "synthetic-private-diagnostic" not in result.error
    saved = repo.get_task(task.id)
    assert saved.status is TaskStatus.COMPLETED and saved.lease_lock is None
    assert not any(name == "task_completed" for name, _ in repo.events)
    assert len(adapter.calls) == len(repo.settlements) == 1


@pytest.mark.parametrize("raw,event", [
    (BLOCKED, "governance_blocked"),
    (DEFERRAL, "approval_requested"),
])
def test_durable_audit_retains_real_transition_origin(open_repo, raw, event):
    repo = open_repo()
    task = task_for(repo)
    run_with(repo, task, raw)
    entries = [json.loads(e["details"]) for e in repo.get_audit_log(task_id=task.id)
               if e["event_type"] == event]
    assert len(entries) == 1
    assert entries[0]["status_before"] == "running"
    assert entries[0]["status_after"] == repo.get_task(task.id).status.value


@pytest.mark.parametrize("extra,expected", [
    (["approval_engine_deferred"], TaskStatus.APPROVAL_PENDING),
    (["ambiguous_target"], TaskStatus.GOVERNANCE_BLOCKED),
])
def test_duplicate_deferred_reason_differs_from_independent_hard_block(open_repo, monkeypatch, extra, expected):
    from workflow_scheduler.governance.stop_conditions import StopConditionResult

    def check(**_):
        return StopConditionResult(is_blocked=True,
                                   blockers=["approval_engine_deferred", *extra], reason="policy")

    monkeypatch.setattr(StopConditionChecker, "check_all_stop_conditions", check)
    repo = open_repo()
    task = task_for(repo)
    result, adapter = run_with(repo, task, SUCCESS)
    assert result.status == "blocked" and not adapter.calls and not repo.claims
    assert repo.get_task(task.id).status is expected
    assert (repo.get_approval_request(task.id) is not None) is (expected is TaskStatus.APPROVAL_PENDING)


def test_snapshot_change_during_governance_invalidates_claim(open_repo, monkeypatch):
    repo = open_repo()
    task = task_for(repo)
    check = StopConditionChecker.check_all_stop_conditions
    updates = []

    def advance(**kw):
        answer = check(**kw)
        changed = repo.get_task(task.id)
        changed.payload.update(governed_field_risk=True)
        updates.append(repo.update_task(changed))
        return answer

    monkeypatch.setattr(StopConditionChecker, "check_all_stop_conditions", advance)
    result, adapter = run_with(repo, task, SUCCESS)
    assert updates == [True]
    assert result.success is False and result.checks_failed == ["lease_acquisition"]
    assert repo.claims == [(task.id, None)]
    assert not adapter.calls and not repo.settlements
    assert repo.get_task(task.id).payload == {"governed_field_risk": True}


def test_truthy_non_string_claim_token_never_dispatches(open_repo):
    class BadToken(ObservedRepository):
        def try_claim_execution(self, task_id, **options):
            token = super().try_claim_execution(task_id, **options)
            assert token is not None
            return True

    repo = open_repo(BadToken)
    result, adapter = run_with(repo, task_for(repo), SUCCESS)
    assert result.success is False and result.checks_failed == ["lease_acquisition"]
    row = repo.get_task("task")
    assert row.status is TaskStatus.RUNNING and row.lease_lock is not None
    assert not adapter.calls and not repo.settlements


def test_adapter_output_is_snapshotted_before_durable_settlement(open_repo):
    raw = {"success": True, "output": {"items": ["initial"]}}

    class AdapterReusesOutput(ObservedRepository):
        def update_claimed_task(self, task, token, **options):
            raw["output"]["items"].append("late mutation")
            return super().update_claimed_task(task, token, **options)

    repo = open_repo(AdapterReusesOutput)
    task = task_for(repo)
    result, _ = run_with(repo, task, raw)
    events = [json.loads(e["details"]) for e in repo.get_audit_log(task_id=task.id)
              if e["event_type"] == "task_completed"]
    assert result.success is True and raw["output"]["items"] == ["initial", "late mutation"]
    assert result.output == {"items": ["initial"]}
    assert repo.get_task(task.id).payload["result"] == result.output
    assert [e["details"]["result"] for e in events] == [result.output]


def test_unhashable_status_has_bounded_validation_diagnostic(open_repo):
    repo = open_repo()
    result, _ = run_with(repo, task_for(repo), {"status": ["private"], "message": "invalid"})
    assert result.checks_failed == ["adapter_result_invalid"]
    assert result.error == "Invalid adapter result: adapter contract result 'status' must be a supported string"


def test_empty_parallel_batch_does_not_construct_worker_pool(open_repo, monkeypatch):
    import workflow_scheduler.execution.executor as executor_module

    def unexpected_pool(**_):
        pytest.fail("An empty batch must not allocate a thread pool")

    monkeypatch.setattr(executor_module, "ThreadPoolExecutor", unexpected_pool)
    repo = open_repo()
    adapter = Adapter(SUCCESS)
    result = Executor(adapter, repo, AuditLogger(repo), max_workers=2).execute_many([])
    assert result == {} and not adapter.calls and not repo.claims


@pytest.mark.parametrize("parent_state", ["paused", "cancelled", "failed", "governance_blocked"])
@pytest.mark.parametrize("after_read", [False, True], ids=["already-stopped", "stops-at-claim"])
def test_direct_execution_respects_durable_parent_state(open_repo, monkeypatch, parent_state, after_read):
    from workflow_scheduler.models import WorkflowPlan

    worker, controller = open_repo(), open_repo(SQLiteRepository)
    task = task_for(worker)
    workflow = WorkflowPlan(task.workflow_id, "Plan", "owner", tasks=[task.id])
    controller.create_workflow(workflow)
    workflow.mark_running()
    assert controller.update_workflow(workflow)

    def stop_parent():
        getattr(workflow, f"mark_{parent_state}")()
        assert controller.update_workflow(workflow)

    if after_read:
        claim = worker.try_claim_execution

        def stop_then_claim(task_id, **options):
            stop_parent()
            return claim(task_id, **options)

        monkeypatch.setattr(worker, "try_claim_execution", stop_then_claim)
    else:
        stop_parent()

    receipt, adapter = run_with(worker, task, SUCCESS)
    observed = controller.get_task(task.id)
    assert controller.get_workflow(task.workflow_id).status.value == parent_state
    assert not receipt.success and receipt.status != "pass"
    assert adapter.calls == [] and worker.claims == [(task.id, None)]
    assert observed.status is task.status and observed.lease_lock is None
    assert not any(event == "task_completed" for event, _ in worker.events)


@pytest.mark.parametrize("parent_state", ["standalone", "draft", "pending", "running"])
def test_direct_execution_preserves_legacy_runnable_parent_states(open_repo, parent_state):
    from workflow_scheduler.models import WorkflowPlan

    repo = open_repo()
    task = task_for(repo)
    if parent_state != "standalone":
        workflow = WorkflowPlan(task.workflow_id, "Plan", "owner", tasks=[task.id])
        if parent_state != "draft":
            getattr(workflow, f"mark_{parent_state}")()
        repo.create_workflow(workflow)
    receipt, adapter = run_with(repo, task, SUCCESS)
    assert receipt.success and len(adapter.calls) == 1
    observed = repo.get_task(task.id)
    assert observed.status is TaskStatus.COMPLETED and observed.lease_lock is None


def test_completed_parent_cannot_claim_a_new_task(open_repo):
    from workflow_scheduler.models import WorkflowPlan, WorkflowStatus

    repo = open_repo()
    prior = task_for(repo, task_id="prior")
    workflow = WorkflowPlan(prior.workflow_id, "Plan", "owner", tasks=[prior.id])
    repo.create_workflow(workflow)
    workflow.mark_running()
    assert repo.update_workflow(workflow)
    receipt, _ = run_with(repo, prior, SUCCESS)
    assert receipt.success
    workflow.mark_completed(completed_task_ids={prior.id})
    assert repo.update_workflow(workflow)

    extra = task_for(repo, task_id="extra")
    receipt, adapter = run_with(repo, extra, SUCCESS)
    assert repo.get_workflow(prior.workflow_id).status is WorkflowStatus.COMPLETED
    assert not receipt.success and adapter.calls == []
    assert repo.claims[-1] == (extra.id, None)
    observed = repo.get_task(extra.id)
    assert observed.status is extra.status and observed.lease_lock is None
