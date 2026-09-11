from dataclasses import replace

from scripts.agent_os_remote_validation.advisory_gate import AdvisoryEvidenceResult
from scripts.agent_os_remote_validation.impact_admission import evaluate_pre_aggregate_admission
from scripts.agent_os_remote_validation.impact_completeness import (
    ImpactCouplingRule,
    evaluate_impact_completeness,
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
            pull_request=2286,
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


def impact(changed, rule, repository_text=None):
    return evaluate_impact_completeness(
        changed_files=tuple(changed),
        rules=(rule,),
        repository_text=repository_text,
    )


def evaluate(plan, impact_result, evidence=None, *, base=BASE, head=HEAD):
    return evaluate_pre_aggregate_admission(
        plan,
        evidence,
        impact=impact_result,
        current_base_sha=base,
        current_head_sha=head,
    )


def test_complete_lockstep_change_preserves_canonical_focused_admission():
    rule = ImpactCouplingRule(
        name="lockstep",
        trigger_paths=("scripts/agent_os_issue_labels/pr_reconciler.py",),
        required_companion_paths=("tests/agent_os_issue_labels/test_pr_reconciler.py",),
    )
    paths = (
        "scripts/agent_os_issue_labels/pr_reconciler.py",
        "tests/agent_os_issue_labels/test_pr_reconciler.py",
    )
    plan = plan_for(paths)
    result = evaluate(plan, impact(paths, rule), evidence_for(plan))
    assert result.status == "admit"
    assert result.reason_codes == ("admission.focused-passed",)


def test_known_missing_companion_blocks_before_aggregate_execution():
    rule = ImpactCouplingRule(
        name="bounded-mcp-surface",
        trigger_paths=("08_Tooling/agent-os-execution-service/src/agent_os_execution_service/mcp_server.py",),
        required_companion_paths=("08_Tooling/agent-os-execution-service/tests/test_mcp_server.py",),
    )
    paths = ("08_Tooling/agent-os-execution-service/src/agent_os_execution_service/mcp_server.py",)
    plan = plan_for(paths)
    result = evaluate(plan, impact(paths, rule))
    assert result.status == "block"
    assert result.validation_obligation == "aggregate"
    assert result.reason_codes == ("impact.bounded-mcp-surface.companion-missing",)
    assert result.merge_authorized is False


def test_retired_lifecycle_interface_blocks_before_broad_validation():
    rule = ImpactCouplingRule(
        name="lifecycle-admission-callers",
        trigger_paths=("scripts/agent_os_issue_labels/pr_reconciler.py",),
        scan_prefixes=("scripts/agent_os_issue_labels/", "tests/agent_os_issue_labels/"),
        forbidden_tokens=("label_write_authorized=True",),
    )
    paths = ("scripts/agent_os_issue_labels/pr_reconciler.py",)
    result = evaluate(
        plan_for(paths),
        impact(
            paths,
            rule,
            {
                "scripts/agent_os_issue_labels/pr_reconciler.py": "lifecycle_admission=admission",
                "tests/agent_os_issue_labels/test_pr_reconciler.py": "label_write_authorized=True",
            },
        ),
    )
    assert result.status == "block"
    assert "impact.lifecycle-admission-callers.retired-interface-present" in result.reason_codes


def test_missing_scan_evidence_never_fabricates_completeness():
    rule = ImpactCouplingRule(
        name="lifecycle-admission-callers",
        trigger_paths=("scripts/agent_os_issue_labels/pr_reconciler.py",),
        scan_prefixes=("scripts/agent_os_issue_labels/",),
        forbidden_tokens=("label_write_authorized=True",),
    )
    paths = ("scripts/agent_os_issue_labels/pr_reconciler.py",)
    result = evaluate(plan_for(paths), impact(paths, rule))
    assert result.status == "block"
    assert "impact.lifecycle-admission-callers.scan-evidence-missing" in result.reason_codes


def test_ambiguous_relationship_routes_to_manual_review():
    rule = ImpactCouplingRule(
        name="prose-only-relationship",
        trigger_paths=("scripts/unmapped_new_surface.py",),
        ambiguous=True,
    )
    paths = ("scripts/unmapped_new_surface.py",)
    result = evaluate(plan_for(paths), impact(paths, rule))
    assert result.status == "manual-review"
    assert result.validation_obligation == "manual-review"


def test_not_applicable_impact_leaves_unknown_executable_to_selector():
    rule = ImpactCouplingRule(name="other", trigger_paths=("scripts/other.py",))
    paths = ("scripts/unmapped_new_surface.py",)
    plan = plan_for(paths)
    assert plan.profile == "aggregate"
    result = evaluate(plan, impact(paths, rule))
    assert result.status == "require-aggregate"
    assert result.reason_codes == ("admission.aggregate-required",)


def test_stale_head_still_wins_over_impact_disposition():
    rule = ImpactCouplingRule(
        name="missing-test",
        trigger_paths=("scripts/unmapped_new_surface.py",),
        required_companion_paths=("tests/test_unmapped_new_surface.py",),
    )
    paths = ("scripts/unmapped_new_surface.py",)
    result = evaluate(plan_for(paths), impact(paths, rule), head="e" * 40)
    assert result.status == "block"
    assert result.reason_codes == ("revision.head-sha-stale",)


def test_tampered_impact_result_fails_closed():
    rule = ImpactCouplingRule(name="other", trigger_paths=("scripts/other.py",))
    paths = ("scripts/unmapped_new_surface.py",)
    original = impact(paths, rule)
    tampered = replace(original, result_id="impact-completeness:" + "0" * 64)
    result = evaluate(plan_for(paths), tampered)
    assert result.status == "block"
    assert result.validation_obligation == "manual-review"
    assert result.reason_codes == ("impact.evidence-invalid",)
