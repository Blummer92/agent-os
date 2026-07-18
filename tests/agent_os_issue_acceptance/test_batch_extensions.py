from dataclasses import dataclass
import socket

import pytest

from scripts.agent_os_issue_acceptance.batch_extensions import (
    GraphCheckResult,
    run_graph_checks,
)
from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
)
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


def ok_result(name: str = "ok", **kwargs: object) -> GraphCheckResult:
    return GraphCheckResult(
        checks=(CheckResult(name, Status.PASS, "ok", ["evidence"]),),
        **kwargs,
    )


def test_checks_run_in_stable_check_id_order():
    calls: list[str] = []
    run = run_graph_checks(
        graph(),
        (
            Check("z", ok_result("z"), calls),
            Check("a", ok_result("a"), calls),
        ),
    )
    assert calls == ["a", "z"]
    assert [result.name for result in run.checks] == ["a", "z"]


def test_duplicate_check_ids_reject_before_execution():
    calls: list[str] = []
    with pytest.raises(ValueError, match="duplicate check_id values: duplicate"):
        run_graph_checks(
            graph(),
            (
                Check("duplicate", ok_result(), calls),
                Check("duplicate", ok_result(), calls),
            ),
        )
    assert calls == []


def test_blank_check_id_is_rejected():
    with pytest.raises(ValueError, match="non-empty check_id"):
        run_graph_checks(graph(), (Check(" ", ok_result()),))


def test_extension_exception_is_bounded_and_remaining_checks_continue():
    run = run_graph_checks(
        graph(),
        (
            Check("a", error=RuntimeError("do not expose this message")),
            Check("b", ok_result("b")),
        ),
    )
    assert run.failed_check_ids == ("a",)
    assert run.checks[0].status == Status.MANUAL_REVIEW
    assert run.checks[0].evidence == [
        "check_id=a",
        "failure=exception",
        "exception_type=RuntimeError",
    ]
    assert run.checks[1].name == "b"


def test_malformed_extension_output_requires_manual_review():
    run = run_graph_checks(graph(), (Check("a", object()),))
    assert run.failed_check_ids == ("a",)
    assert run.checks[0].evidence == [
        "check_id=a",
        "failure=malformed-output",
    ]


def test_unknown_node_id_requires_manual_review():
    run = run_graph_checks(
        graph(),
        (Check("a", ok_result(inspected_node_ids=("unknown",))),),
    )
    assert run.failed_check_ids == ("a",)
    assert "failure=unknown-node-id" in run.checks[0].evidence


def test_unknown_dependency_pair_requires_manual_review():
    run = run_graph_checks(
        graph(),
        (
            Check(
                "a",
                ok_result(inspected_dependency_pairs=(("unknown", "pair"),)),
            ),
        ),
    )
    assert run.failed_check_ids == ("a",)
    assert "failure=unknown-dependency-pair" in run.checks[0].evidence


def test_check_result_evidence_is_copied_into_snapshot():
    evidence = ["before"]
    source = CheckResult("source", Status.PASS, "ok", evidence)
    run = run_graph_checks(
        graph(),
        (Check("a", GraphCheckResult(checks=(source,))),),
    )
    evidence.append("after")
    assert run.checks[0].evidence == ["before"]


def test_ids_and_dependency_pairs_are_sorted_and_deduplicated():
    run = run_graph_checks(
        graph(),
        (
            Check(
                "a",
                ok_result(
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
    assert run.quarantined_node_ids == ("a", "b")
    assert run.inspected_node_ids == ("a", "b")
    assert run.inspected_dependency_pairs == (
        ("a", "missing"),
        ("b", "a"),
    )


def test_checking_is_offline_and_graph_remains_unchanged(monkeypatch):
    supplied = graph()
    before = repr(supplied)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: pytest.fail("network access"),
    )
    run_graph_checks(supplied, (Check("a", ok_result()),))
    assert repr(supplied) == before


def test_wrong_graph_type_fails_closed():
    with pytest.raises(TypeError, match="graph must be an IssueBatchGraph"):
        run_graph_checks(object(), ())
