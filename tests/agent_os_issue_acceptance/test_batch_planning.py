import ast
import inspect
import socket
import subprocess

import pytest

import scripts.agent_os_issue_acceptance as issue_acceptance
from scripts.agent_os_issue_acceptance import batch_planning
from scripts.agent_os_issue_acceptance.batch_checks import (
    BatchConflictRun,
    evaluate_base_batch_conflict_run,
)
from scripts.agent_os_issue_acceptance.batch_extensions import GraphCheckRun
from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
    build_issue_batch_graph,
)
from scripts.agent_os_issue_acceptance.batch_planning import (
    BatchPlanningResult,
    PlanningClassification,
    evaluate_batch_plan,
)
from scripts.agent_os_issue_acceptance.models import CheckResult
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome


def node(
    node_id,
    *,
    readiness=ReadinessOutcome.READY,
    paths=(),
    forbidden=(),
    dependencies=(),
    owner="Integration Manager",
    source="GitHub",
    entity_id=None,
):
    return IssueBatchNode(
        node_id=node_id,
        readiness=readiness,
        owner=owner,
        source_of_truth=source,
        affected_paths=tuple(paths),
        forbidden_paths=tuple(forbidden),
        dependency_ids=tuple(dependencies),
        entity_id=entity_id,
    )


def cohort_for(result, node_id):
    matches = [cohort for cohort in result.cohorts if node_id in cohort.node_ids]
    assert len(matches) == 1
    return matches[0]


def test_public_api_accepts_only_one_graph_input_and_fails_closed():
    assert tuple(inspect.signature(evaluate_batch_plan).parameters) == ("graph",)
    with pytest.raises(TypeError, match="graph must be an IssueBatchGraph"):
        evaluate_batch_plan(object())


def test_empty_graph_needs_decision_and_cannot_override_safety_fields():
    result = evaluate_batch_plan(IssueBatchGraph())
    assert result.overall_classification is PlanningClassification.NEEDS_DECISION
    assert result.cohorts == ()
    assert result.batch_reason_codes == ("empty-supplied-graph",)
    assert result.planning_scope == "supplied-graph-only"
    assert result.execution_authorized is False

    with pytest.raises(TypeError):
        BatchPlanningResult(
            supplied_node_ids=(),
            overall_classification=PlanningClassification.NEEDS_DECISION,
            cohorts=(),
            planning_scope="other",
        )
    with pytest.raises(TypeError):
        BatchPlanningResult(
            supplied_node_ids=(),
            overall_classification=PlanningClassification.NEEDS_DECISION,
            cohorts=(),
            execution_authorized=True,
        )


def test_clean_nodes_form_one_sorted_parallel_candidate_cohort():
    graph = build_issue_batch_graph([node("b"), node("a")])
    result = evaluate_batch_plan(graph)
    assert result.supplied_node_ids == ("a", "b")
    assert result.overall_classification is PlanningClassification.PARALLEL_CANDIDATE
    assert len(result.cohorts) == 1
    assert result.cohorts[0].node_ids == ("a", "b")
    assert result.cohorts[0].reason_codes == (
        "covered-no-deterministic-conflict",
    )


def test_mixed_blocked_sequencing_and_parallel_results_do_not_spread():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("production/secrets.txt",)),
            node(
                "b",
                paths=("production",),
                forbidden=("production/*.txt",),
            ),
            node("c", paths=("docs/readme.md",)),
        ]
    )
    result = evaluate_batch_plan(graph)
    assert cohort_for(result, "a").classification is PlanningClassification.BLOCKED
    assert (
        cohort_for(result, "b").classification
        is PlanningClassification.SEQUENCING_REVIEW
    )
    assert (
        cohort_for(result, "c").classification
        is PlanningClassification.PARALLEL_CANDIDATE
    )
    assert result.overall_classification is PlanningClassification.BLOCKED
    assert "forbidden-path-crossing" in cohort_for(result, "a").reason_codes
    assert "path-overlap" in cohort_for(result, "b").reason_codes


def test_needs_decision_does_not_spread_across_a_path_overlap():
    graph = build_issue_batch_graph(
        [
            node("a", paths=("src",), owner=None),
            node("b", paths=("src/tool.py",)),
            node("c", paths=("docs",)),
        ]
    )
    result = evaluate_batch_plan(graph)
    assert (
        cohort_for(result, "a").classification
        is PlanningClassification.NEEDS_DECISION
    )
    assert (
        cohort_for(result, "b").classification
        is PlanningClassification.SEQUENCING_REVIEW
    )
    assert (
        cohort_for(result, "c").classification
        is PlanningClassification.PARALLEL_CANDIDATE
    )


def test_resolved_dependencies_form_deterministic_sequencing_components():
    graph = build_issue_batch_graph(
        [
            node("a", dependencies=("b",)),
            node("b", dependencies=("c",)),
            node("c"),
            node("d"),
        ]
    )
    result = evaluate_batch_plan(graph)
    sequencing = cohort_for(result, "a")
    assert sequencing.node_ids == ("a", "b", "c")
    assert sequencing.classification is PlanningClassification.SEQUENCING_REVIEW
    assert sequencing.dependency_pairs == (("a", "b"), ("b", "c"))
    assert cohort_for(result, "d").classification is PlanningClassification.PARALLEL_CANDIDATE


def test_unresolved_dependency_affects_only_the_supplied_source():
    graph = build_issue_batch_graph(
        [node("a", dependencies=("missing",)), node("b")]
    )
    result = evaluate_batch_plan(graph)
    source = cohort_for(result, "a")
    assert source.classification is PlanningClassification.NEEDS_DECISION
    assert source.dependency_pairs == (("a", "missing"),)
    assert "missing" not in result.supplied_node_ids
    assert cohort_for(result, "b").classification is PlanningClassification.PARALLEL_CANDIDATE


def test_self_dependencies_and_disjoint_cycles_are_stable():
    graph = build_issue_batch_graph(
        [
            node("a", dependencies=("a",)),
            node("b", dependencies=("c",)),
            node("c", dependencies=("b",)),
            node("d", dependencies=("e",)),
            node("e", dependencies=("d",)),
            node("f"),
        ]
    )
    result = evaluate_batch_plan(graph)
    assert result.cycle_node_groups == (("b", "c"), ("d", "e"))
    for node_id in ("a", "b", "c", "d", "e"):
        assert (
            cohort_for(result, node_id).classification
            is PlanningClassification.NEEDS_DECISION
        )
    assert "self-dependency" in cohort_for(result, "a").reason_codes
    assert "dependency-cycle" in cohort_for(result, "b").reason_codes
    assert cohort_for(result, "f").classification is PlanningClassification.PARALLEL_CANDIDATE


def test_identity_quarantine_preserves_unrelated_candidates():
    graph = build_issue_batch_graph(
        [
            node("a", entity_id="same"),
            node("b", entity_id="same"),
            node("c", entity_id="other"),
        ]
    )
    result = evaluate_batch_plan(graph)
    for node_id in ("a", "b"):
        cohort = cohort_for(result, node_id)
        assert cohort.classification is PlanningClassification.NEEDS_DECISION
        assert "identity-quarantine" in cohort.reason_codes
    assert cohort_for(result, "c").classification is PlanningClassification.PARALLEL_CANDIDATE


def test_report_text_is_not_a_planning_input(monkeypatch):
    graph = build_issue_batch_graph(
        [node("a", paths=("src",)), node("b", paths=("src/tool.py",))]
    )
    expected = evaluate_batch_plan(graph)
    original = evaluate_base_batch_conflict_run(graph)
    changed_checks = tuple(
        CheckResult(
            name=f"changed-{index}",
            status=check.status,
            message="changed message",
            evidence=["changed evidence"],
        )
        for index, check in enumerate(original.checks)
    )
    changed = BatchConflictRun(
        checks=changed_checks,
        malformed_path_node_ids=original.malformed_path_node_ids,
        sequencing_pairs=original.sequencing_pairs,
        forbidden_crossings=original.forbidden_crossings,
        owner_conflict_node_ids=original.owner_conflict_node_ids,
        source_of_truth_conflict_node_ids=original.source_of_truth_conflict_node_ids,
        missing_owner_node_ids=original.missing_owner_node_ids,
        missing_source_of_truth_node_ids=original.missing_source_of_truth_node_ids,
    )
    monkeypatch.setattr(
        batch_planning,
        "evaluate_base_batch_conflict_run",
        lambda supplied: changed,
    )
    assert evaluate_batch_plan(graph) == expected
    changed_checks[0].evidence.append("later mutation")
    assert evaluate_batch_plan(graph) == expected


def test_graph_check_failure_routes_the_supplied_graph_to_review(monkeypatch):
    graph = build_issue_batch_graph([node("a"), node("b")])
    failed_run = GraphCheckRun(
        checks=(),
        quarantined_node_ids=(),
        inspected_node_ids=(),
        inspected_dependency_pairs=(),
        failed_check_ids=("broken.check",),
    )
    monkeypatch.setattr(
        batch_planning,
        "_run_canonical_graph_checks",
        lambda supplied: failed_run,
    )
    result = evaluate_batch_plan(graph)
    assert result.batch_reason_codes == (
        "graph-check-failure",
        "incomplete-supplied-graph-coverage",
    )
    assert all(
        cohort.classification is PlanningClassification.NEEDS_DECISION
        for cohort in result.cohorts
    )


def test_every_supplied_node_appears_exactly_once_and_results_are_deterministic():
    forward = build_issue_batch_graph(
        [
            node("c"),
            node("a", dependencies=("b",)),
            node("b"),
        ]
    )
    reverse = build_issue_batch_graph(reversed(forward.nodes))
    first = evaluate_batch_plan(forward)
    second = evaluate_batch_plan(reverse)
    assert first == second
    observed = [node_id for cohort in first.cohorts for node_id in cohort.node_ids]
    assert sorted(observed) == list(first.supplied_node_ids)
    assert len(observed) == len(set(observed))


def test_package_exports_only_the_approved_planning_boundary():
    expected = {
        "BatchPlanningResult",
        "PlanningClassification",
        "PlanningCohort",
        "evaluate_batch_plan",
    }
    assert expected <= set(issue_acceptance.__all__)
    assert "_resolved_dependency_inspection" not in issue_acceptance.__all__


def test_planning_module_has_no_scheduler_import():
    tree = ast.parse(inspect.getsource(batch_planning))
    imported = []
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            imported.extend(alias.name for alias in item.names)
        elif isinstance(item, ast.ImportFrom) and item.module:
            imported.append(item.module)
    assert not any("workflow" in name.lower() for name in imported)


def test_graph_is_unchanged_and_evaluation_is_offline(monkeypatch):
    graph = build_issue_batch_graph(
        [node("a", paths=("src",)), node("b", paths=("src/b.py",))]
    )
    before = repr(graph)
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: pytest.fail("network access"),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("subprocess access"),
    )
    evaluate_batch_plan(graph)
    assert repr(graph) == before
