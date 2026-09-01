import pytest

from scripts.agent_os_pr_remediation.models import EvidenceValidationError
from scripts.agent_os_pr_remediation.review_attack_plan import build_review_attack_plan
from scripts.agent_os_pr_remediation.review_evidence import ReviewDepth, ReviewRiskEvidence, build_review_evidence_packet, review_invalidation_scope
from scripts.agent_os_pr_remediation.review_findings import (
    ClearingEvidenceClass, FindingSeverity, FindingStatus, build_review_finding,
    build_review_suggestion, reevaluate_finding, unresolved_finding_ids,
)

HEAD = "b" * 40
NEW_HEAD = "d" * 40
PATH = "scripts/agent_os_pr_remediation/review_findings.py"


def _attack():
    packet = build_review_evidence_packet(
        repository="Blummer92/agent-os", issue_number=1585, pr_number=1601,
        base_sha="a" * 40, head_sha=HEAD, metadata_fingerprint="c" * 64,
        objective="Evidence-backed review findings", acceptance_criteria=["falsifiable findings"],
        allowed_paths=["scripts/agent_os_pr_remediation/"], forbidden_paths=[".github/workflows/"],
        non_goals=["no provider execution"], authorization_ceiling=["no-external-write"],
        changed_files=[PATH], bounded_diff="@@ bounded @@", changed_contracts=["review-finding-v1"],
        dependency_changes=[], workflow_changes=[],
        risk_evidence=[ReviewRiskEvidence("authorization", ("historical:evidence-authority-confusion",))],
        validation_profiles=["focused"], validation_results=["focused:pass"], exact_tested_sha=HEAD,
        failed_finding_ids=[], repaired_finding_ids=[], unresolved_finding_ids=[], prior_reviewed_head="a" * 40,
        paths_changed_since_review=[PATH], activated_references=["CRH1", "CRH5"], review_depth=ReviewDepth.ADVERSARIAL,
    )
    return build_review_attack_plan(packet).required_attacks[0]


def _finding():
    attack = _attack()
    return build_review_finding(
        attack=attack, threatened_invariant=attack.invariant, affected_path=PATH,
        symbol_or_contract_ref="build_review_finding", failure_scenario="Evidence-only output is treated as write authority.",
        severity=FindingSeverity.HIGH, supporting_evidence_refs=["fixture:authority-confusion"],
        clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
        clearing_evidence_identity="test:authority-remains-false", reviewed_head_sha=HEAD,
    )


def test_vague_refactor_is_structurally_non_blocking_suggestion():
    suggestion = build_review_suggestion(affected_path=PATH, suggestion="Consider refactoring this helper.", reviewed_head_sha=HEAD)
    assert suggestion.blocking is False
    with pytest.raises(EvidenceValidationError):
        unresolved_finding_ids([suggestion])


def test_substantive_finding_is_falsifiable_and_links_exact_crh5_attack():
    finding = _finding()
    assert finding.attack_id == _attack().attack_id
    assert finding.blocking is True
    assert finding.failure_scenario
    assert finding.clearing_condition.evidence_identity == "test:authority-remains-false"


def test_missing_failure_scenario_is_rejected():
    attack = _attack()
    with pytest.raises(EvidenceValidationError):
        build_review_finding(attack=attack, threatened_invariant=attack.invariant, affected_path=PATH,
            failure_scenario="", severity=FindingSeverity.HIGH, supporting_evidence_refs=["fixture:x"],
            clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
            clearing_evidence_identity="test:x", reviewed_head_sha=HEAD)


def test_missing_clearing_condition_is_rejected():
    attack = _attack()
    with pytest.raises(EvidenceValidationError):
        build_review_finding(attack=attack, threatened_invariant=attack.invariant, affected_path=PATH,
            failure_scenario="Concrete failure", severity=FindingSeverity.HIGH, supporting_evidence_refs=["fixture:x"],
            clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
            clearing_evidence_identity="", reviewed_head_sha=HEAD)


def test_provider_prose_cannot_clear_regression_test_condition():
    result = reevaluate_finding(finding=_finding(), current_head_sha=HEAD, invalidated_paths=[], clearing_evidence_refs=["reviewer:says-fixed"])
    assert result.status is FindingStatus.OPEN
    assert result.blocking


def test_new_head_invalidated_surface_makes_old_finding_stale():
    result = reevaluate_finding(finding=_finding(), current_head_sha=NEW_HEAD, invalidated_paths=[PATH])
    assert result.status is FindingStatus.STALE


def test_identical_canonical_evidence_has_deterministic_finding_identity():
    assert _finding().finding_id == _finding().finding_id


def test_current_clearing_evidence_resolves_and_removes_blocker_but_preserves_identity():
    finding = _finding()
    resolved = reevaluate_finding(finding=finding, current_head_sha=HEAD, invalidated_paths=[], clearing_evidence_refs=["test:authority-remains-false"])
    assert resolved.status is FindingStatus.RESOLVED_CURRENT
    assert not resolved.blocking
    assert resolved.finding_id == finding.finding_id
    assert unresolved_finding_ids([resolved]) == ()


def test_unrelated_head_change_preserves_compatible_resolved_evidence_when_crh1_does_not_invalidate_path():
    finding = reevaluate_finding(finding=_finding(), current_head_sha=HEAD, invalidated_paths=[], clearing_evidence_refs=["test:authority-remains-false"])
    invalidated = review_invalidation_scope(prior_reviewed_head=HEAD, current_head=NEW_HEAD,
        changed_paths_since_review=["docs/unrelated.md"], material_change_kinds=["markdown-only"], previously_reviewed_paths=[PATH])
    preserved = reevaluate_finding(finding=finding, current_head_sha=NEW_HEAD, invalidated_paths=invalidated,
        clearing_evidence_refs=["test:authority-remains-false"])
    assert invalidated == ()
    assert preserved.status is FindingStatus.RESOLVED_CURRENT


def test_crh1_broad_invalidator_makes_resolved_finding_stale():
    finding = reevaluate_finding(finding=_finding(), current_head_sha=HEAD, invalidated_paths=[], clearing_evidence_refs=["test:authority-remains-false"])
    invalidated = review_invalidation_scope(prior_reviewed_head=HEAD, current_head=NEW_HEAD,
        changed_paths_since_review=["public/api.py"], material_change_kinds=["authorization-security"], previously_reviewed_paths=[PATH])
    stale = reevaluate_finding(finding=finding, current_head_sha=NEW_HEAD, invalidated_paths=invalidated,
        clearing_evidence_refs=["test:authority-remains-false"])
    assert invalidated == (PATH,)
    assert stale.status is FindingStatus.STALE


def test_attack_head_mismatch_fails_closed():
    attack = _attack()
    with pytest.raises(EvidenceValidationError):
        build_review_finding(attack=attack, threatened_invariant=attack.invariant, affected_path=PATH,
            failure_scenario="Concrete failure", severity=FindingSeverity.HIGH, supporting_evidence_refs=["fixture:x"],
            clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST, clearing_evidence_identity="test:x",
            reviewed_head_sha=NEW_HEAD)


def test_all_finding_authority_fields_remain_false():
    finding = _finding()
    for name in ("execution_authorized", "merge_authorized", "closure_authorized", "readiness_authorized",
                 "production_authorized", "protected_setting_authorized", "external_write_authorized", "side_effects_performed"):
        assert getattr(finding, name) is False
