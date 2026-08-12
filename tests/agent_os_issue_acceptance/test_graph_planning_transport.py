import json
import socket
import subprocess

import pytest

from scripts.agent_os_issue_acceptance import (
    BatchPlanningResult,
    IssueBatchNode,
    PlanningClassification,
    PlanningCohort,
    build_issue_batch_graph,
    compute_graph_digest,
    compute_planning_result_digest,
    evaluate_batch_plan,
    reconstruct_batch_planning_result,
    reconstruct_issue_batch_graph,
    serialize_batch_planning_result,
    serialize_issue_batch_graph,
)
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome


def _node(node_id: str, *, dependencies=()) -> IssueBatchNode:
    return IssueBatchNode(
        node_id=node_id,
        readiness=ReadinessOutcome.READY,
        readiness_evidence=("ready-evidence",),
        owner="Integration Manager",
        source_of_truth="GitHub",
        affected_paths=(f"scripts/{node_id}.py",),
        forbidden_paths=("production/**",),
        dependency_ids=tuple(dependencies),
        entity_id=f"entity-{node_id}",
        provenance=("fixture",),
    )


def _graph():
    return build_issue_batch_graph(
        [_node("a", dependencies=("b",)), _node("b"), _node("c")]
    )


def test_graph_transport_round_trip_is_byte_stable_and_digest_stable():
    graph = _graph()
    encoded = serialize_issue_batch_graph(graph)
    reconstructed = reconstruct_issue_batch_graph(encoded)

    assert reconstructed == graph
    assert serialize_issue_batch_graph(reconstructed) == encoded
    assert compute_graph_digest(reconstructed) == compute_graph_digest(graph)
    assert encoded == json.dumps(
        json.loads(encoded),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert not encoded.endswith(b"\n")


def test_graph_transport_rejects_unknown_missing_and_noncanonical_fields():
    payload = json.loads(serialize_issue_batch_graph(_graph()))

    unknown = dict(payload, surprise=True)
    with pytest.raises(ValueError, match="unknown fields: surprise"):
        reconstruct_issue_batch_graph(unknown)

    missing = dict(payload)
    missing.pop("nodes")
    with pytest.raises(ValueError, match="missing required fields: nodes"):
        reconstruct_issue_batch_graph(missing)

    reordered = dict(payload)
    reordered["nodes"] = list(reversed(reordered["nodes"]))
    with pytest.raises(ValueError, match="not canonical"):
        reconstruct_issue_batch_graph(reordered)


def test_graph_transport_rejects_noncanonical_text_and_bytes():
    encoded = serialize_issue_batch_graph(_graph())
    canonical_text = encoded.decode("utf-8")
    payload = json.loads(encoded)

    whitespace = canonical_text.replace("{", "{ ", 1)
    reordered = json.dumps(
        dict(reversed(list(payload.items()))),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    duplicate = canonical_text.replace('"nodes":', '"nodes":[],"nodes":', 1)

    for candidate in (whitespace, reordered, duplicate):
        with pytest.raises(ValueError, match="canonical"):
            reconstruct_issue_batch_graph(candidate)
        with pytest.raises(ValueError, match="canonical"):
            reconstruct_issue_batch_graph(candidate.encode("utf-8"))


def test_graph_transport_rejects_enum_collection_and_dependency_drift():
    payload = json.loads(serialize_issue_batch_graph(_graph()))

    malformed_enum = json.loads(json.dumps(payload))
    malformed_enum["nodes"][0]["readiness"] = "maybe"
    with pytest.raises(ValueError, match="readiness is unsupported"):
        reconstruct_issue_batch_graph(malformed_enum)

    malformed_array = json.loads(json.dumps(payload))
    malformed_array["nodes"][0]["affected_paths"] = "scripts/a.py"
    with pytest.raises(ValueError, match="affected_paths must be an array"):
        reconstruct_issue_batch_graph(malformed_array)

    drifted_dependencies = json.loads(json.dumps(payload))
    drifted_dependencies["resolved_dependencies"] = []
    with pytest.raises(ValueError, match="resolved_dependencies do not match"):
        reconstruct_issue_batch_graph(drifted_dependencies)


def test_graph_serializer_rejects_manually_inconsistent_public_graph():
    graph = _graph()
    tampered = type(graph)(
        nodes=graph.nodes,
        resolved_dependencies=(),
        unresolved_dependencies=graph.unresolved_dependencies,
    )
    with pytest.raises(ValueError, match="dependency evidence"):
        serialize_issue_batch_graph(tampered)


def test_planning_transport_round_trip_is_byte_stable_and_digest_stable():
    result = evaluate_batch_plan(_graph())
    encoded = serialize_batch_planning_result(result)
    reconstructed = reconstruct_batch_planning_result(encoded)

    assert reconstructed == result
    assert serialize_batch_planning_result(reconstructed) == encoded
    assert compute_planning_result_digest(reconstructed) == compute_planning_result_digest(
        result
    )
    payload = json.loads(encoded)
    assert payload["planning_scope"] == "supplied-graph-only"
    assert payload["execution_authorized"] is False
    assert not encoded.endswith(b"\n")


def test_planning_transport_rejects_unknown_missing_and_authority_drift():
    payload = json.loads(serialize_batch_planning_result(evaluate_batch_plan(_graph())))

    unknown = dict(payload, surprise=True)
    with pytest.raises(ValueError, match="unknown fields: surprise"):
        reconstruct_batch_planning_result(unknown)

    missing = dict(payload)
    missing.pop("cohorts")
    with pytest.raises(ValueError, match="missing required fields: cohorts"):
        reconstruct_batch_planning_result(missing)

    authority = dict(payload, execution_authorized=True)
    with pytest.raises(ValueError, match="execution_authorized must remain false"):
        reconstruct_batch_planning_result(authority)

    scope = dict(payload, planning_scope="repository-wide")
    with pytest.raises(ValueError, match="planning_scope must be supplied-graph-only"):
        reconstruct_batch_planning_result(scope)


def test_planning_transport_rejects_noncanonical_text_and_bytes():
    encoded = serialize_batch_planning_result(evaluate_batch_plan(_graph()))
    canonical_text = encoded.decode("utf-8")
    payload = json.loads(encoded)

    whitespace = canonical_text.replace("{", "{ ", 1)
    reordered = json.dumps(
        dict(reversed(list(payload.items()))),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    duplicate = canonical_text.replace(
        '"batch_reason_codes":',
        '"batch_reason_codes":[],"batch_reason_codes":',
        1,
    )

    for candidate in (whitespace, reordered, duplicate):
        with pytest.raises(ValueError, match="canonical"):
            reconstruct_batch_planning_result(candidate)
        with pytest.raises(ValueError, match="canonical"):
            reconstruct_batch_planning_result(candidate.encode("utf-8"))


def test_planning_transport_rejects_malformed_enum_and_collection_shapes():
    payload = json.loads(serialize_batch_planning_result(evaluate_batch_plan(_graph())))

    malformed_overall = json.loads(json.dumps(payload))
    malformed_overall["overall_classification"] = "unknown"
    with pytest.raises(ValueError, match="overall_classification is unsupported"):
        reconstruct_batch_planning_result(malformed_overall)

    malformed_cohort = json.loads(json.dumps(payload))
    malformed_cohort["cohorts"][0]["classification"] = "unknown"
    with pytest.raises(ValueError, match="classification is unsupported"):
        reconstruct_batch_planning_result(malformed_cohort)

    malformed_pairs = json.loads(json.dumps(payload))
    malformed_pairs["cohorts"][0]["dependency_pairs"] = ["a", "b"]
    with pytest.raises(ValueError, match="two-string array"):
        reconstruct_batch_planning_result(malformed_pairs)


def test_planning_transport_rejects_coverage_and_order_drift():
    payload = json.loads(serialize_batch_planning_result(evaluate_batch_plan(_graph())))

    reversed_ids = json.loads(json.dumps(payload))
    reversed_ids["supplied_node_ids"] = list(reversed(reversed_ids["supplied_node_ids"]))
    with pytest.raises(ValueError, match="cohorts must contain each supplied node exactly once"):
        reconstruct_batch_planning_result(reversed_ids)

    duplicate_ids = json.loads(json.dumps(payload))
    duplicate_ids["supplied_node_ids"].append(duplicate_ids["supplied_node_ids"][0])
    with pytest.raises(ValueError, match="cohorts must contain each supplied node exactly once"):
        reconstruct_batch_planning_result(duplicate_ids)

    reversed_cohorts = json.loads(json.dumps(payload))
    reversed_cohorts["cohorts"] = list(reversed(reversed_cohorts["cohorts"]))
    with pytest.raises(ValueError, match="not canonical"):
        reconstruct_batch_planning_result(reversed_cohorts)

    nested = json.loads(json.dumps(payload))
    cohort = nested["cohorts"][0]
    cohort["reason_codes"] = list(reversed(cohort["reason_codes"]))
    if len(cohort["reason_codes"]) < 2:
        cohort["reason_codes"].append("zzz-noncanonical-order")
        cohort["reason_codes"] = list(reversed(cohort["reason_codes"]))
    with pytest.raises(ValueError, match="not canonical"):
        reconstruct_batch_planning_result(nested)


def test_planning_serializer_rejects_noncanonical_nested_ordering():
    canonical = evaluate_batch_plan(_graph())
    reordered = BatchPlanningResult(
        supplied_node_ids=canonical.supplied_node_ids,
        overall_classification=canonical.overall_classification,
        cohorts=tuple(reversed(canonical.cohorts)),
        batch_reason_codes=canonical.batch_reason_codes,
        cycle_node_groups=canonical.cycle_node_groups,
    )
    with pytest.raises(ValueError, match="not canonical"):
        serialize_batch_planning_result(reordered)


def test_transport_is_offline_and_never_invokes_runtime_capabilities(monkeypatch):
    graph = _graph()
    planning = evaluate_batch_plan(graph)

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

    assert reconstruct_issue_batch_graph(serialize_issue_batch_graph(graph)) == graph
    assert (
        reconstruct_batch_planning_result(serialize_batch_planning_result(planning))
        == planning
    )


def test_planning_transport_preserves_all_classification_values():
    # Constructed directly (not planner-derived) so this test exercises pure
    # transport fidelity for every PlanningClassification member, independent
    # of what the planner itself would ever classify a real graph as.
    cohorts = (
        PlanningCohort(
            node_ids=("blocked-node",),
            classification=PlanningClassification.BLOCKED,
            reason_codes=("readiness-blocked",),
        ),
        PlanningCohort(
            node_ids=("needs-decision-node",),
            classification=PlanningClassification.NEEDS_DECISION,
            reason_codes=("readiness-needs-decision",),
        ),
        PlanningCohort(
            node_ids=("sequencing-a", "sequencing-b"),
            classification=PlanningClassification.SEQUENCING_REVIEW,
            reason_codes=("path-overlap",),
            sequencing_pairs=(("sequencing-a", "sequencing-b"),),
        ),
        PlanningCohort(
            node_ids=("parallel-node",),
            classification=PlanningClassification.PARALLEL_CANDIDATE,
            reason_codes=("covered-no-deterministic-conflict",),
        ),
    )
    supplied_node_ids = tuple(
        sorted(node_id for cohort in cohorts for node_id in cohort.node_ids)
    )
    result = BatchPlanningResult(
        supplied_node_ids=supplied_node_ids,
        overall_classification=PlanningClassification.BLOCKED,
        cohorts=cohorts,
    )
    reconstructed = reconstruct_batch_planning_result(
        serialize_batch_planning_result(result)
    )

    assert reconstructed == result
    assert reconstructed.overall_classification is PlanningClassification.BLOCKED
    assert {
        cohort.classification for cohort in reconstructed.cohorts
    } == set(PlanningClassification)
