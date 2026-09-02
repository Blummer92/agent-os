import pytest

from scripts.agent_os_pr_remediation.models import EvidenceValidationError
from scripts.agent_os_pr_remediation.review_attack_plan import build_review_attack_plan
from scripts.agent_os_pr_remediation.review_evidence import ReviewDepth, ReviewRiskEvidence, build_review_evidence_packet
from scripts.agent_os_pr_remediation.review_findings import (
    ClearingEvidenceClass,
    FindingSeverity,
    FindingState,
    build_substantive_finding,
    build_suggestion,
    finding_currentness,
    resolve_finding,
)


def _packet(risk: str, *, path: str = "src/example.py"):
    return build_review_evidence_packet(
        repository="Blummer92/agent-os", issue_number=1585, pr_number=1700,
        base_sha="a" * 40, head_sha="b" * 40, metadata_fingerprint="c" * 64,
        objective="Evidence-backed review findings", acceptance_criteria=["falsifiable findings"],
        allowed_paths=["scripts/agent_os_pr_remediation/"], forbidden_paths=[".github/workflows/"],
        non_goals=["no provider execution"], authorization_ceiling=["no-external-write"],
        changed_files=[path], bounded_diff="@@ bounded @@", changed_contracts=[], dependency_changes=[],
        workflow_changes=[path] if risk == "workflow-ci-authority" else [],
        risk_evidence=[ReviewRiskEvidence(risk, ("historical-regression",))], validation_profiles=["focused"],
        validation_results=["focused:pass"], exact_tested_sha="b" * 40,
        failed_finding_ids=[], repaired_finding_ids=[], unresolved_finding_ids=[], prior_reviewed_head="a" * 40,
        paths_changed_since_review=[path], activated_references=["CRH1"], review_depth=ReviewDepth.ADVERSARIAL,
    )


def _attack(risk: str, reason: str, *, path: str = "src/example.py"):
    plan = build_review_attack_plan(_packet(risk, path=path))
    return next(a for a in plan.required_attacks if reason in a.reason_codes)


def _finding(risk="parser", reason="parser-ambiguity-first-match", **overrides):
    attack = _attack(risk, reason)
    payload = dict(
        attack=attack,
        invariant=attack.invariant,
        affected_surface_refs=["src/example.py"],
        failure_scenario="Two valid-looking targets are present and first-match selects the wrong issue.",
        severity=FindingSeverity.HIGH,
        supporting_evidence_refs=["fixture:ambiguous-linked-issue", "assertion:manual-review"],
        clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
        clearing_evidence_refs=["test:ambiguous-target-fails-closed"],
    )
    payload.update(overrides)
    return build_substantive_finding(**payload)


def test_historical_parser_first_match_defect_is_substantive_and_deterministic():
    first = _finding()
    second = _finding()
    assert first.finding_id == second.finding_id
    assert first.attack_id == _attack("parser", "parser-ambiguity-first-match").attack_id
    assert first.blocks_review is True


def test_transport_success_vs_semantic_failure_is_expressible():
    attack = _attack("workflow-ci-authority", "workflow-transport-vs-semantic")
    finding = build_substantive_finding(
        attack=attack, invariant=attack.invariant, affected_surface_refs=["src/example.py"],
        failure_scenario="Transport returns success while semantic validation reports failure.",
        severity=FindingSeverity.CRITICAL, supporting_evidence_refs=["transport:success", "semantic:failure"],
        clearing_evidence_class=ClearingEvidenceClass.EXACT_HEAD_VALIDATION,
        clearing_evidence_refs=["profile:semantic-validation"],
    )
    assert finding.attack_id == attack.attack_id


def test_wrong_identity_evidence_consumption_is_expressible():
    attack = _attack("authorization", "authorization-current-identity")
    finding = build_substantive_finding(
        attack=attack, invariant=attack.invariant, affected_surface_refs=["src/example.py"],
        failure_scenario="Evidence for issue 10 is consumed while evaluating issue 11.",
        severity=FindingSeverity.HIGH, supporting_evidence_refs=["issue:10", "expected-issue:11"],
        clearing_evidence_class=ClearingEvidenceClass.INVARIANT_PROOF,
        clearing_evidence_refs=["proof:identity-sha-binding"],
    )
    assert finding.blocks_review


def test_authorization_evidence_never_becomes_authority():
    attack = _attack("authorization", "authorization-evidence-not-authority")
    finding = build_substantive_finding(
        attack=attack, invariant=attack.invariant, affected_surface_refs=["src/example.py"],
        failure_scenario="A report-only evidence flag is treated as permission to mutate.",
        severity=FindingSeverity.CRITICAL, supporting_evidence_refs=["report:authorized-looking"],
        clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
        clearing_evidence_refs=["test:evidence-does-not-authorize"],
    )
    assert not any((finding.execution_authorized, finding.merge_authorized, finding.closure_authorized,
                    finding.readiness_authorized, finding.production_authorized,
                    finding.protected_setting_authorized, finding.external_write_authorized,
                    finding.side_effects_performed))


def test_state_reconciliation_failure_is_expressible():
    attack = _attack("state-machine", "state-retry-idempotency")
    finding = build_substantive_finding(
        attack=attack, invariant=attack.invariant, affected_surface_refs=["src/example.py"],
        failure_scenario="Retry after partial state produces duplicate terminal mutation.",
        severity=FindingSeverity.HIGH, supporting_evidence_refs=["fixture:partial-retry"],
        clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
        clearing_evidence_refs=["test:retry-converges"],
    )
    assert finding.severity is FindingSeverity.HIGH


def test_style_observation_remains_nonblocking_suggestion():
    suggestion = build_suggestion(affected_surface_refs=["src/example.py"], observation="Consider extracting a helper.", rationale="May improve readability.")
    assert suggestion.blocking is False
    assert suggestion.satisfies_required_attack is False
    assert suggestion.counts_as_discovered_defect is False
    assert suggestion.creates_authority is False


def test_unsupported_speculative_blocker_cannot_satisfy_contract():
    attack = _attack("parser", "parser-ambiguity-first-match")
    with pytest.raises(EvidenceValidationError):
        build_substantive_finding(
            attack=attack, invariant=attack.invariant, affected_surface_refs=["src/example.py"],
            failure_scenario="", severity=FindingSeverity.HIGH, supporting_evidence_refs=["concern:vague"],
            clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
            clearing_evidence_refs=["test:unknown"],
        )


def test_resolved_finding_requires_named_current_exact_head_evidence():
    finding = _finding()
    with pytest.raises(EvidenceValidationError):
        resolve_finding(finding, evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
                        evidence_refs=["reviewer:says-fixed"], evidence_head_sha="b" * 40)
    resolved = resolve_finding(finding, evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
                               evidence_refs=["test:ambiguous-target-fails-closed"], evidence_head_sha="b" * 40)
    assert resolved.state is FindingState.RESOLVED
    assert resolved.blocks_review is False


def test_changed_reviewed_surface_makes_finding_stale_via_crh1():
    finding = _finding()
    currentness = finding_currentness(finding, current_head_sha="d" * 40,
                                      changed_paths_since_review=["src/example.py"], material_change_kinds=["finding-repair"])
    assert currentness.state is FindingState.STALE
    assert currentness.invalidated_surface_refs == ("src/example.py",)


def test_unrelated_later_change_preserves_compatible_resolved_evidence():
    resolved = resolve_finding(_finding(), evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
                               evidence_refs=["test:ambiguous-target-fails-closed"], evidence_head_sha="b" * 40)
    currentness = finding_currentness(resolved, current_head_sha="d" * 40,
                                      changed_paths_since_review=["docs/unrelated.md"], material_change_kinds=["markdown-only"])
    assert currentness.state is FindingState.RESOLVED
    assert currentness.invalidated_surface_refs == ()


def test_interface_change_uses_crh1_broad_invalidation():
    finding = _finding()
    currentness = finding_currentness(finding, current_head_sha="d" * 40,
                                      changed_paths_since_review=["docs/unrelated.md"], material_change_kinds=["public-interface"])
    assert currentness.state is FindingState.STALE
    assert currentness.invalidated_surface_refs == ("src/example.py",)
