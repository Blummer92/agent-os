import socket

import pytest

from scripts.agent_os_issue_acceptance.batch_checks import (
    evaluate_base_batch_conflicts,
)
from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
    build_issue_batch_graph,
)
from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome


def node(
    node_id,
    *,
    paths=(),
    forbidden=(),
    owner="Integration Manager",
    source="GitHub",
):
    return IssueBatchNode(
        node_id=node_id,
        readiness=ReadinessOutcome.READY,
        owner=owner,
        source_of_truth=source,
        affected_paths=tuple(paths),
        forbidden_paths=tuple(forbidden),
    )


def by_name(results):
    return {result.name: result for result in results}


def test_final_result_order_is_fixed():
    assert [
        result.name
        for result in evaluate_base_batch_conflicts(build_issue_batch_graph([node("a")]))
    ] == [
        "batch declared path syntax",
        "batch exact path overlap",
        "batch directory path overlap",
        "batch forbidden path conflict",
        "batch owner compatibility",
        "batch source-of-truth compatibility",
        "batch required metadata",
    ]


def test_exact_and_directory_overlap_are_boundary_aware():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("app", ".github/workflows/check.yml")),
            node("b", paths=("app/models.py", ".github/workflows/check.yml")),
            node("c", paths=("application/main.py",)),
        ]
    )
    results = by_name(evaluate_base_batch_conflicts(graph))
    assert results["batch exact path overlap"].evidence == [
        "nodes=a,b; path=.github/workflows/check.yml"
    ]
    assert results["batch directory path overlap"].evidence == [
        "nodes=a,b; paths=app,app/models.py"
    ]


def test_forbidden_conflict_supports_bounded_wildcard_without_crossing_slash():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("src/generated/cache.py", "src/generated/nested/cache.py")),
            node("b", forbidden=("src/generated/*.py",)),
        ]
    )
    result = by_name(evaluate_base_batch_conflicts(graph))[
        "batch forbidden path conflict"
    ]
    assert result.status == Status.FAIL
    assert result.evidence == [
        "affected_node=a; forbidden_node=b; path=src/generated/cache.py; pattern=src/generated/*.py"
    ]


def test_sibling_prefixes_remain_distinct():
    graph = build_issue_batch_graph(
        [node("a", paths=("production-old/config.yml",)), node("b", forbidden=("production",))]
    )
    results = by_name(evaluate_base_batch_conflicts(graph))
    assert results["batch directory path overlap"].status == Status.PASS
    assert results["batch forbidden path conflict"].status == Status.PASS


def test_malformed_values_route_to_manual_review_with_stable_evidence():
    graph = build_issue_batch_graph(
        [
            node("b", paths=("/absolute.txt",), forbidden=("src/**",)),
            node("a", paths=("../traversal.txt",)),
        ]
    )
    result = evaluate_base_batch_conflicts(graph)[0]
    assert result.name == "batch declared path syntax"
    assert result.status == Status.MANUAL_REVIEW
    assert result.evidence == [
        "node=a; field=affected_paths; value='../traversal.txt'; code=traversal",
        "node=b; field=affected_paths; value='/absolute.txt'; code=absolute-posix",
        "node=b; field=forbidden_paths; value='src/**'; code=unsupported-double-star",
    ]


def test_valid_values_from_partially_malformed_nodes_continue_to_conflicts():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("../ignored.txt", "production/secrets.txt")),
            node("b", forbidden=("production", "src/**")),
        ]
    )
    results = by_name(evaluate_base_batch_conflicts(graph))
    assert results["batch declared path syntax"].status == Status.MANUAL_REVIEW
    assert results["batch forbidden path conflict"].status == Status.FAIL
    assert results["batch forbidden path conflict"].evidence == [
        "affected_node=a; forbidden_node=b; path=production/secrets.txt; pattern=production"
    ]


def test_differing_owners_sources_and_missing_metadata_are_preserved():
    graph = build_issue_batch_graph(
        [
            node("a", owner="Integration Manager", source="GitHub"),
            node("b", owner="QA / Test Agent", source="Notion"),
            node("c", owner=None, source=None),
        ]
    )
    results = by_name(evaluate_base_batch_conflicts(graph))
    assert results["batch owner compatibility"].status == Status.MANUAL_REVIEW
    assert results["batch source-of-truth compatibility"].status == Status.MANUAL_REVIEW
    assert results["batch required metadata"].evidence == [
        "node=c; missing=owner",
        "node=c; missing=source_of_truth",
    ]


def test_empty_and_single_complete_graphs_pass_all_checks():
    for graph in (IssueBatchGraph(), build_issue_batch_graph([node("a")])):
        results = evaluate_base_batch_conflicts(graph)
        assert len(results) == 7
        assert all(result.status == Status.PASS for result in results)


def test_result_and_evidence_order_are_deterministic():
    forward = build_issue_batch_graph(
        [
            node("b", paths=("src/b.py", "shared"), owner="B", source="Notion"),
            node("a", paths=("shared/a.py",), owner="A", source="GitHub"),
        ]
    )
    reverse = build_issue_batch_graph(reversed(forward.nodes))
    assert evaluate_base_batch_conflicts(forward) == evaluate_base_batch_conflicts(reverse)


def test_graph_is_unchanged_and_checking_is_offline(monkeypatch):
    graph = build_issue_batch_graph(
        [node("a", paths=("src",)), node("b", paths=("src/b.py",))]
    )
    before = repr(graph)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: pytest.fail("network access"),
    )
    evaluate_base_batch_conflicts(graph)
    assert repr(graph) == before


def test_wrong_graph_type_fails_closed():
    with pytest.raises(TypeError, match="graph must be an IssueBatchGraph"):
        evaluate_base_batch_conflicts(object())
