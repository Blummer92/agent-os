from __future__ import annotations

import dataclasses
import json
from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance import (
    HandoffCohort,
    HandoffValidationOutcome,
    IssueBatchGraph,
    IssueBatchNode,
    PlanningClassification,
    PlanningCohort,
    ReadinessOutcome,
    SchedulerPlanningHandoff,
    compute_graph_digest,
    compute_handoff_digest,
    compute_planning_result_digest,
    serialize_scheduler_planning_handoff,
    validate_scheduler_planning_handoff,
    with_computed_handoff_digest,
)
from scripts.agent_os_issue_acceptance.batch_planning import BatchPlanningResult


SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _graph(*, owner: str | None = "Integration Manager") -> IssueBatchGraph:
    return IssueBatchGraph(
        nodes=(
            IssueBatchNode(
                node_id="331",
                readiness=ReadinessOutcome.READY,
                readiness_evidence=("status:ready", "issue-readiness:ready"),
                owner=owner,
                source_of_truth="GitHub",
                affected_paths=("scripts/z.py", "scripts/a.py"),
                forbidden_paths=("08_Tooling/workflow-scheduler/",),
                dependency_ids=("325",),
                entity_id="issue:331",
                provenance=("issue-331", "adr-0002"),
            ),
        ),
        resolved_dependencies=(),
        unresolved_dependencies=(("331", "325"),),
    )


def _planning_result(*, reason: str = "covered-no-deterministic-conflict") -> BatchPlanningResult:
    return BatchPlanningResult(
        supplied_node_ids=("331",),
        overall_classification=PlanningClassification.PARALLEL_CANDIDATE,
        cohorts=(
            PlanningCohort(
                node_ids=("331",),
                classification=PlanningClassification.PARALLEL_CANDIDATE,
                reason_codes=(reason,),
            ),
        ),
    )


def _handoff(**changes) -> SchedulerPlanningHandoff:
    base = SchedulerPlanningHandoff(
        contract_version="0.2.0",
        planning_result_version="0.1.0",
        evaluator_commit_sha=SHA_A,
        repository="Blummer92/agent-os",
        base_branch="main",
        evaluated_repository_sha=SHA_B,
        supplied_node_ids=("331",),
        graph_digest=compute_graph_digest(_graph()),
        planning_result_digest=compute_planning_result_digest(_planning_result()),
        cohort_summaries=(
            HandoffCohort(
                node_ids=("331",),
                classification="parallel-candidate",
                reason_codes=("covered-no-deterministic-conflict",),
            ),
        ),
        planning_scope="supplied-graph-only",
        execution_authorized=False,
        created_at="2026-07-19T18:00:00Z",
        handoff_digest="",
    )
    return replace(base, **changes)


def _valid_handoff(**changes) -> SchedulerPlanningHandoff:
    return with_computed_handoff_digest(_handoff(**changes))


def test_canonical_serialization_matches_exact_expected_bytes() -> None:
    handoff = _valid_handoff()

    expected = json.dumps(
        {
            "contract_version": "0.2.0",
            "planning_result_version": "0.1.0",
            "evaluator_commit_sha": SHA_A,
            "repository": "Blummer92/agent-os",
            "base_branch": "main",
            "evaluated_repository_sha": SHA_B,
            "supplied_node_ids": ["331"],
            "graph_digest": handoff.graph_digest,
            "planning_result_digest": handoff.planning_result_digest,
            "cohort_summaries": [
                {
                    "node_ids": ["331"],
                    "classification": "parallel-candidate",
                    "reason_codes": ["covered-no-deterministic-conflict"],
                }
            ],
            "planning_scope": "supplied-graph-only",
            "execution_authorized": False,
            "created_at": "2026-07-19T18:00:00Z",
            "handoff_digest": handoff.handoff_digest,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert serialize_scheduler_planning_handoff(handoff) == expected
    assert not expected.endswith(b"\n")


def test_dictionary_insertion_order_does_not_change_validation() -> None:
    handoff = _valid_handoff()
    payload = dataclasses.asdict(handoff)
    reversed_payload = dict(reversed(tuple(payload.items())))

    result = validate_scheduler_planning_handoff(reversed_payload)

    assert result.outcome is HandoffValidationOutcome.NEEDS_DECISION
    assert result.reason_codes == ("current-state-revalidation-required",)


def test_equivalent_graph_inputs_produce_identical_digest() -> None:
    left = _graph()
    node = left.nodes[0]
    right = IssueBatchGraph(
        nodes=(
            IssueBatchNode(
                node_id=node.node_id,
                readiness=node.readiness,
                readiness_evidence=tuple(reversed(node.readiness_evidence)),
                owner=node.owner,
                source_of_truth=node.source_of_truth,
                affected_paths=tuple(reversed(node.affected_paths)),
                forbidden_paths=node.forbidden_paths,
                dependency_ids=node.dependency_ids,
                entity_id=node.entity_id,
                provenance=tuple(reversed(node.provenance)),
            ),
        ),
        unresolved_dependencies=tuple(reversed(left.unresolved_dependencies)),
    )

    assert compute_graph_digest(left) == compute_graph_digest(right)


def test_changed_graph_field_changes_graph_digest() -> None:
    assert compute_graph_digest(_graph()) != compute_graph_digest(_graph(owner="QA / Test Agent"))


def test_changed_planning_result_field_changes_digest() -> None:
    assert compute_planning_result_digest(_planning_result()) != compute_planning_result_digest(
        _planning_result(reason="manual-review-required")
    )


def test_changed_envelope_field_changes_handoff_digest() -> None:
    handoff = _handoff()

    assert compute_handoff_digest(handoff) != compute_handoff_digest(
        replace(handoff, base_branch="release")
    )


def test_stored_handoff_digest_is_excluded_from_digest_input() -> None:
    handoff = _handoff(handoff_digest=DIGEST_A)

    assert compute_handoff_digest(handoff) == compute_handoff_digest(
        replace(handoff, handoff_digest=DIGEST_B)
    )


def test_graph_digest_represents_every_issue_batch_node_field() -> None:
    baseline = _graph()
    node = baseline.nodes[0]
    variants = (
        replace(node, readiness=ReadinessOutcome.BLOCKED),
        replace(node, readiness_evidence=("different",)),
        replace(node, owner="QA / Test Agent"),
        replace(node, source_of_truth="Notion"),
        replace(node, affected_paths=("different.py",)),
        replace(node, forbidden_paths=("different/",)),
        replace(node, dependency_ids=("999",)),
        replace(node, entity_id="issue:999"),
        replace(node, provenance=("different",)),
    )

    baseline_digest = compute_graph_digest(baseline)
    for variant in variants:
        graph = IssueBatchGraph(nodes=(variant,), unresolved_dependencies=baseline.unresolved_dependencies)
        assert compute_graph_digest(graph) != baseline_digest


def test_dependency_pairs_are_sorted_and_deduplicated() -> None:
    graph_a = IssueBatchGraph(
        nodes=_graph().nodes,
        resolved_dependencies=(("331", "325"), ("331", "325")),
        unresolved_dependencies=(("331", "999"), ("331", "999")),
    )
    graph_b = IssueBatchGraph(
        nodes=_graph().nodes,
        resolved_dependencies=(("331", "325"),),
        unresolved_dependencies=(("331", "999"),),
    )

    assert compute_graph_digest(graph_a) == compute_graph_digest(graph_b)


def test_none_and_empty_string_remain_distinct_in_graph_digest() -> None:
    none_graph = _graph(owner=None)
    empty_owner_node = object.__new__(IssueBatchNode)
    for field in dataclasses.fields(IssueBatchNode):
        object.__setattr__(empty_owner_node, field.name, getattr(none_graph.nodes[0], field.name))
    object.__setattr__(empty_owner_node, "owner", "")
    empty_graph = IssueBatchGraph(nodes=(empty_owner_node,), unresolved_dependencies=none_graph.unresolved_dependencies)

    assert compute_graph_digest(none_graph) != compute_graph_digest(empty_graph)


def test_cohorts_use_direct_classification_precedence() -> None:
    handoff = _handoff(
        supplied_node_ids=("a", "b", "c", "d"),
        cohort_summaries=(
            HandoffCohort(("d",), "parallel-candidate", ("d",)),
            HandoffCohort(("b",), "needs-decision", ("b",)),
            HandoffCohort(("c",), "sequencing-review", ("c",)),
            HandoffCohort(("a",), "blocked", ("a",)),
        ),
    )

    assert tuple(cohort.classification for cohort in handoff.cohort_summaries) == (
        "blocked",
        "needs-decision",
        "sequencing-review",
        "parallel-candidate",
    )


def test_supported_versions_are_structurally_valid_but_not_fresh() -> None:
    result = validate_scheduler_planning_handoff(_valid_handoff())

    assert result.outcome is HandoffValidationOutcome.NEEDS_DECISION
    assert result.reason_codes == ("current-state-revalidation-required",)


@pytest.mark.parametrize(
    ("field_name", "value", "reason"),
    (
        ("contract_version", "1.0.0", "unsupported-contract-version"),
        ("planning_result_version", "9.0.0", "unsupported-planning-result-version"),
        ("planning_scope", "all-open-issues", "invalid-planning-scope"),
        ("execution_authorized", True, "execution-authorized-must-be-false"),
        ("evaluator_commit_sha", "short", "malformed-evaluator-commit-sha"),
        ("evaluated_repository_sha", "short", "malformed-evaluated-repository-sha"),
        ("repository", "agent-os", "malformed-repository"),
        ("base_branch", "", "malformed-base-branch"),
        ("created_at", "2026-07-19", "malformed-created-at"),
        ("graph_digest", "bad", "malformed-graph-digest"),
        ("planning_result_digest", "bad", "malformed-planning-result-digest"),
        ("handoff_digest", "bad", "malformed-handoff-digest"),
    ),
)
def test_malformed_or_contradictory_fields_fail_closed(
    field_name: str, value: object, reason: str
) -> None:
    result = validate_scheduler_planning_handoff(replace(_valid_handoff(), **{field_name: value}))

    assert result.outcome is HandoffValidationOutcome.INVALID
    assert reason in result.reason_codes


def test_missing_required_field_fails_closed() -> None:
    payload = dataclasses.asdict(_valid_handoff())
    payload.pop("repository")

    result = validate_scheduler_planning_handoff(payload)

    assert result == type(result)(HandoffValidationOutcome.INVALID, ("malformed-handoff",))


def test_unknown_field_fails_closed() -> None:
    payload = dataclasses.asdict(_valid_handoff())
    payload["unknown_required_field"] = "value"

    result = validate_scheduler_planning_handoff(payload)

    assert result.outcome is HandoffValidationOutcome.INVALID


def test_partial_cohort_coverage_fails_closed() -> None:
    handoff = _valid_handoff(
        supplied_node_ids=("331", "332"),
        cohort_summaries=(
            HandoffCohort(("331",), "parallel-candidate", ("covered",)),
        ),
    )

    result = validate_scheduler_planning_handoff(handoff)

    assert result.outcome is HandoffValidationOutcome.INVALID
    assert "partial-or-duplicate-cohort-coverage" in result.reason_codes


def test_handoff_digest_mismatch_fails_closed() -> None:
    result = validate_scheduler_planning_handoff(
        replace(_valid_handoff(), handoff_digest=DIGEST_A)
    )

    assert result.outcome is HandoffValidationOutcome.INVALID
    assert "handoff-digest-mismatch" in result.reason_codes


def test_public_models_and_collections_are_immutable() -> None:
    handoff = _valid_handoff()

    with pytest.raises(dataclasses.FrozenInstanceError):
        handoff.base_branch = "release"  # type: ignore[misc]
    with pytest.raises(TypeError):
        handoff.supplied_node_ids[0] = "999"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        handoff.cohort_summaries[0].classification = "blocked"  # type: ignore[misc]


def test_serialization_preserves_unicode_without_ascii_escaping() -> None:
    handoff = _valid_handoff(repository="Blummer92/agent-ös")

    serialized = serialize_scheduler_planning_handoff(handoff)

    assert "ös".encode("utf-8") in serialized
    assert b"\\u00f6" not in serialized


def test_module_performs_no_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("external I/O is not allowed")

    monkeypatch.setattr("builtins.open", fail)
    handoff = _valid_handoff()

    serialize_scheduler_planning_handoff(handoff)
    compute_graph_digest(_graph())
    compute_planning_result_digest(_planning_result())
    validate_scheduler_planning_handoff(handoff)
