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


def test_exact_file_overlap_is_warn_evidence():
    graph = build_issue_batch_graph(
        [node("b", paths=("a.py",)), node("a", paths=("./a.py",))]
    )
    result = by_name(evaluate_base_batch_conflicts(graph))[
        "batch exact path overlap"
    ]
    assert result.status == Status.WARN
    assert result.evidence == ["nodes=a,b; path=a.py"]


def test_directory_prefix_overlap_is_boundary_aware():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("app",)),
            node("b", paths=("app/models.py",)),
            node("c", paths=("application/main.py",)),
        ]
    )
    result = by_name(evaluate_base_batch_conflicts(graph))[
        "batch directory path overlap"
    ]
    assert result.status == Status.WARN
    assert result.evidence == ["nodes=a,b; paths=app,app/models.py"]


def test_forbidden_path_conflict_is_fail_and_cross_node():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("prod/secrets.py",)),
            node("b", forbidden=("prod",)),
        ]
    )
    result = by_name(evaluate_base_batch_conflicts(graph))[
        "batch forbidden path conflict"
    ]
    assert result.status == Status.FAIL
    assert result.evidence == [
        "affected_node=a; forbidden_node=b; path=prod/secrets.py; pattern=prod"
    ]


def test_glob_forbidden_path_conflict_is_supported():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("src/generated/cache.py",)),
            node("b", forbidden=("src/generated/*",)),
        ]
    )
    result = by_name(evaluate_base_batch_conflicts(graph))[
        "batch forbidden path conflict"
    ]
    assert result.status == Status.FAIL


def test_differing_owners_and_sources_require_manual_review():
    graph = build_issue_batch_graph(
        [
            node("b", owner="QA / Test Agent", source="Notion"),
            node("a", owner="Integration Manager", source="GitHub"),
        ]
    )
    results = by_name(evaluate_base_batch_conflicts(graph))
    assert results["batch owner compatibility"].status == Status.MANUAL_REVIEW
    assert (
        results["batch source-of-truth compatibility"].status
        == Status.MANUAL_REVIEW
    )
    assert results["batch owner compatibility"].evidence == [
        "node=a; owner=Integration Manager",
        "node=b; owner=QA / Test Agent",
    ]


def test_missing_metadata_requires_manual_review():
    graph = build_issue_batch_graph([node("a", owner=None, source=None)])
    result = by_name(evaluate_base_batch_conflicts(graph))[
        "batch required metadata"
    ]
    assert result.status == Status.MANUAL_REVIEW
    assert result.evidence == [
        "node=a; missing=owner",
        "node=a; missing=source_of_truth",
    ]


def test_empty_and_single_complete_graphs_pass_all_checks():
    for graph in (IssueBatchGraph(), build_issue_batch_graph([node("a")])):
        results = evaluate_base_batch_conflicts(graph)
        assert len(results) == 6
        assert all(result.status == Status.PASS for result in results)


def test_result_and_evidence_order_are_deterministic():
    forward = build_issue_batch_graph(
        [
            node(
                "b",
                paths=("src/b.py", "shared"),
                owner="B",
                source="Notion",
            ),
            node(
                "a",
                paths=("shared/a.py",),
                owner="A",
                source="GitHub",
            ),
        ]
    )
    reverse = build_issue_batch_graph(reversed(forward.nodes))
    assert evaluate_base_batch_conflicts(forward) == evaluate_base_batch_conflicts(
        reverse
    )
    assert [result.name for result in evaluate_base_batch_conflicts(forward)] == [
        "batch exact path overlap",
        "batch directory path overlap",
        "batch forbidden path conflict",
        "batch owner compatibility",
        "batch source-of-truth compatibility",
        "batch required metadata",
    ]


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
