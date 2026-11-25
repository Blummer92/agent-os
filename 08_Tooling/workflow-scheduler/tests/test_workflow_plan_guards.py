from datetime import UTC, datetime, timedelta
import json

import pytest

from workflow_scheduler.models import WorkflowMode, WorkflowPlan, WorkflowStatus


START = datetime(2026, 11, 25, tzinfo=UTC)
NEXT = START + timedelta(seconds=1)


def _plan(**kwargs):
    return WorkflowPlan("workflow", "Plan", "owner", created_at=START, **kwargs)


_TRANSITION_CALLS = (
    ("mark_pending", {}),
    ("mark_running", {}),
    ("mark_completed", {"completed_task_ids": {"a"}}),
    ("mark_failed", {"reason": "second failure"}),
    ("mark_paused", {}),
    ("resume", {}),
    ("mark_cancelled", {}),
    ("mark_governance_blocked", {}),
)


@pytest.mark.parametrize("status", [
    WorkflowStatus.COMPLETED, WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED, WorkflowStatus.GOVERNANCE_BLOCKED,
])
@pytest.mark.parametrize(("method", "kwargs"), _TRANSITION_CALLS)
def test_terminal_plans_cannot_transition(status, method, kwargs):
    plan = _plan(status=status, tasks=["a"])
    assert plan.is_terminal()
    with pytest.raises(ValueError):
        getattr(plan, method)(at=NEXT, **kwargs)
    assert plan.status is status
    assert plan.updated_at == START
    assert not plan.transition_history


@pytest.mark.parametrize("status", [
    WorkflowStatus.DRAFT, WorkflowStatus.PENDING, WorkflowStatus.PAUSED, WorkflowStatus.FAILED,
])
def test_exact_task_set_does_not_bypass_required_running_state(status):
    plan = _plan(status=status, tasks=["a"])
    with pytest.raises(ValueError):
        plan.mark_completed(completed_task_ids={"a"}, at=NEXT)
    assert plan.status is status


@pytest.mark.parametrize("reported", [(), ("a",), ("a", "a"), ("a", "unexpected")])
def test_running_plans_require_exact_completion_evidence(reported):
    plan = _plan(status=WorkflowStatus.RUNNING, tasks=["a", "b"], dependencies={"b": ["a"]})
    with pytest.raises(ValueError):
        plan.mark_completed(completed_task_ids=reported, at=NEXT)
    plan.mark_completed(completed_task_ids={"a", "b"}, at=NEXT)
    assert plan.transition_history[-1].current is WorkflowStatus.COMPLETED


def test_empty_workflow_is_not_completed():
    plan = _plan(status=WorkflowStatus.RUNNING)
    with pytest.raises(ValueError):
        plan.mark_completed()


@pytest.mark.parametrize("method", ["mark_paused", "resume"])
def test_explicit_pause_and_resume_have_distinct_preconditions(method):
    plan = _plan()
    with pytest.raises(ValueError):
        getattr(plan, method)(at=NEXT)
    assert plan.status is WorkflowStatus.DRAFT


@pytest.mark.parametrize(("task", "parents"), [
    ("missing", []), ("a", ["missing"]), ("a", ["a"]),
    ("b", ["a", "a"]), ("a", ["c"]),
])
def test_invalid_graph_is_rejected_without_mutation(task, parents):
    graph = {"b": ["a"], "c": ["b"]}
    plan = _plan(tasks=["a", "b", "c"], dependencies=graph)
    with pytest.raises(ValueError):
        plan.set_dependencies(task, parents, at=NEXT)
    assert plan.dependencies == graph
    assert plan.updated_at == START


def test_graph_and_metadata_are_owned_copies():
    tasks, parents = ["a", "b"], ["a"]
    meta = {"user": ["keep"]}
    plan = _plan(tasks=tasks, dependencies={"b": parents}, metadata=meta)
    tasks.append("c")
    parents.clear()
    meta["user"].clear()
    plan.tasks.append("unowned")
    plan.dependencies["b"].append("unowned")
    added = ["a"]
    plan.set_dependencies("b", added, at=NEXT)
    added.clear()
    assert plan.tasks == ["a", "b"]
    assert json.dumps(plan.dependencies) == '{"b": ["a"]}'
    assert plan.metadata == {"user": ["keep"]}
    with pytest.raises(AttributeError):
        plan.status = WorkflowStatus.COMPLETED
    with pytest.raises(AttributeError):
        del plan.status
    with pytest.raises(AttributeError):
        plan.dependencies = {"a": ["a"]}


def test_constructor_rejects_invalid_graph_and_blank_identity():
    with pytest.raises(ValueError, match="Circular"):
        _plan(tasks=["a", "b"], dependencies={"a": ["b"], "b": ["a"]})
    with pytest.raises(ValueError, match="title"):
        WorkflowPlan("workflow", "  ", "owner")


@pytest.mark.parametrize("kwargs", [
    {"mode": "Draft"}, {"status": "draft"},
    {"mode": WorkflowStatus.DRAFT}, {"status": WorkflowMode.DRAFT},
])
def test_mode_and_status_require_their_distinct_enum_types(kwargs):
    with pytest.raises(TypeError):
        _plan(**kwargs)


def test_explicit_timestamps_noop_and_terminal_reason_history():
    calls = []

    def clock():
        calls.append(None)
        return START

    plan = WorkflowPlan("workflow", "Plan", "owner", clock=clock, metadata={"failure_reason": "user metadata"})
    assert plan.created_at == plan.updated_at == START
    assert len(calls) == 1
    plan.add_task("a", at=NEXT)
    plan.add_task("a")
    assert plan.updated_at == NEXT
    with pytest.raises(ValueError):
        plan.add_task(" ", at=NEXT)
    assert len(calls) == 1

    plan.mark_pending(at=NEXT)
    plan.mark_running(at=NEXT)
    plan.mark_paused(reason="pause\nfirst", at=NEXT)
    plan.resume(at=NEXT)
    plan.mark_failed(reason="first\x00 failure" + "x" * 1000, at=NEXT)
    snapshot = plan.transition_history
    assert snapshot[0].previous is WorkflowStatus.DRAFT
    assert snapshot[0].current is WorkflowStatus.PENDING
    assert snapshot[2].reason == "pause first"
    assert len(snapshot[-1].reason) == 500
    assert "\x00" not in snapshot[-1].reason
    with pytest.raises(ValueError):
        plan.mark_failed(reason="second", at=NEXT)
    assert plan.transition_history == snapshot
    assert plan.metadata == {"failure_reason": "user metadata"}


def test_history_is_bounded_without_discarding_latest_transition():
    plan = _plan(status=WorkflowStatus.RUNNING)
    for i in range(40):
        plan.mark_paused(reason=f"pause {i}", at=NEXT)
        plan.resume(at=NEXT)
    assert len(plan.transition_history) == 64
    assert plan.transition_history[-2].reason == "pause 39"
    assert plan.transition_history[-1].at == NEXT


def test_planned_tasks_cannot_change_after_completion():
    plan = _plan(status=WorkflowStatus.RUNNING, tasks=["a", "b"])
    plan.mark_completed(completed_task_ids={"a", "b"}, at=NEXT)
    with pytest.raises(ValueError, match="terminal"):
        plan.add_task("c", at=NEXT)
    with pytest.raises(ValueError, match="terminal"):
        plan.set_dependencies("b", ["a"], at=NEXT)
    assert plan.tasks == ["a", "b"]
    assert plan.dependencies == {}
