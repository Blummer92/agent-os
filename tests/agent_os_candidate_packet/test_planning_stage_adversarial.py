from __future__ import annotations

import json
from dataclasses import replace
from itertools import permutations

import pytest

from scripts.agent_os_candidate_packet.planning_stage import (
    reconstruct_scheduler_planning_handoff,
)
from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
    build_issue_batch_graph,
    load_issue_batch_fixture,
)
from scripts.agent_os_issue_acceptance.batch_planning import (
    BatchPlanningResult,
    PlanningClassification,
    PlanningCohort,
    evaluate_batch_plan,
)
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome
from scripts.agent_os_issue_acceptance.scheduler_handoff import (
    HandoffCohort,
    HandoffValidationOutcome,
    SchedulerPlanningHandoff,
    compute_graph_digest,
    compute_handoff_digest,
    compute_planning_result_digest,
    serialize_scheduler_planning_handoff,
    validate_scheduler_planning_handoff,
)

_SHA40_A = "a" * 40
_SHA40_B = "b" * 40


def _node(node_id: str, *, dependencies=(), readiness=ReadinessOutcome.READY):
    return IssueBatchNode(
        node_id=node_id,
        readiness=readiness,
        readiness_evidence=("fixture:ready",),
        owner="QA / Test Agent",
        source_of_truth="GitHub",
        affected_paths=(f"tests/{node_id}.py",),
        forbidden_paths=(".github/workflows/**",),
        dependency_ids=dependencies,
        entity_id=f"entity:{node_id}",
        provenance=("issue:860", f"node:{node_id}"),
    )


def _handoff_for(graph: IssueBatchGraph) -> SchedulerPlanningHandoff:
    planning = evaluate_batch_plan(graph)
    cohorts = tuple(
        HandoffCohort(
            node_ids=cohort.node_ids,
            classification=cohort.classification.value,
            reason_codes=cohort.reason_codes,
        )
        for cohort in planning.cohorts
    )
    payload = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": _SHA40_A,
        "repository": "Blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": _SHA40_B,
        "supplied_node_ids": planning.supplied_node_ids,
        "graph_digest": compute_graph_digest(graph),
        "planning_result_digest": compute_planning_result_digest(planning),
        "cohort_summaries": cohorts,
        "planning_scope": "supplied-graph-only",
        "execution_authorized": False,
        "created_at": "2026-08-08T02:00:00Z",
    }
    return SchedulerPlanningHandoff(
        contract_version=payload["contract_version"],
        planning_result_version=payload["planning_result_version"],
        evaluator_commit_sha=payload["evaluator_commit_sha"],
        repository=payload["repository"],
        base_branch=payload["base_branch"],
        evaluated_repository_sha=payload["evaluated_repository_sha"],
        supplied_node_ids=payload["supplied_node_ids"],
        graph_digest=payload["graph_digest"],
        planning_result_digest=payload["planning_result_digest"],
        cohort_summaries=cohorts,
        created_at=payload["created_at"],
        handoff_digest=compute_handoff_digest(payload),
    )


def _payload(handoff: SchedulerPlanningHandoff) -> dict[str, object]:
    return json.loads(serialize_scheduler_planning_handoff(handoff))


def test_resolved_and_unresolved_dependency_identities_preserve_direction() -> None:
    graph = build_issue_batch_graph(
        (_node("issue-b", dependencies=("issue-a", "issue-missing")), _node("issue-a"))
    )

    assert graph.resolved_dependencies == (("issue-b", "issue-a"),)
    assert graph.unresolved_dependencies == (("issue-b", "issue-missing"),)

    planning = evaluate_batch_plan(graph)
    assert planning.overall_classification is PlanningClassification.NEEDS_DECISION
    b_cohort = next(cohort for cohort in planning.cohorts if "issue-b" in cohort.node_ids)
    assert ("issue-b", "issue-a") in b_cohort.dependency_pairs
    assert ("issue-b", "issue-missing") in b_cohort.dependency_pairs
    assert "unresolved-dependency" in b_cohort.reason_codes
    assert planning.execution_authorized is False


def test_duplicate_node_ids_fail_before_a_graph_can_be_planned() -> None:
    with pytest.raises(ValueError, match="duplicate node_id"):
        build_issue_batch_graph((_node("issue-a"), _node("issue-a")))


@pytest.mark.parametrize("ordering", tuple(permutations(("issue-a", "issue-b", "issue-c"))))
def test_semantically_equivalent_node_order_has_identical_identities(ordering) -> None:
    nodes = {
        "issue-a": _node("issue-a"),
        "issue-b": _node("issue-b", dependencies=("issue-a",)),
        "issue-c": _node("issue-c", dependencies=("issue-b",)),
    }
    graph = build_issue_batch_graph(tuple(nodes[node_id] for node_id in ordering))
    planning = evaluate_batch_plan(graph)
    handoff = _handoff_for(graph)

    canonical_graph = build_issue_batch_graph(tuple(nodes.values()))
    canonical_planning = evaluate_batch_plan(canonical_graph)
    canonical_handoff = _handoff_for(canonical_graph)

    assert compute_graph_digest(graph) == compute_graph_digest(canonical_graph)
    assert compute_planning_result_digest(planning) == compute_planning_result_digest(
        canonical_planning
    )
    assert handoff.handoff_digest == canonical_handoff.handoff_digest
    assert serialize_scheduler_planning_handoff(handoff) == serialize_scheduler_planning_handoff(
        canonical_handoff
    )
    assert handoff.execution_authorized is False


def test_provenance_and_path_order_are_semantically_canonical() -> None:
    first = IssueBatchNode(
        node_id="issue-a",
        readiness=ReadinessOutcome.READY,
        readiness_evidence=("z", "a"),
        owner="QA / Test Agent",
        source_of_truth="GitHub",
        affected_paths=("tests/z.py", "tests/a.py"),
        forbidden_paths=("production/**", ".github/workflows/**"),
        dependency_ids=("issue-c", "issue-b"),
        entity_id="entity:a",
        provenance=("z", "a"),
    )
    second = IssueBatchNode(
        node_id="issue-a",
        readiness=ReadinessOutcome.READY,
        readiness_evidence=("a", "z"),
        owner="QA / Test Agent",
        source_of_truth="GitHub",
        affected_paths=("tests/a.py", "tests/z.py"),
        forbidden_paths=(".github/workflows/**", "production/**"),
        dependency_ids=("issue-b", "issue-c"),
        entity_id="entity:a",
        provenance=("a", "z"),
    )

    assert compute_graph_digest(build_issue_batch_graph((first,))) == compute_graph_digest(
        build_issue_batch_graph((second,))
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("contract_version", "9.9.9", "unsupported-contract-version"),
        ("planning_result_version", "9.9.9", "unsupported-planning-result-version"),
        ("repository", "bad/repository/shape", "malformed-field:repository"),
        ("base_branch", "refs/heads/main", "malformed-field:base_branch"),
        ("evaluator_commit_sha", "abc", "malformed-field:evaluator_commit_sha"),
        ("evaluated_repository_sha", "abc", "malformed-field:evaluated_repository_sha"),
        ("created_at", "not-a-timestamp", "malformed-field:created_at"),
        ("cohort_summaries", "not-a-cohort-list", "malformed-field:cohort_summaries"),
    ],
)
def test_malformed_handoff_fields_fail_closed(field, value, reason) -> None:
    payload = _payload(_handoff_for(build_issue_batch_graph((_node("issue-a"),))))
    payload[field] = value

    result = validate_scheduler_planning_handoff(payload)

    assert result.outcome is HandoffValidationOutcome.INVALID
    assert reason in result.reason_codes
    assert result.execution_authorized is False


@pytest.mark.parametrize("missing", ("repository", "graph_digest", "planning_result_digest", "cohort_summaries"))
def test_missing_required_payload_fields_fail_closed(missing) -> None:
    payload = _payload(_handoff_for(build_issue_batch_graph((_node("issue-a"),))))
    payload.pop(missing)

    result = validate_scheduler_planning_handoff(payload)

    assert result.outcome is HandoffValidationOutcome.INVALID
    assert f"missing-field:{missing}" in result.reason_codes
    assert result.execution_authorized is False


def test_unknown_payload_fields_fail_closed_with_bounded_diagnostic() -> None:
    payload = _payload(_handoff_for(build_issue_batch_graph((_node("issue-a"),))))
    payload.update({f"unknown-{index}": index for index in range(32)})

    result = validate_scheduler_planning_handoff(payload)

    assert result.outcome is HandoffValidationOutcome.INVALID
    assert result.reason_codes == ("unknown-field",)
    assert result.execution_authorized is False


def test_graph_digest_tampering_is_detectable_against_canonical_graph() -> None:
    graph = build_issue_batch_graph((_node("issue-a"), _node("issue-b")))
    handoff = _handoff_for(graph)
    tampered = replace(handoff, graph_digest="0" * 64)

    assert tampered.graph_digest != compute_graph_digest(graph)
    assert tampered.handoff_digest != compute_handoff_digest(_payload(tampered))


def test_planning_result_digest_tampering_is_detectable_against_canonical_result() -> None:
    graph = build_issue_batch_graph((_node("issue-a"), _node("issue-b")))
    planning = evaluate_batch_plan(graph)
    handoff = _handoff_for(graph)
    tampered = replace(handoff, planning_result_digest="0" * 64)

    assert tampered.planning_result_digest != compute_planning_result_digest(planning)
    assert tampered.handoff_digest != compute_handoff_digest(_payload(tampered))


def test_handoff_digest_tampering_fails_reconstruction() -> None:
    payload = _payload(_handoff_for(build_issue_batch_graph((_node("issue-a"),))))
    payload["handoff_digest"] = "0" * 64

    with pytest.raises(ValueError, match="invalid SchedulerPlanningHandoff"):
        reconstruct_scheduler_planning_handoff(payload)


def test_serialization_reconstruction_round_trip_preserves_identity() -> None:
    handoff = _handoff_for(
        build_issue_batch_graph((_node("issue-b", dependencies=("issue-a",)), _node("issue-a")))
    )

    reconstructed = reconstruct_scheduler_planning_handoff(
        serialize_scheduler_planning_handoff(handoff)
    )

    assert reconstructed == handoff
    assert reconstructed.graph_digest == handoff.graph_digest
    assert reconstructed.planning_result_digest == handoff.planning_result_digest
    assert reconstructed.handoff_digest == handoff.handoff_digest
    assert reconstructed.execution_authorized is False


def test_exact_cohort_coverage_rejects_duplicate_or_missing_nodes() -> None:
    with pytest.raises(ValueError, match="each supplied node exactly once"):
        BatchPlanningResult(
            supplied_node_ids=("issue-a", "issue-b"),
            overall_classification=PlanningClassification.PARALLEL_CANDIDATE,
            cohorts=(
                PlanningCohort(
                    node_ids=("issue-a", "issue-a"),
                    classification=PlanningClassification.PARALLEL_CANDIDATE,
                    reason_codes=("covered-no-deterministic-conflict",),
                ),
            ),
        )


def test_blocked_and_needs_decision_remain_distinct_and_non_authorizing() -> None:
    graph = build_issue_batch_graph(
        (
            _node("issue-blocked", readiness=ReadinessOutcome.BLOCKED),
            _node("issue-review", dependencies=("missing",)),
        )
    )
    planning = evaluate_batch_plan(graph)
    by_node = {
        node_id: cohort.classification
        for cohort in planning.cohorts
        for node_id in cohort.node_ids
    }

    assert by_node["issue-blocked"] is PlanningClassification.BLOCKED
    assert by_node["issue-review"] is PlanningClassification.NEEDS_DECISION
    assert planning.overall_classification is PlanningClassification.BLOCKED
    assert planning.execution_authorized is False


def test_fixture_loader_rejects_missing_unknown_and_malformed_payloads() -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        load_issue_batch_fixture(({"readiness": "ready"},))
    with pytest.raises(ValueError, match="unknown fields"):
        load_issue_batch_fixture(
            ({"node_id": "issue-a", "readiness": "ready", "surprise": True},)
        )
    with pytest.raises(ValueError, match="non-empty string"):
        load_issue_batch_fixture(({"node_id": " ", "readiness": "ready"},))


def test_repeated_equivalent_input_is_deterministic_and_side_effect_free() -> None:
    nodes = (_node("issue-b", dependencies=("issue-a",)), _node("issue-a"))

    first_graph = build_issue_batch_graph(nodes)
    second_graph = build_issue_batch_graph(nodes)
    first_plan = evaluate_batch_plan(first_graph)
    second_plan = evaluate_batch_plan(second_graph)
    first_handoff = _handoff_for(first_graph)
    second_handoff = _handoff_for(second_graph)

    assert first_graph == second_graph
    assert first_plan == second_plan
    assert serialize_scheduler_planning_handoff(first_handoff) == serialize_scheduler_planning_handoff(
        second_handoff
    )
    assert first_plan.execution_authorized is False
    assert first_handoff.execution_authorized is False
