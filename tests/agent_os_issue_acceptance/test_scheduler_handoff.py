import ast
import inspect
import socket
import subprocess
from dataclasses import FrozenInstanceError

import pytest

import scripts.agent_os_issue_acceptance as issue_acceptance
from scripts.agent_os_issue_acceptance import scheduler_handoff
from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
    build_issue_batch_graph,
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

SHA40_A = "a" * 40
SHA40_B = "b" * 40
SHA256_A = "a" * 64


def node(node_id="a", **changes):
    values = {
        "node_id": node_id,
        "readiness": ReadinessOutcome.READY,
        "readiness_evidence": ("ready-evidence",),
        "owner": "Integration Manager",
        "source_of_truth": "GitHub",
        "affected_paths": ("scripts/a.py",),
        "forbidden_paths": ("production/**",),
        "dependency_ids": (),
        "entity_id": f"entity-{node_id}",
        "provenance": ("fixture",),
    }
    values.update(changes)
    return IssueBatchNode(**values)


def valid_mapping(**changes):
    payload = {
        "contract_version": "0.2.0",
        "planning_result_version": "0.1.0",
        "evaluator_commit_sha": SHA40_A,
        "repository": "Blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": SHA40_B,
        "supplied_node_ids": ["a"],
        "graph_digest": SHA256_A,
        "planning_result_digest": "b" * 64,
        "cohort_summaries": [
            {
                "node_ids": ["a"],
                "classification": "parallel-candidate",
                "reason_codes": ["covered-no-deterministic-conflict"],
            }
        ],
        "planning_scope": "supplied-graph-only",
        "execution_authorized": False,
        "created_at": "2026-07-19T17:00:00Z",
        "handoff_digest": "0" * 64,
    }
    payload.update(changes)
    payload["handoff_digest"] = compute_handoff_digest(payload)
    return payload


def valid_handoff(**changes):
    payload = valid_mapping(**changes)
    return SchedulerPlanningHandoff(
        contract_version=payload["contract_version"],
        planning_result_version=payload["planning_result_version"],
        evaluator_commit_sha=payload["evaluator_commit_sha"],
        repository=payload["repository"],
        base_branch=payload["base_branch"],
        evaluated_repository_sha=payload["evaluated_repository_sha"],
        supplied_node_ids=tuple(payload["supplied_node_ids"]),
        graph_digest=payload["graph_digest"],
        planning_result_digest=payload["planning_result_digest"],
        cohort_summaries=tuple(HandoffCohort(**item) for item in payload["cohort_summaries"]),
        created_at=payload["created_at"],
        handoff_digest=payload["handoff_digest"],
    )


def assert_invalid(payload, code):
    result = validate_scheduler_planning_handoff(payload)
    assert result.outcome is HandoffValidationOutcome.INVALID
    assert result.local_checks_passed is False
    assert code in result.reason_codes
    assert result.freshness == "not-evaluated"
    assert result.execution_authorized is False


def test_exact_transport_bytes_are_compact_utf8_and_have_no_newline():
    handoff = valid_handoff()
    encoded = serialize_scheduler_planning_handoff(handoff)
    expected = (
        b'{"base_branch":"main","cohort_summaries":[{"classification":'
        b'"parallel-candidate","node_ids":["a"],"reason_codes":'
        b'["covered-no-deterministic-conflict"]}],"contract_version":"0.2.0",'
        b'"created_at":"2026-07-19T17:00:00Z","evaluated_repository_sha":"'
        + SHA40_B.encode()
        + b'","evaluator_commit_sha":"'
        + SHA40_A.encode()
        + b'","execution_authorized":false,"graph_digest":"'
        + SHA256_A.encode()
        + b'","handoff_digest":"'
        + handoff.handoff_digest.encode()
        + b'","planning_result_digest":"'
        + ("b" * 64).encode()
        + b'","planning_result_version":"0.1.0","planning_scope":'
        b'"supplied-graph-only","repository":"Blummer92/agent-os",'
        b'"supplied_node_ids":["a"]}'
    )
    assert encoded == expected
    assert not encoded.endswith(b"\n")


def test_non_ascii_reason_is_literal_utf8_not_escape():
    payload = valid_mapping(
        cohort_summaries=[
            {
                "node_ids": ["a"],
                "classification": "parallel-candidate",
                "reason_codes": ["café"],
            }
        ]
    )
    handoff = valid_handoff(cohort_summaries=payload["cohort_summaries"])
    encoded = serialize_scheduler_planning_handoff(handoff)
    assert "café".encode("utf-8") in encoded
    assert b"\\u00e9" not in encoded


def test_graph_digest_is_order_independent_for_canonical_graph_content():
    first = IssueBatchGraph(
        nodes=(node("b"), node("a")),
        resolved_dependencies=(("b", "a"), ("b", "a")),
        unresolved_dependencies=(("a", "missing"),),
    )
    second = IssueBatchGraph(
        nodes=(node("a"), node("b")),
        resolved_dependencies=(("b", "a"),),
        unresolved_dependencies=(("a", "missing"),),
    )
    assert compute_graph_digest(first) == compute_graph_digest(second)


@pytest.mark.parametrize(
    "field,value",
    [
        ("readiness", ReadinessOutcome.BLOCKED),
        ("readiness_evidence", ("different",)),
        ("owner", "QA / Test Agent"),
        ("source_of_truth", "Other"),
        ("affected_paths", ("other.py",)),
        ("forbidden_paths", ("secrets/**",)),
        ("dependency_ids", ("z",)),
        ("entity_id", "other"),
        ("provenance", ("other",)),
    ],
)
def test_each_non_identity_node_field_changes_graph_digest(field, value):
    baseline = build_issue_batch_graph([node()])
    changed = build_issue_batch_graph([node(**{field: value})])
    assert compute_graph_digest(baseline) != compute_graph_digest(changed)


def test_node_id_and_dependency_collections_change_graph_digest():
    assert compute_graph_digest(build_issue_batch_graph([node("a")])) != compute_graph_digest(
        build_issue_batch_graph([node("b")])
    )
    base = IssueBatchGraph(nodes=(node("a"),))
    resolved = IssueBatchGraph(nodes=(node("a"),), resolved_dependencies=(("a", "a"),))
    unresolved = IssueBatchGraph(nodes=(node("a"),), unresolved_dependencies=(("a", "x"),))
    assert compute_graph_digest(base) != compute_graph_digest(resolved)
    assert compute_graph_digest(base) != compute_graph_digest(unresolved)


def test_planning_result_digest_uses_complete_stored_content_without_deduplication():
    cohort = PlanningCohort(
        ("a",),
        PlanningClassification.PARALLEL_CANDIDATE,
        ("same", "same"),
        (("a", "b"), ("a", "b")),
        (),
    )
    with_duplicates = BatchPlanningResult(
        ("a",),
        PlanningClassification.PARALLEL_CANDIDATE,
        (cohort,),
        ("batch", "batch"),
        (("a", "b"), ("a", "b")),
    )
    without_duplicates = BatchPlanningResult(
        ("a",),
        PlanningClassification.PARALLEL_CANDIDATE,
        (
            PlanningCohort(
                ("a",),
                PlanningClassification.PARALLEL_CANDIDATE,
                ("same",),
                (("a", "b"),),
                (),
            ),
        ),
        ("batch",),
        (("a", "b"),),
    )
    assert compute_planning_result_digest(with_duplicates) != compute_planning_result_digest(
        without_duplicates
    )


def test_equivalent_producer_results_have_identical_planning_digests():
    forward = build_issue_batch_graph([node("b"), node("a")])
    reverse = build_issue_batch_graph(reversed(forward.nodes))
    assert compute_planning_result_digest(evaluate_batch_plan(forward)) == compute_planning_result_digest(
        evaluate_batch_plan(reverse)
    )


def test_planning_digest_requires_public_result_type():
    with pytest.raises(TypeError, match="BatchPlanningResult"):
        compute_planning_result_digest({})


def test_handoff_digest_excludes_stored_digest_and_changes_for_other_fields():
    first = valid_mapping()
    second = dict(first, handoff_digest="f" * 64)
    assert compute_handoff_digest(first) == compute_handoff_digest(second)
    changed = dict(first, repository="other/repo")
    assert compute_handoff_digest(first) != compute_handoff_digest(changed)


def test_local_pass_needs_external_revalidation_and_never_authorizes_execution():
    result = validate_scheduler_planning_handoff(valid_mapping())
    assert result.outcome is HandoffValidationOutcome.NEEDS_DECISION
    assert result.local_checks_passed is True
    assert result.reason_codes == ("external-revalidation-required",)
    assert result.freshness == "not-evaluated"
    assert result.execution_authorized is False


@pytest.mark.parametrize("missing", sorted(scheduler_handoff._REQUIRED_FIELDS))
def test_every_missing_required_field_fails_closed(missing):
    payload = valid_mapping()
    payload.pop(missing)
    assert_invalid(payload, f"missing-field:{missing}")


def test_many_unknown_fields_produce_one_bounded_reason_code():
    payload = valid_mapping()
    payload.update({f"unknown_{index}": index for index in range(50)})
    result = validate_scheduler_planning_handoff(payload)
    assert result.reason_codes == ("unknown-field",)


def test_optional_field_registry_is_immutable_and_empty_for_current_version():
    assert scheduler_handoff.DECLARED_OPTIONAL_FIELDS["0.2.0"] == frozenset()
    with pytest.raises(TypeError):
        scheduler_handoff.DECLARED_OPTIONAL_FIELDS["0.2.0"] = frozenset({"x"})


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("contract_version", "1.0.0", "unsupported-contract-version"),
        ("contract_version", "bad", "malformed-field:contract_version"),
        ("planning_result_version", "0.2.0", "unsupported-planning-result-version"),
        ("evaluator_commit_sha", "abc", "malformed-field:evaluator_commit_sha"),
        ("evaluated_repository_sha", "abc", "malformed-field:evaluated_repository_sha"),
        ("graph_digest", "abc", "malformed-field:graph_digest"),
        ("planning_result_digest", "abc", "malformed-field:planning_result_digest"),
        ("repository", "owner/repo/extra", "malformed-field:repository"),
        ("repository", " owner/repo", "malformed-field:repository"),
        ("base_branch", "refs/heads/main", "malformed-field:base_branch"),
        ("base_branch", "feature/*", "malformed-field:base_branch"),
        ("base_branch", "main~1", "malformed-field:base_branch"),
        ("base_branch", "main^", "malformed-field:base_branch"),
        ("base_branch", "main..other", "malformed-field:base_branch"),
        ("created_at", "2026-02-30T17:00:00Z", "malformed-field:created_at"),
        ("created_at", "2026-07-19T17:00:00-04:00", "malformed-field:created_at"),
        ("created_at", "2026-07-19T17:00:00", "malformed-field:created_at"),
        ("created_at", " 2026-07-19T17:00:00Z", "malformed-field:created_at"),
    ],
)
def test_field_validation_fails_closed(field, value, code):
    payload = valid_mapping()
    payload[field] = value
    assert_invalid(payload, code)


def test_scope_and_execution_invariants_fail_closed():
    payload = valid_mapping()
    payload["planning_scope"] = "repository-wide"
    payload["execution_authorized"] = True
    result = validate_scheduler_planning_handoff(payload)
    assert result.reason_codes == (
        "execution-authorized-violation",
        "planning-scope-violation",
    )


@pytest.mark.parametrize(
    "cohorts,supplied,code",
    [
        ([{"node_ids": [], "classification": "parallel-candidate", "reason_codes": []}], ["a"], "malformed-field:cohort_summaries"),
        ([{"node_ids": [""], "classification": "parallel-candidate", "reason_codes": []}], [""], "malformed-field:cohort_summaries"),
        ([{"node_ids": ["a", "a"], "classification": "parallel-candidate", "reason_codes": []}], ["a"], "malformed-field:cohort_summaries"),
        ([
            {"node_ids": ["a"], "classification": "parallel-candidate", "reason_codes": []},
            {"node_ids": ["a"], "classification": "needs-decision", "reason_codes": []},
        ], ["a"], "partial-graph-coverage"),
        ([{"node_ids": ["b"], "classification": "parallel-candidate", "reason_codes": []}], ["a"], "partial-graph-coverage"),
        ([{"node_ids": ["a"], "classification": "parallel-candidate", "reason_codes": []}], ["a", "b"], "partial-graph-coverage"),
    ],
)
def test_cohort_coverage_and_structure_fail_closed(cohorts, supplied, code):
    payload = valid_mapping(cohort_summaries=cohorts, supplied_node_ids=supplied)
    assert_invalid(payload, code)


def test_duplicate_and_unsorted_supplied_node_ids_fail_closed():
    assert_invalid(valid_mapping(supplied_node_ids=["a", "a"]), "malformed-field:supplied_node_ids")
    assert_invalid(valid_mapping(supplied_node_ids=["b", "a"]), "malformed-field:supplied_node_ids")
    assert_invalid(valid_mapping(supplied_node_ids=[]), "malformed-field:supplied_node_ids")


def test_digest_mismatch_fails_closed():
    payload = valid_mapping()
    payload["handoff_digest"] = "f" * 64
    assert_invalid(payload, "handoff-digest-mismatch")


@pytest.mark.parametrize("garbage", [None, object(), 1, "handoff"])
def test_garbage_input_returns_invalid_without_raising(garbage):
    assert_invalid(garbage, "malformed-field:handoff")


def test_validation_does_not_mutate_input_and_reason_codes_are_sorted():
    payload = valid_mapping()
    payload["base_branch"] = "refs/heads/main"
    payload["repository"] = "bad"
    before = repr(payload)
    result = validate_scheduler_planning_handoff(payload)
    assert repr(payload) == before
    assert result.reason_codes == tuple(sorted(set(result.reason_codes)))


def test_models_are_frozen_and_tuple_backed():
    handoff = valid_handoff()
    assert isinstance(handoff.supplied_node_ids, tuple)
    assert isinstance(handoff.cohort_summaries, tuple)
    with pytest.raises(FrozenInstanceError):
        handoff.repository = "other/repo"


def test_constructor_does_not_allow_overriding_safety_fields():
    values = valid_mapping()
    kwargs = {
        "contract_version": values["contract_version"],
        "planning_result_version": values["planning_result_version"],
        "evaluator_commit_sha": values["evaluator_commit_sha"],
        "repository": values["repository"],
        "base_branch": values["base_branch"],
        "evaluated_repository_sha": values["evaluated_repository_sha"],
        "supplied_node_ids": tuple(values["supplied_node_ids"]),
        "graph_digest": values["graph_digest"],
        "planning_result_digest": values["planning_result_digest"],
        "cohort_summaries": tuple(HandoffCohort(**item) for item in values["cohort_summaries"]),
        "created_at": values["created_at"],
        "handoff_digest": values["handoff_digest"],
    }
    with pytest.raises(TypeError):
        SchedulerPlanningHandoff(**kwargs, execution_authorized=True)
    with pytest.raises(TypeError):
        SchedulerPlanningHandoff(**kwargs, planning_scope="other")


def test_package_exports_only_approved_handoff_boundary():
    expected = {
        "HandoffCohort",
        "HandoffValidationOutcome",
        "HandoffValidationResult",
        "SUPPORTED_CONTRACT_VERSIONS",
        "SUPPORTED_PLANNING_RESULT_VERSIONS",
        "SchedulerPlanningHandoff",
        "compute_graph_digest",
        "compute_handoff_digest",
        "compute_planning_result_digest",
        "serialize_scheduler_planning_handoff",
        "validate_scheduler_planning_handoff",
    }
    assert expected <= set(issue_acceptance.__all__)
    assert "DECLARED_OPTIONAL_FIELDS" not in issue_acceptance.__all__


def test_module_has_no_scheduler_or_workflow_import():
    tree = ast.parse(inspect.getsource(scheduler_handoff))
    imported = []
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            imported.extend(alias.name for alias in item.names)
        elif isinstance(item, ast.ImportFrom) and item.module:
            imported.append(item.module)
    assert not any("scheduler" in name.lower() or "workflow" in name.lower() for name in imported)


def test_all_public_functions_are_offline(monkeypatch):
    graph = build_issue_batch_graph([node()])
    plan = evaluate_batch_plan(graph)
    handoff = valid_handoff()
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: pytest.fail("network access"))
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("subprocess access"))
    compute_graph_digest(graph)
    compute_planning_result_digest(plan)
    compute_handoff_digest(handoff)
    serialize_scheduler_planning_handoff(handoff)
    validate_scheduler_planning_handoff(handoff)
