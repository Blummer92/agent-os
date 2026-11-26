"""Public contracts for workflow and task models; no wall-clock coordination."""

from datetime import UTC, datetime, timedelta

import pytest

from workflow_scheduler.models import (
    Task,
    TaskMode,
    TaskStatus,
    WorkflowMode,
    WorkflowPlan,
    WorkflowStatus,
)


START = datetime(2026, 11, 25, 12, tzinfo=UTC)
TICK = START + timedelta(seconds=1)
TASK_TERMINALS = frozenset({
    TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
    TaskStatus.GOVERNANCE_BLOCKED,
})
PLAN_TERMINALS = frozenset({
    WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED,
    WorkflowStatus.GOVERNANCE_BLOCKED,
})


def task_model(task_id="task-1", **kwargs):
    return Task(task_id, "workflow-1", "test", "alice", "test_action", f"key:{task_id}", **kwargs)


def plan_model(**kwargs):
    return WorkflowPlan("workflow-1", "Test Workflow", "alice", created_at=START, **kwargs)


def test_task_creation_preserves_identity_and_defaults():
    task = task_model()
    assert (task.id, task.workflow_id, task.type, task.owner, task.action, task.idempotency_key) == (
        "task-1", "workflow-1", "test", "alice", "test_action", "key:task-1",
    )
    assert task.mode is TaskMode.DRAFT
    assert task.status is TaskStatus.DRAFT
    assert task.priority == 0
    assert task.approval_required is False
    assert task.production_ready is False
    assert task.lease_lock is None
    assert task.payload == {}
    assert task.depends_on == []


@pytest.mark.parametrize("mode", list(TaskMode))
def test_task_lifecycle_does_not_change_execution_mode(mode):
    task = task_model(mode=mode)
    task.mark_approved()
    assert task.status is TaskStatus.APPROVED
    assert task.mode is mode


def test_task_defaults_are_not_shared_between_instances():
    first = task_model("first")
    second = task_model("second")
    first.mark_cancelled("only first")
    first.depends_on.append("dependency")
    assert first.payload == {"cancellation_reason": "only first"}
    assert first.depends_on == ["dependency"]
    assert second.payload == {}
    assert second.depends_on == []


def test_task_owns_nested_constructor_payload_and_dependency_list():
    payload = {"config": {"keys": ["a"]}}
    dependencies = ["dependency"]
    task = task_model(payload=payload, depends_on=dependencies)
    payload["config"]["keys"].append("unowned")
    dependencies.clear()
    assert task.payload == {"config": {"keys": ["a"]}}
    assert task.depends_on == ["dependency"]


def test_task_mark_completed_detaches_nested_result_and_clears_local_lease():
    task = task_model()
    task.acquire_lease()
    assert task.status is TaskStatus.RUNNING
    assert task.lease_lock is not None
    result = {"output": ["success"]}
    task.mark_completed(result=result)
    result["output"].append("caller edit")
    assert task.status is TaskStatus.COMPLETED
    assert task.payload == {"result": {"output": ["success"]}}
    assert task.lease_lock is None


@pytest.mark.parametrize("result", [None, {}], ids=["none", "empty-output"])
def test_task_distinguishes_absent_and_empty_completed_result(result):
    task = task_model()
    task.acquire_lease()
    task.mark_completed(result=result)
    assert task.status is TaskStatus.COMPLETED
    assert task.lease_lock is None
    expected = {} if result is None else {"result": {}}
    assert task.payload == expected


@pytest.mark.parametrize(("is_transient", "status"), [
    (False, TaskStatus.FAILED), (True, TaskStatus.RETRY_SCHEDULED),
], ids=["terminal", "transient"])
def test_task_failure_records_exact_error_and_clears_local_lease(is_transient, status):
    task = task_model(retry_count=1)
    task.acquire_lease()
    task.mark_failed("Test error", is_transient=is_transient)
    assert task.status is status
    assert task.payload == {"error": "Test error"}
    assert task.lease_lock is None
    # The failure does not debit another attempt; schedule_retry does.
    assert task.retry_count == 1


def test_task_schedule_retry_debits_attempt_and_preserves_error():
    task = task_model(retry_count=1)
    task.mark_failed("Test error", is_transient=True)
    task.schedule_retry(delay_seconds=30)
    assert task.status is TaskStatus.RETRY_SCHEDULED
    assert task.retry_count == 2
    assert task.next_retry_at is not None
    assert task.payload == {"error": "Test error"}


@pytest.mark.parametrize("prior", [
    TaskStatus.DRAFT, TaskStatus.PENDING, TaskStatus.APPROVAL_PENDING, TaskStatus.APPROVED,
    TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.RETRY_SCHEDULED,
])
def test_task_pause_remembers_exact_prior_state(prior):
    # Constructor state is the public restore/bootstrap path; no live claim is set.
    task = task_model(status=prior)
    task.mark_paused()
    assert task.status is TaskStatus.PAUSED
    assert task.paused_from_status == prior.value
    assert task.lease_lock is None
    task.resume()
    assert task.status is prior
    assert task.paused_from_status is None


def test_task_duplicate_pause_does_not_lose_prior_status():
    task = task_model()
    task.mark_approved()
    task.mark_paused()
    stamp = task.updated_at
    with pytest.raises(ValueError):
        task.mark_paused()
    assert task.updated_at == stamp
    assert task.paused_from_status == TaskStatus.APPROVED.value
    task.resume()
    assert task.status is TaskStatus.APPROVED


@pytest.mark.parametrize("prior", [None, "", "unknown", "paused", "cancelled"])
def test_task_resume_refuses_untrustworthy_pause_origin(prior):
    task = task_model(status=TaskStatus.PAUSED, paused_from_status=prior)
    stamp = task.updated_at
    with pytest.raises(ValueError):
        task.resume()
    assert task.status is TaskStatus.PAUSED
    assert task.paused_from_status == prior
    assert task.updated_at == stamp


def test_task_mark_cancelled_keeps_cancellation_reason():
    task = task_model()
    task.mark_cancelled("User cancelled")
    assert task.status is TaskStatus.CANCELLED
    assert task.payload == {"cancellation_reason": "User cancelled"}
    assert task.lease_lock is None


@pytest.mark.parametrize("status", sorted(TASK_TERMINALS, key=lambda value: value.value))
@pytest.mark.parametrize(("method", "args"), [
    ("mark_approved", ()),
    ("mark_approval_pending", ()),
    ("mark_completed", ({"output": "wrong"},)),
    ("mark_failed", ("second failure",)),
    ("mark_paused", ()),
    ("resume", ()),
    ("mark_cancelled", ("second cancellation",)),
    ("acquire_lease", ()),
    ("schedule_retry", (1,)),
])
def test_task_terminal_state_rejects_transitions(status, method, args):
    task = task_model(status=status, payload={"existing": {"id": "original"}}, updated_at=START)
    assert task.is_completed() is True
    with pytest.raises(ValueError):
        getattr(task, method)(*args)
    assert task.status is status
    assert task.payload == {"existing": {"id": "original"}}
    assert task.updated_at == START
    assert task.lease_lock is None
    assert task.retry_count == 0


def test_task_duplicate_approval_is_noop():
    task = task_model(status=TaskStatus.APPROVED, updated_at=START)
    task.mark_approved()
    assert task.status is TaskStatus.APPROVED
    assert task.updated_at == START


def test_task_local_lease_acquire_release_keeps_running_status():
    task = task_model()
    assert task.lease_lock is None
    acquired = task.acquire_lease(at=START)
    assert acquired is None  # local model mutation, not a repository claim token
    assert task.lease_lock == START
    assert task.status is TaskStatus.RUNNING
    with pytest.raises(ValueError):
        task.acquire_lease(at=TICK)
    assert task.lease_lock == START
    task.release_lease()
    assert task.lease_lock is None
    assert task.status is TaskStatus.RUNNING


def test_task_release_without_local_lease_is_noop():
    task = task_model(updated_at=START)
    task.release_lease()
    assert task.lease_lock is None
    assert task.status is TaskStatus.DRAFT
    assert task.updated_at == START


@pytest.mark.parametrize(("elapsed", "expected"), [
    (timedelta(microseconds=-1), True),
    (timedelta(0), True),
    (timedelta(seconds=300, microseconds=-1), True),
    (timedelta(seconds=300), False),
    (timedelta(seconds=300, microseconds=1), False),
], ids=["future-fails-closed", "fresh", "before-expiry", "at-expiry", "after-expiry"])
def test_task_lease_expiry_at_exact_boundaries(elapsed, expected):
    task = task_model()
    task.acquire_lease(at=START)
    assert task.has_active_lease(now=START + elapsed) is expected


def test_task_lease_comparison_accepts_legacy_naive_utc():
    task = task_model(status=TaskStatus.RUNNING, lease_lock=START.replace(tzinfo=None))
    assert task.has_active_lease(timeout_seconds=2, now=TICK) is True
    assert task.has_active_lease(timeout_seconds=1, now=TICK.replace(tzinfo=None)) is False


def test_task_lease_absence_is_not_active():
    task = task_model()
    assert task.has_active_lease(now=START) is False


def test_task_approval_makes_it_ready_until_leased():
    task = task_model(approval_required=True)
    assert task.is_ready_to_run() is False
    task.mark_approved()
    assert task.is_ready_to_run() is True
    task.acquire_lease()
    assert task.is_ready_to_run() is False


@pytest.mark.parametrize("status", list(TaskStatus))
def test_task_readiness_and_terminality_are_explicit_per_status(status):
    task = task_model(status=status, approval_required=True)
    assert task.is_ready_to_run() is (status is TaskStatus.APPROVED)
    assert task.is_completed() is (status in TASK_TERMINALS)


def test_workflow_creation_preserves_identity_and_defaults():
    plan = plan_model()
    assert (plan.workflow_id, plan.title, plan.created_by) == ("workflow-1", "Test Workflow", "alice")
    assert plan.status is WorkflowStatus.DRAFT
    assert plan.mode is WorkflowMode.DRAFT
    assert plan.tasks == []
    assert plan.dependencies == {}
    assert plan.transition_history == ()
    assert plan.created_at == plan.updated_at == START


@pytest.mark.parametrize("mode", list(WorkflowMode))
def test_workflow_mode_stays_independent_of_lifecycle(mode):
    plan = plan_model(mode=mode)
    assert plan.status is WorkflowStatus.DRAFT
    plan.mark_pending(at=TICK)
    assert plan.status is WorkflowStatus.PENDING
    plan.mark_running(at=TICK)
    assert plan.status is WorkflowStatus.RUNNING
    assert plan.mode is mode


@pytest.mark.parametrize("status", list(WorkflowStatus))
def test_workflow_terminality_is_explicit_per_status(status):
    plan = plan_model(status=status)
    assert plan.is_terminal() is (status in PLAN_TERMINALS)


def test_workflow_add_task_preserves_order_and_duplicate_is_noop():
    plan = plan_model()
    plan.add_task("z", at=START)
    plan.add_task("a", at=TICK)
    plan.add_task("z", at=TICK + timedelta(seconds=1))
    assert plan.tasks == ["z", "a"]
    assert plan.updated_at == TICK


@pytest.mark.parametrize("task_id", ["", " ", None])
def test_workflow_rejects_invalid_task_id_without_editing(task_id):
    plan = plan_model()
    with pytest.raises(ValueError):
        plan.add_task(task_id, at=TICK)
    assert plan.tasks == []
    assert plan.updated_at == START


def test_workflow_owns_graph_and_preserves_explicit_empty_dependencies():
    first = plan_model(tasks=["a", "b"])
    second = plan_model(tasks=["a", "b"])
    dependencies = ["a"]
    first.set_dependencies("b", dependencies, at=TICK)
    dependencies.clear()
    assert first.dependencies == {"b": ["a"]}
    assert second.dependencies == {}
    graph = first.dependencies
    graph["b"].clear()
    assert first.dependencies == {"b": ["a"]}
    first.set_dependencies("b", [], at=TICK)
    assert first.dependencies == {"b": []}


@pytest.mark.parametrize(("node", "parents", "error"), [
    ("unknown", [], ValueError), ("a", ["unknown"], ValueError),
    ("a", ["a"], ValueError), ("b", ["a", "a"], ValueError),
    ("a", ["b"], ValueError), ("a", ("b",), TypeError),
], ids=["unknown-owner", "unknown-parent", "self", "duplicate", "cycle", "not-list"])
def test_workflow_rejects_bad_dependency_graph_atomically(node, parents, error):
    plan = plan_model(tasks=["a", "b"], dependencies={"b": ["a"]})
    with pytest.raises(error):
        plan.set_dependencies(node, parents, at=TICK)
    assert plan.tasks == ["a", "b"]
    assert plan.dependencies == {"b": ["a"]}
    assert plan.updated_at == START


@pytest.mark.parametrize("evidence", [
    (), set(), None, ["a"], ["a", "b", "c"], ["a", "a"], [True, "a"], {"a": "b"},
], ids=["omitted-shape", "empty", "none", "missing", "extra", "duplicate", "non-string-id", "wrong-container"])
def test_workflow_requires_exact_completed_task_ids(evidence):
    plan = plan_model(tasks=["a", "b"], dependencies={"b": ["a"]})
    plan.mark_running(at=TICK)
    history = plan.transition_history
    with pytest.raises(ValueError):
        plan.mark_completed(completed_task_ids=evidence, at=START)
    assert plan.status is WorkflowStatus.RUNNING
    assert plan.updated_at == TICK
    assert plan.transition_history == history


@pytest.mark.parametrize("status", list(WorkflowStatus))
def test_workflow_completion_requires_running_even_with_exact_ids(status):
    plan = plan_model(tasks=["a", "b"], status=status)
    if status is WorkflowStatus.RUNNING:
        plan.mark_completed(completed_task_ids={"a", "b"}, at=TICK)
        assert plan.status is WorkflowStatus.COMPLETED
        assert plan.transition_history[-1].current is WorkflowStatus.COMPLETED
        assert plan.updated_at == TICK
    else:
        with pytest.raises(ValueError):
            plan.mark_completed(completed_task_ids={"a", "b"}, at=TICK)
        assert plan.status is status
        assert plan.updated_at == START
        assert plan.transition_history == ()


@pytest.mark.parametrize(("method", "end"), [
    ("mark_failed", WorkflowStatus.FAILED), ("mark_cancelled", WorkflowStatus.CANCELLED),
    ("mark_governance_blocked", WorkflowStatus.GOVERNANCE_BLOCKED),
])
def test_workflow_terminal_history_appends_and_cannot_be_replaced(method, end):
    plan = plan_model()
    other = plan_model()
    plan.mark_running(at=START)
    earlier = plan.transition_history
    run = getattr(plan, method)
    run("first reason", at=TICK)
    assert plan.status is end
    assert plan.updated_at == TICK
    records = plan.transition_history
    assert len(records) == 2
    assert records[:1] == earlier
    last = records[-1]
    assert (last.previous, last.current, last.at, last.reason) == (
        WorkflowStatus.RUNNING, end, TICK, "first reason",
    )
    with pytest.raises(ValueError):
        run("second reason", at=START)
    assert plan.transition_history == records
    assert plan.updated_at == TICK
    assert other.transition_history == ()


def test_workflow_constructor_detaches_tasks_and_each_dependency_list():
    tasks = ["x", "y"]
    prerequisites = ["x"]
    graph = {"y": prerequisites}
    plan = plan_model(tasks=tasks, dependencies=graph)
    tasks.clear()
    prerequisites.clear()
    graph["new"] = ["x"]
    assert plan.tasks == ["x", "y"]
    assert plan.dependencies == {"y": ["x"]}


def test_workflow_with_no_tasks_never_completes_on_empty_evidence():
    plan = plan_model()
    plan.mark_running(at=TICK)
    with pytest.raises(ValueError):
        plan.mark_completed(at=START)
    assert plan.status is WorkflowStatus.RUNNING
    assert plan.updated_at == TICK


def test_task_approved_with_legacy_lease_is_not_ready():
    task = task_model(status=TaskStatus.APPROVED, lease_lock=START)
    assert task.lease_lock == START
    assert task.is_ready_to_run() is False


def test_task_paused_does_not_acquire_lease_or_resume():
    task = task_model()
    task.mark_paused()
    with pytest.raises(ValueError):
        task.acquire_lease(at=TICK)
    assert task.status is TaskStatus.PAUSED
    assert task.paused_from_status == TaskStatus.DRAFT.value
    assert task.lease_lock is None


@pytest.mark.parametrize(("method", "args", "expected"), [
    ("mark_completed", ({"output": "first"},), {"result": {"output": "first"}}),
    ("mark_cancelled", ("first reason",), {"cancellation_reason": "first reason"}),
])
def test_task_terminal_call_is_not_repeated_from_a_public_transition(method, args, expected):
    task = task_model()
    task.mark_approved()
    transition = getattr(task, method)
    transition(*args)
    stamp = task.updated_at
    with pytest.raises(ValueError):
        transition(*args)
    assert task.payload == expected
    assert task.updated_at == stamp
