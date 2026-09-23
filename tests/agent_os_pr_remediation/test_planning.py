from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_os_pr_remediation import (
    EvidenceValidationError,
    deterministic_id,
    normalize_pr_snapshot,
    normalize_review_threads,
    plan_remediation,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "agent_os_pr_remediation" / "planning.json"
AUTHORITY_FIELDS = (
    "execution_authorized",
    "external_write_authorized",
    "merge_authorized",
    "side_effects_performed",
)


def _data() -> dict:
    return json.loads(FIXTURE.read_text())


def _inputs():
    data = _data()
    return (
        data,
        normalize_pr_snapshot(data["snapshot"]),
        normalize_review_threads(data["review_threads"]),
    )


def _plan(*names: str, allowed_files=None, include_optional=False):
    data, snapshot, threads = _inputs()
    kwargs = {}
    if include_optional:
        kwargs = {
            "failure_evidence": data["failure_evidence"],
            "repair_handoff": data["repair_handoff"],
        }
    return plan_remediation(
        snapshot,
        threads,
        [data["candidates"][name] for name in names],
        data["allowed_files"] if allowed_files is None else allowed_files,
        **kwargs,
    )


def _task_by_summary(plan, summary: str):
    return next(task for task in plan.tasks if task.requested_summary == summary)


def test_exact_duplicates_are_deterministically_classified_without_losing_source_findings():
    plan = _plan("duplicate_a", "duplicate_b")
    assert sorted(finding.classification for finding in plan.findings) == ["actionable", "duplicate"]
    assert len(plan.tasks) == 1
    duplicate = next(finding for finding in plan.findings if finding.classification == "duplicate")
    actionable = next(finding for finding in plan.findings if finding.classification == "actionable")
    assert duplicate.duplicate_of == actionable.finding_id
    assert {thread_id for finding in plan.findings for thread_id in finding.source_thread_ids} == {"PRRT_A", "PRRT_B"}


def test_conflicting_requested_outcomes_remain_separate_and_blocked():
    plan = _plan("conflict_a", "conflict_b")
    assert len(plan.findings) == 2
    assert {finding.classification for finding in plan.findings} == {"conflicting"}
    assert {finding.compute_route for finding in plan.findings} == {"high-reasoning-required"}
    assert all(finding.blocking for finding in plan.findings)
    assert len(plan.tasks) == 2
    assert all(not task.handoff_ready for task in plan.tasks)


def test_resolved_thread_is_not_treated_as_already_fixed_without_exact_head_proof():
    plan = _plan("resolved_not_fixed")
    assert plan.findings[0].classification == "actionable"
    task = _task_by_summary(plan, "resolved thread remains actionable without proof")
    assert task.handoff_ready is True
    assert task.compute_route == "no-model"


def test_exact_current_head_condition_absent_proof_is_already_fixed():
    plan = _plan("already_fixed")
    assert plan.findings[0].classification == "already-fixed"
    assert plan.findings[0].compute_route == "no-model"
    assert plan.tasks == ()
    assert any(item.startswith("condition-absent-at-head:") for item in plan.findings[0].evidence_basis)


def test_stale_already_fixed_proof_fails_closed_to_missing_evidence():
    data, snapshot, threads = _inputs()
    candidate = dict(data["candidates"]["already_fixed"])
    candidate["already_fixed_head_sha"] = "3333333333333333333333333333333333333333"
    plan = plan_remediation(snapshot, threads, [candidate], data["allowed_files"])
    assert plan.findings[0].classification == "missing-evidence"
    assert plan.findings[0].compute_route == "manual-decision-required"
    assert plan.tasks[0].handoff_ready is False


def test_outdated_and_out_of_scope_findings_are_distinct():
    outdated = _plan("outdated")
    assert outdated.findings[0].classification == "outdated"
    assert outdated.tasks == ()

    outside = _plan("out_of_scope")
    assert outside.findings[0].classification == "out-of-scope"
    assert outside.findings[0].scope_state == "outside-scope"
    assert outside.findings[0].compute_route == "manual-decision-required"
    assert outside.tasks[0].blockers == ("finding exceeds the supplied authorized file scope",)


def test_compute_routes_are_labels_only_and_do_not_create_authority():
    plan = _plan("small_model", "high_reasoning", "manual")
    routes = {task.requested_summary: task.compute_route for task in plan.tasks}
    assert routes["route bounded ambiguity"] == "small-model-eligible"
    assert routes["route compatibility decision"] == "high-reasoning-required"
    assert routes["route unclear authority to manual decision"] == "manual-decision-required"
    for finding in plan.findings:
        for field in AUTHORITY_FIELDS:
            assert getattr(finding, field) is False
    for task in plan.tasks:
        for field in AUTHORITY_FIELDS:
            assert getattr(task, field) is False
    for field in AUTHORITY_FIELDS:
        assert getattr(plan, field) is False


def test_many_source_threads_and_files_are_preserved_in_one_task():
    plan = _plan("multi_thread")
    task = _task_by_summary(plan, "preserve many source threads in one task")
    assert task.source_thread_ids == ("PRRT_A", "PRRT_B")
    assert task.affected_files == ("scripts/example.py", "tests/example.py")
    assert task.proposed_validations == ("aggregate-validation", "focused-tests")


def test_optional_failure_and_repair_packets_are_opaque_bounded_evidence():
    data = _data()
    plan = _plan("resolved_not_fixed", include_optional=True)
    assert plan.optional_failure_evidence_id == deterministic_id(data["failure_evidence"])
    assert plan.optional_repair_handoff_id == deterministic_id(data["repair_handoff"])


def test_plan_identity_is_invariant_to_candidate_order():
    forward = _plan("small_model", "high_reasoning", "resolved_not_fixed")
    reverse = _plan("resolved_not_fixed", "high_reasoning", "small_model")
    assert forward.evidence_id == reverse.evidence_id
    assert forward.finding_ids == reverse.finding_ids
    assert forward.task_ids == reverse.task_ids


def test_missing_thread_and_true_duplicate_payloads_fail_closed():
    data, snapshot, threads = _inputs()
    candidate = dict(data["candidates"]["resolved_not_fixed"])
    candidate["source_thread_ids"] = ["DOES_NOT_EXIST"]
    plan = plan_remediation(snapshot, threads, [candidate], data["allowed_files"])
    assert plan.findings[0].classification == "missing-evidence"

    exact = data["candidates"]["resolved_not_fixed"]
    with pytest.raises(EvidenceValidationError, match="exact duplicate payloads"):
        plan_remediation(snapshot, threads, [exact, exact], data["allowed_files"])


def test_unknown_fields_authority_true_and_oversized_collections_fail_closed():
    data, snapshot, threads = _inputs()
    candidate = dict(data["candidates"]["resolved_not_fixed"])
    candidate["unknown"] = "value"
    with pytest.raises(EvidenceValidationError, match="unknown finding candidate fields"):
        plan_remediation(snapshot, threads, [candidate], data["allowed_files"])

    candidate = dict(data["candidates"]["resolved_not_fixed"])
    candidate["execution_authorized"] = True
    with pytest.raises(EvidenceValidationError, match="must remain false"):
        plan_remediation(snapshot, threads, [candidate], data["allowed_files"])

    with pytest.raises(EvidenceValidationError, match="allowed_files exceeds size limit"):
        plan_remediation(snapshot, threads, [], [f"file-{index}.py" for index in range(5_001)])


def test_optional_evidence_rejects_non_builtin_and_oversized_payloads():
    data, snapshot, threads = _inputs()
    candidate = data["candidates"]["resolved_not_fixed"]
    with pytest.raises(EvidenceValidationError, match="built-in dictionary"):
        plan_remediation(snapshot, threads, [candidate], data["allowed_files"], failure_evidence=object())
    with pytest.raises(EvidenceValidationError, match="exceeds size limit"):
        plan_remediation(
            snapshot,
            threads,
            [candidate],
            data["allowed_files"],
            failure_evidence={"excerpt": "x" * 200_001},
        )
