from dataclasses import replace

from scripts.agent_os_remote_validation.advisory_gate import AdvisoryEvidenceResult
from scripts.agent_os_remote_validation.main_health import project_main_health
from scripts.agent_os_remote_validation.main_health_admission import evaluate_final_validation_admission
from scripts.agent_os_remote_validation.models import SelectionInput
from scripts.agent_os_remote_validation.selector import load_rule_map, select_validation_plan, validation_plan_id

REPOSITORY = "Blummer92/agent-os"
BASE = "a" * 40
HEAD = "b" * 40
OLD_MAIN = "c" * 40


def plan_for(paths: tuple[str, ...]):
    return select_validation_plan(
        SelectionInput(
            repository=REPOSITORY,
            pull_request=2285,
            base_sha=BASE,
            head_sha=HEAD,
            changed_files=paths,
        ),
        load_rule_map(),
    )


def health(*, current=BASE, evidence=BASE, conclusion="success", recovery=False):
    return project_main_health(
        repository=REPOSITORY,
        current_main_sha=current,
        evidence_sha=evidence,
        validation_conclusion=conclusion,
        recovery_requested=recovery,
    )


def evidence_for(plan, status="passed"):
    return AdvisoryEvidenceResult(
        schema_name="agent-os-advisory-pre-pr-evidence",
        schema_version="1.0",
        status=status,
        result_id="advisory-evidence:" + "d" * 64,
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
        implementation_contract_fingerprint="e" * 64,
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


def evaluate(plan, candidate_evidence=None, main=None):
    return evaluate_final_validation_admission(
        plan,
        candidate_evidence,
        main_health=health() if main is None else main,
        current_base_sha=BASE,
        current_head_sha=HEAD,
    )


def test_exact_healthy_main_preserves_existing_focused_admission():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate(plan, evidence_for(plan))
    assert result.status == "admit"
    assert result.validation_obligation == "focused"
    assert result.reason_codes == ("admission.focused-passed",)


def test_unhealthy_main_blocks_before_aggregate_is_requested():
    plan = plan_for((".github/workflows/agent-os-validation.yml",))
    result = evaluate(plan, main=health(conclusion="repository-failure"))
    assert result.status == "block"
    assert result.validation_obligation == "aggregate"
    assert result.reason_codes == ("main-health.exact-main-red",)
    assert result.merge_authorized is False


def test_missing_main_evidence_fails_closed_as_unknown():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate(plan, evidence_for(plan), health(evidence=None, conclusion="missing"))
    assert result.status == "block"
    assert result.reason_codes == ("main-health.evidence-missing",)


def test_pending_main_evidence_fails_closed():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate(plan, evidence_for(plan), health(conclusion="pending"))
    assert result.status == "block"
    assert result.reason_codes == ("main-health.validation-pending",)


def test_infrastructure_unproven_main_fails_closed_without_false_red_attribution():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    result = evaluate(plan, evidence_for(plan), health(conclusion="infrastructure-failure"))
    assert result.status == "block"
    assert result.reason_codes == ("main-health.infrastructure-unproven",)


def test_old_green_main_evidence_cannot_admit_newer_base():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    stale = health(current=OLD_MAIN, evidence=OLD_MAIN, conclusion="success")
    result = evaluate(plan, evidence_for(plan), stale)
    assert result.status == "block"
    assert result.reason_codes == ("main-health.evidence-stale",)


def test_repository_mismatch_fails_closed():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    mismatched = project_main_health(
        repository="other/repo",
        current_main_sha=BASE,
        evidence_sha=BASE,
        validation_conclusion="success",
    )
    result = evaluate(plan, evidence_for(plan), mismatched)
    assert result.status == "block"
    assert result.reason_codes == ("main-health.repository-mismatch",)


def test_tampered_main_health_result_fails_closed():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    tampered = replace(health(), result_id="main-health:" + "0" * 64)
    result = evaluate(plan, evidence_for(plan), tampered)
    assert result.status == "block"
    assert result.reason_codes == ("main-health.evidence-invalid",)


def test_recovery_only_main_keeps_candidate_validation_representable_without_authority():
    plan = plan_for(("scripts/agent_os_issue_acceptance/operating_mode.py",))
    recovery = health(conclusion="repository-failure", recovery=True)
    result = evaluate(plan, evidence_for(plan), recovery)
    assert recovery.disposition == "recovery-only"
    assert result.status == "admit"
    assert result.validation_obligation == "focused"
    assert result.merge_authorized is False
    assert result.authoritative is False
    assert result.side_effects_performed is False
