from dataclasses import replace

from scripts.agent_os_remote_validation.advisory_gate import AdvisoryEvidenceResult
from scripts.agent_os_remote_validation.merge_admission import (
    evaluate_merge_admission,
    merge_admission_result_id,
    serialize_merge_admission,
)
from scripts.agent_os_remote_validation.models import SelectionInput
from scripts.agent_os_remote_validation.selector import (
    load_rule_map,
    select_validation_plan,
    validation_plan_id,
)

BASE = "a" * 40
HEAD = "b" * 40


def plan_for(paths: tuple[str, ...]):
    return select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=2235,
            base_sha=BASE,
            head_sha=HEAD,
            changed_files=paths,
        ),
        load_rule_map(),
    )


def evidence_for(plan, status="passed"):
    return AdvisoryEvidenceResult(
        schema_name="agent-os-advisory-pre-pr-evidence",
        schema_version="1.0",
        status=status,
        result_id="advisory-evidence:" + "c" * 64,
        repository_identity=None,
        pull_request=plan.pull_request,
        base_branch="main",
        base_sha=plan.base_sha,
        source_head_sha=plan.head_sha,
        tested_sha=plan.head_sha,
        repository_evidence_type=None,
        projection_id="projection:fixture",
        proposal_id="proposal:fixture",
        approval_id="approval:fixture",
        repository_state_evidence_id="repository-state:fixture",
        implementation_contract_fingerprint="d" * 64,
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        plan_id=validation_plan_id(plan),
        bundle_id=None,
        runner_id="runner:fixture",
        invocation_id="invocation:fixture",
        command_result_ids=(),
        command_result_statuses=(),
        reason_codes=(),
        details=(),
    )


def test_docs_only_static_plan_admits_without_aggregate():
    plan = plan_for(("01_Shared_Standards/github/example.md",))
    assert plan.profile == "static"
    result = evaluate_merge_admission(plan, None, current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "admit"
    assert result.validation_obligation == "static"
    assert result.reason_codes == ("admission.static-plan-sufficient",)


def test_focused_plan_admits_with_exact_green_evidence():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    assert plan.profile == "focused"
    result = evaluate_merge_admission(plan, evidence_for(plan), current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "admit"
    assert result.validation_obligation == "focused"


def test_focused_missing_evidence_blocks_instead_of_silently_passing():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate_merge_admission(plan, None, current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "block"
    assert result.validation_obligation == "focused"
    assert result.reason_codes == ("admission.focused-evidence-missing",)


def test_aggregate_plan_requires_aggregate_when_evidence_missing():
    plan = plan_for((".github/workflows/agent-os-validation.yml",))
    assert plan.profile == "aggregate"
    result = evaluate_merge_admission(plan, None, current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "require-aggregate"
    assert result.validation_obligation == "aggregate"


def test_aggregate_red_blocks_even_when_evidence_is_well_bound():
    plan = plan_for((".github/workflows/agent-os-validation.yml",))
    result = evaluate_merge_admission(plan, evidence_for(plan, "failed"), current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "block"
    assert result.validation_obligation == "aggregate"
    assert result.reason_codes == ("admission.aggregate-failed",)


def test_incomplete_focused_evidence_escalates_budget_to_aggregate():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate_merge_admission(plan, evidence_for(plan, "incomplete"), current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "require-aggregate"
    assert result.validation_obligation == "aggregate"
    assert result.reason_codes == ("admission.focused-incomplete",)


def test_unknown_non_executable_surface_preserves_manual_review():
    plan = plan_for(("assets/example.bin",))
    assert plan.profile == "manual-review"
    result = evaluate_merge_admission(plan, None, current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "manual-review"
    assert result.validation_obligation == "manual-review"


def test_unmapped_executable_surface_requires_aggregate_budget():
    plan = plan_for(("scripts/unmapped_new_surface.py",))
    assert plan.profile == "aggregate"
    result = evaluate_merge_admission(plan, None, current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "require-aggregate"
    assert result.validation_obligation == "aggregate"


def test_validation_framework_change_requires_aggregate_budget():
    plan = plan_for(("tests/test_agent_os_validation_workflow.py",))
    assert plan.profile == "aggregate"
    result = evaluate_merge_admission(plan, None, current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "require-aggregate"
    assert result.validation_obligation == "aggregate"


def test_stale_head_blocks_before_evidence_can_admit():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate_merge_admission(plan, evidence_for(plan), current_base_sha=BASE, current_head_sha="e" * 40)
    assert result.status == "block"
    assert result.validation_obligation == "focused"
    assert result.reason_codes == ("revision.head-sha-stale",)


def test_stale_base_blocks_before_evidence_can_admit():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate_merge_admission(plan, evidence_for(plan), current_base_sha="e" * 40, current_head_sha=HEAD)
    assert result.status == "block"
    assert result.validation_obligation == "focused"
    assert result.reason_codes == ("revision.base-sha-stale",)


def test_evidence_for_another_head_cannot_admit():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    evidence = replace(evidence_for(plan), source_head_sha="e" * 40, tested_sha="e" * 40)
    result = evaluate_merge_admission(plan, evidence, current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "block"
    assert result.validation_obligation == "focused"
    assert "identity.head-sha-mismatch" in result.reason_codes
    assert "identity.tested-sha-mismatch" in result.reason_codes


def test_infrastructure_or_unavailable_focused_evidence_escalates_not_authorizes():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate_merge_admission(plan, evidence_for(plan, "incomplete"), current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "require-aggregate"
    assert result.validation_obligation == "aggregate"
    assert result.merge_authorized is False


def test_needs_decision_raises_budget_to_manual_review():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate_merge_admission(plan, evidence_for(plan, "needs-decision"), current_base_sha=BASE, current_head_sha=HEAD)
    assert result.status == "manual-review"
    assert result.validation_obligation == "manual-review"


def test_result_is_deterministic_non_authorizing_and_serializable():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    evidence = evidence_for(plan)
    first = evaluate_merge_admission(plan, evidence, current_base_sha=BASE, current_head_sha=HEAD)
    second = evaluate_merge_admission(plan, evidence, current_base_sha=BASE, current_head_sha=HEAD)
    assert first == second
    assert first.validation_obligation == "focused"
    assert first.merge_authorized is False
    assert first.authoritative is False
    assert first.side_effects_performed is False
    assert merge_admission_result_id(first) == first.result_id
    serialized = serialize_merge_admission(first)
    assert serialized["status"] == "admit"
    assert serialized["validation_obligation"] == "focused"
