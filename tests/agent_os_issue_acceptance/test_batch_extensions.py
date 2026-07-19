from dataclasses import dataclass
import socket

import pytest

from scripts.agent_os_issue_acceptance.batch_extensions import (
    GraphCheckResult,
    run_graph_checks,
)
from scripts.agent_os_issue_acceptance.batch_graph import IssueBatchGraph, IssueBatchNode
from scripts.agent_os_issue_acceptance.models import CheckResult, Status
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome


@dataclass
class Check:
    check_id: str
    result: object = None
    calls: list[str] | None = None
    error: Exception | None = None

    def __call__(self, graph: IssueBatchGraph) -> object:
        if self.calls is not None:
            self.calls.append(self.check_id)
        if self.error is not None:
            raise self.error
        return self.result


def graph() -> IssueBatchGraph:
    return IssueBatchGraph(
        nodes=(
            IssueBatchNode("a", ReadinessOutcome.READY),
            IssueBatchNode("b", ReadinessOutcome.READY),
        ),
        resolved_dependencies=(("b", "a"),),
        unresolved_dependencies=(("a", "missing"),),
    )


def result(name: str = "ok", **kwargs: object) -> GraphCheckResult:
    return GraphCheckResult(
        checks=(CheckResult(name, Status.PASS, "ok", ["evidence"]),),
        **kwargs,
    )


def test_deterministic_order_and_duplicate_preflight():
    calls: list[str] = []
    run = run_graph_checks(
        graph(),
        (Check("z", result("z"), calls), Check("a", result("a"), calls)),
    )
    assert calls == ["a", "z"]
    assert [item.name for item in run.checks] == ["a", "z"]

    calls.clear()
    with pytest.raises(ValueError, match="duplicate check_id"):
        run_graph_checks(
            graph(),
            (Check("same", result(), calls), Check("same", result(), calls)),
        )
    assert calls == []


def test_blank_id_and_wrong_graph_fail_closed():
    with pytest.raises(ValueError, match="non-empty check_id"):
        run_graph_checks(graph(), (Check(" ", result()),))
    with pytest.raises(TypeError, match="graph must be an IssueBatchGraph"):
        run_graph_checks(object(), ())


def test_exception_is_bounded_and_remaining_check_runs():
    run = run_graph_checks(
        graph(),
        (Check("a", error=RuntimeError("details")), Check("b", result("b"))),
    )
    assert run.failed_check_ids == ("a",)
    assert run.checks[0].status == Status.MANUAL_REVIEW
    assert run.checks[0].evidence == [
        "check_id=a",
        "failure=exception",
        "exception_type=RuntimeError",
    ]
    assert run.checks[1].name == "b"


def test_malformed_and_unknown_references_require_review():
    malformed = run_graph_checks(graph(), (Check("a", object()),))
    assert "failure=malformed-output" in malformed.checks[0].evidence

    unknown_node = run_graph_checks(
        graph(), (Check("a", result(inspected_node_ids=("unknown",))),)
    )
    assert "failure=unknown-node-id" in unknown_node.checks[0].evidence

    unknown_pair = run_graph_checks(
        graph(),
        (Check("a", result(inspected_dependency_pairs=(("x", "y"),))),),
    )
    assert "failure=unknown-dependency-pair" in unknown_pair.checks[0].evidence


def test_snapshot_copy_and_sorted_deduplicated_output():
    evidence = ["before"]
    source = CheckResult("source", Status.PASS, "ok", evidence)
    run = run_graph_checks(
        graph(),
        (
            Check(
                "a",
                GraphCheckResult(
                    checks=(source,),
                    quarantined_node_ids=("b", "a", "b"),
                    inspected_node_ids=("b", "a", "b"),
                    inspected_dependency_pairs=(
                        ("b", "a"),
                        ("a", "missing"),
                        ("b", "a"),
                    ),
                ),
            ),
        ),
    )
    evidence.append("after")
    assert run.checks[0].evidence == ["before"]
    assert run.quarantined_node_ids == ("a", "b")
    assert run.inspected_node_ids == ("a", "b")
    assert run.inspected_dependency_pairs == (("a", "missing"), ("b", "a"))


def test_offline_and_graph_unchanged(monkeypatch):
    supplied = graph()
    before = repr(supplied)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: pytest.fail("unexpected socket use"),
    )
    run_graph_checks(supplied, (Check("a", result()),))
    assert repr(supplied) == before
