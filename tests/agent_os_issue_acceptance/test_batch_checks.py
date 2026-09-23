import socket

import pytest

from scripts.agent_os_issue_acceptance.batch_checks import (
    BatchConflictRun,
    ForbiddenPathCrossing,
    evaluate_base_batch_conflict_run,
    evaluate_base_batch_conflicts,
)
from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
    build_issue_batch_graph,
)
from scripts.agent_os_issue_acceptance.models import CheckResult, Status
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


def test_compatibility_wrapper_returns_the_structured_run_checks():
    graph = build_issue_batch_graph([node("a", paths=("src",)), node("b", paths=("src/b.py",))])
    assert evaluate_base_batch_conflicts(graph) == evaluate_base_batch_conflict_run(graph).checks


def test_exact_and_directory_overlap_are_boundary_aware():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("app", ".github/workflows/check.yml")),
            node("b", paths=("app/models.py", ".github/workflows/check.yml")),
            node("c", paths=("application/main.py",)),
        ]
    )
    run = evaluate_base_batch_conflict_run(graph)
    results = by_name(run.checks)
    assert results["batch exact path overlap"].evidence == [
        "nodes=a,b; path=.github/workflows/check.yml"
    ]
    assert results["batch directory path overlap"].evidence == [
        "nodes=a,b; paths=app,app/models.py"
    ]
    assert run.sequencing_pairs == (("a", "b"),)


def test_exact_and_directory_evidence_deduplicate_one_sequencing_pair():
    graph = build_issue_batch_graph(
        [
            node("b", paths=("shared/file.py", "src/module.py")),
            node("a", paths=("shared/file.py", "src")),
        ]
    )
    run = evaluate_base_batch_conflict_run(graph)
    results = by_name(run.checks)
    assert results["batch exact path overlap"].status == Status.WARN
    assert results["batch directory path overlap"].status == Status.WARN
    assert run.sequencing_pairs == (("a", "b"),)


def test_forbidden_conflict_supports_bounded_wildcard_without_crossing_slash():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("src/generated/cache.py", "src/generated/nested/cache.py")),
            node("b", forbidden=("src/generated/*.py",)),
        ]
    )
    run = evaluate_base_batch_conflict_run(graph)
    result = by_name(run.checks)["batch forbidden path conflict"]
    assert result.status == Status.FAIL
    assert result.evidence == [
        "affected_node=a; forbidden_node=b; path=src/generated/cache.py; pattern=src/generated/*.py"
    ]
    assert run.forbidden_crossings == (
        ForbiddenPathCrossing(
            affected_node_id="a",
            forbidden_node_id="b",
            path="src/generated/cache.py",
            pattern="src/generated/*.py",
        ),
    )


def test_forbidden_crossings_are_sorted_and_deduplicated():
    graph = build_issue_batch_graph(
        [
            node("b", forbidden=("production", "src/*.py")),
            node("a", paths=("src/main.py", "production/config.yml")),
        ]
    )
    run = evaluate_base_batch_conflict_run(graph)
    assert run.forbidden_crossings == (
        ForbiddenPathCrossing("a", "b", "production/config.yml", "production"),
        ForbiddenPathCrossing("a", "b", "src/main.py", "src/*.py"),
    )


def test_sibling_prefixes_remain_distinct():
    graph = build_issue_batch_graph(
        [node("a", paths=("production-old/config.yml",)), node("b", forbidden=("production",))]
    )
    run = evaluate_base_batch_conflict_run(graph)
    results = by_name(run.checks)
    assert results["batch directory path overlap"].status == Status.PASS
    assert results["batch forbidden path conflict"].status == Status.PASS
    assert run.sequencing_pairs == ()
    assert run.forbidden_crossings == ()


def test_malformed_values_route_to_manual_review_with_stable_evidence():
    graph = build_issue_batch_graph(
        [
            node("b", paths=("/absolute.txt",), forbidden=("src/**",)),
            node("a", paths=("../traversal.txt",)),
        ]
    )
    run = evaluate_base_batch_conflict_run(graph)
    result = run.checks[0]
    assert result.name == "batch declared path syntax"
    assert result.status == Status.MANUAL_REVIEW
    assert result.evidence == [
        "node=a; field=affected_paths; value='../traversal.txt'; code=traversal",
        "node=b; field=affected_paths; value='/absolute.txt'; code=absolute-posix",
        "node=b; field=forbidden_paths; value='src/**'; code=unsupported-double-star",
    ]
    assert run.malformed_path_node_ids == ("a", "b")


def test_valid_values_from_partially_malformed_nodes_continue_to_conflicts():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("../ignored.txt", "production/secrets.txt")),
            node("b", forbidden=("production", "src/**")),
        ]
    )
    run = evaluate_base_batch_conflict_run(graph)
    results = by_name(run.checks)
    assert results["batch declared path syntax"].status == Status.MANUAL_REVIEW
    assert results["batch forbidden path conflict"].status == Status.FAIL
    assert results["batch forbidden path conflict"].evidence == [
        "affected_node=a; forbidden_node=b; path=production/secrets.txt; pattern=production"
    ]
    assert run.malformed_path_node_ids == ("a", "b")
    assert run.forbidden_crossings == (
        ForbiddenPathCrossing("a", "b", "production/secrets.txt", "production"),
    )


def test_differing_owners_sources_and_missing_metadata_are_preserved():
    graph = build_issue_batch_graph(
        [
            node("a", owner="Integration Manager", source="GitHub"),
            node("b", owner="QA / Test Agent", source="Notion"),
            node("c", owner=None, source=None),
        ]
    )
    run = evaluate_base_batch_conflict_run(graph)
    results = by_name(run.checks)
    assert results["batch owner compatibility"].status == Status.MANUAL_REVIEW
    assert results["batch source-of-truth compatibility"].status == Status.MANUAL_REVIEW
    assert results["batch required metadata"].evidence == [
        "node=c; missing=owner",
        "node=c; missing=source_of_truth",
    ]
    assert run.owner_conflict_node_ids == ("a", "b")
    assert run.source_of_truth_conflict_node_ids == ("a", "b")
    assert run.missing_owner_node_ids == ("c",)
    assert run.missing_source_of_truth_node_ids == ("c",)


def test_single_nonempty_owner_or_source_is_not_a_conflict():
    graph = build_issue_batch_graph(
        [node("a", owner="A", source="GitHub"), node("b", owner=None, source=None)]
    )
    run = evaluate_base_batch_conflict_run(graph)
    assert run.owner_conflict_node_ids == ()
    assert run.source_of_truth_conflict_node_ids == ()
    assert run.missing_owner_node_ids == ("b",)
    assert run.missing_source_of_truth_node_ids == ("b",)


def test_empty_and_single_complete_graphs_pass_all_checks_and_have_empty_facts():
    for graph in (IssueBatchGraph(), build_issue_batch_graph([node("a")])):
        run = evaluate_base_batch_conflict_run(graph)
        assert len(run.checks) == 7
        assert all(result.status == Status.PASS for result in run.checks)
        assert run.malformed_path_node_ids == ()
        assert run.sequencing_pairs == ()
        assert run.forbidden_crossings == ()
        assert run.owner_conflict_node_ids == ()
        assert run.source_of_truth_conflict_node_ids == ()
        assert run.missing_owner_node_ids == ()
        assert run.missing_source_of_truth_node_ids == ()


def test_result_evidence_and_structured_facts_are_deterministic():
    forward = build_issue_batch_graph(
        [
            node("b", paths=("src/b.py", "shared"), owner="B", source="Notion"),
            node("a", paths=("shared/a.py",), owner="A", source="GitHub"),
        ]
    )
    reverse = build_issue_batch_graph(reversed(forward.nodes))
    assert evaluate_base_batch_conflict_run(forward) == evaluate_base_batch_conflict_run(reverse)


def test_batch_conflict_run_defensively_copies_check_evidence():
    source = CheckResult("example", Status.WARN, "example", ["original"])
    run = BatchConflictRun(
        checks=(source,),
        malformed_path_node_ids=(),
        sequencing_pairs=(),
        forbidden_crossings=(),
        owner_conflict_node_ids=(),
        source_of_truth_conflict_node_ids=(),
        missing_owner_node_ids=(),
        missing_source_of_truth_node_ids=(),
    )
    source.evidence.append("mutated")
    assert run.checks[0].evidence == ["original"]
    assert run.checks[0] is not source


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
    evaluate_base_batch_conflict_run(graph)
    assert repr(graph) == before


def test_wrong_graph_type_fails_closed():
    with pytest.raises(TypeError, match="graph must be an IssueBatchGraph"):
        evaluate_base_batch_conflict_run(object())
    with pytest.raises(TypeError, match="graph must be an IssueBatchGraph"):
        evaluate_base_batch_conflicts(object())
