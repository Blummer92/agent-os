import builtins
import inspect
import socket

import pytest

from scripts.agent_os_issue_acceptance import (
    evaluate_input_scope_coverage,
    unresolved_dependency_check,
)
from scripts.agent_os_issue_acceptance.batch_extensions import GraphCheckRun
from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
)
from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome


def node(node_id: str) -> IssueBatchNode:
    return IssueBatchNode(
        node_id=node_id,
        readiness=ReadinessOutcome.READY,
    )


def graph(
    *,
    nodes: tuple[IssueBatchNode, ...] = (),
    resolved: tuple[tuple[str, str], ...] = (),
    unresolved: tuple[tuple[str, str], ...] = (),
) -> IssueBatchGraph:
    return IssueBatchGraph(
        nodes=nodes,
        resolved_dependencies=resolved,
        unresolved_dependencies=unresolved,
    )


def run(
    *,
    nodes: tuple[str, ...] = (),
    pairs: tuple[tuple[str, str], ...] = (),
    failed: tuple[str, ...] = (),
) -> GraphCheckRun:
    return GraphCheckRun(
        checks=(),
        quarantined_node_ids=(),
        inspected_node_ids=nodes,
        inspected_dependency_pairs=pairs,
        failed_check_ids=failed,
    )


def test_empty_graph_coverage_passes():
    result = evaluate_input_scope_coverage(graph(), run())
    assert result.status == Status.PASS
    assert result.message == "input_scope_covered"
    assert result.evidence == ["coverage_scope=supplied-graph-only"]


def test_complete_node_and_pair_coverage_passes():
    supplied = graph(
        nodes=(node("a"), node("b")),
        resolved=(("a", "b"),),
        unresolved=(("b", "missing"),),
    )
    result = evaluate_input_scope_coverage(
        supplied,
        run(
            nodes=("b", "a"),
            pairs=(("b", "missing"), ("a", "b")),
        ),
    )
    assert result.status == Status.PASS
    assert result.evidence == ["coverage_scope=supplied-graph-only"]


def test_missing_coverage_and_failed_checks_are_sorted():
    supplied = graph(
        nodes=(node("b"), node("a")),
        resolved=(("b", "a"),),
        unresolved=(("a", "z"),),
    )
    result = evaluate_input_scope_coverage(
        supplied,
        run(failed=("z-check", "a-check")),
    )
    assert result.status == Status.MANUAL_REVIEW
    assert result.evidence == [
        "coverage_scope=supplied-graph-only",
        "failed_check_id=a-check",
        "failed_check_id=z-check",
        "missing_node=a",
        "missing_node=b",
        "missing_resolved_pair=b,a",
        "missing_unresolved_pair=a,z",
    ]


def test_each_missing_coverage_type_requires_manual_review():
    supplied = graph(
        nodes=(node("a"), node("b")),
        resolved=(("a", "b"),),
        unresolved=(("b", "missing"),),
    )
    cases = (
        run(nodes=("a",), pairs=(("a", "b"), ("b", "missing"))),
        run(nodes=("a", "b"), pairs=(("b", "missing"),)),
        run(nodes=("a", "b"), pairs=(("a", "b"),)),
        run(
            nodes=("a", "b"),
            pairs=(("a", "b"), ("b", "missing")),
            failed=("broken",),
        ),
    )
    assert all(
        evaluate_input_scope_coverage(supplied, item).status
        == Status.MANUAL_REVIEW
        for item in cases
    )


def test_unresolved_dependency_check_passes_without_pairs():
    result = unresolved_dependency_check(graph(nodes=(node("a"),)))
    assert result.checks[0].status == Status.PASS
    assert result.checks[0].evidence == []
    assert result.inspected_node_ids == ("a",)
    assert result.inspected_dependency_pairs == ()


def test_unresolved_dependency_evidence_is_sorted_and_declares_pair_coverage():
    supplied = graph(
        nodes=(node("b"), node("a")),
        unresolved=(("b", "z"), ("a", "x")),
    )
    first = unresolved_dependency_check(supplied)
    second = unresolved_dependency_check(supplied)
    assert first == second
    assert first.checks[0].status == Status.MANUAL_REVIEW
    assert first.checks[0].evidence == [
        "source=a; target=x",
        "source=b; target=z",
    ]
    assert first.inspected_node_ids == ("a", "b")
    assert first.inspected_dependency_pairs == (("a", "x"), ("b", "z"))


def test_scope_checks_are_offline_and_do_not_mutate_inputs(monkeypatch):
    supplied = graph(
        nodes=(node("a"),),
        unresolved=(("a", "missing"),),
    )
    supplied_run = run(nodes=("a",), pairs=(("a", "missing"),))
    graph_before = repr(supplied)
    run_before = repr(supplied_run)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: pytest.fail("unexpected socket use"),
    )
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *args, **kwargs: pytest.fail("unexpected file access"),
    )
    unresolved_dependency_check(supplied)
    evaluate_input_scope_coverage(supplied, supplied_run)
    assert repr(supplied) == graph_before
    assert repr(supplied_run) == run_before


def test_source_uses_supplied_graph_terminology_only():
    source = inspect.getsource(unresolved_dependency_check.__class__)
    coverage_source = inspect.getsource(evaluate_input_scope_coverage)
    combined = f"{source}\n{coverage_source}".lower()
    assert "evidence_exhausted" not in combined
    assert "historical" not in combined
    assert "active relationship" not in combined
