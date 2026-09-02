import pytest

from scripts.agent_os_pr_remediation.models import EvidenceValidationError
from scripts.agent_os_pr_remediation.review_attack_plan import RequiredAttack, ReviewAttackPlan
from scripts.agent_os_pr_remediation.review_coverage import (
    AdequacyStatus,
    CoverageStatus,
    ReviewCoverageObservation,
    TestEvidence,
    assess_test_adequacy,
    normalize_review_coverage,
)
from scripts.agent_os_pr_remediation.review_findings import (
    ClearingEvidenceClass,
    FindingSeverity,
    build_substantive_finding,
)

HEAD = "a" * 40
OLD = "b" * 40
NEW = "c" * 40


def attack(reason="parser-ambiguity-first-match", obligations=("ambiguous-input-case", "selection-result")):
    return RequiredAttack(
        attack_family="parser",
        invariant="ambiguous or multiple valid-looking targets are not resolved by first match",
        reviewed_head_sha=HEAD,
        affected_surface_refs=("parse.py",),
        bounded_evidence_requirements=obligations,
        reason_codes=(reason,),
    )


def plan(*attacks):
    return ReviewAttackPlan(
        reviewed_head_sha=HEAD,
        risk_classes=("parser",),
        required_attacks=tuple(attacks),
        activated_contracts=(),
        bounded_evidence_requirements=tuple(sorted({x for a in attacks for x in a.bounded_evidence_requirements})),
        manual_review_reasons=(),
    )


def observation(item, status=CoverageStatus.EXAMINED_CLEAR, head=HEAD, refs=("review:1",), reasons=()):
    return ReviewCoverageObservation(item.attack_id, head, "exec:1", status, refs, reasons)


def test_missing_required_attack_is_unexamined_blocking():
    first, second = attack(), attack("parser-noncanonical-target", ("noncanonical-input-case", "canonical-target-proof"))
    records = normalize_review_coverage(plan=plan(first, second), observations=[observation(first)])
    assert [r.coverage_status for r in records].count(CoverageStatus.UNEXAMINED_BLOCKING) == 1
    assert any(r.blocks_review for r in records)


def test_provider_success_without_per_attack_evidence_does_not_synthesize_clear():
    item = attack()
    records = normalize_review_coverage(plan=plan(item), observations=[])
    assert records[0].coverage_status is CoverageStatus.UNEXAMINED_BLOCKING


def test_examined_clear_requires_bounded_per_attack_evidence():
    item = attack()
    record = normalize_review_coverage(plan=plan(item), observations=[observation(item, refs=())])[0]
    assert record.coverage_status is CoverageStatus.MANUAL_REVIEW
    assert "examined-disposition-requires-bounded-evidence" in record.reason_codes


def test_current_finding_requires_examined_finding_disposition():
    item = attack()
    finding = build_substantive_finding(
        attack=item, invariant=item.invariant, affected_surface_refs=("parse.py",),
        failure_scenario="first incidental issue reference wins before the explicit closing target",
        severity=FindingSeverity.HIGH, supporting_evidence_refs=("fixture:first-match",),
        clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
        clearing_evidence_refs=("test:explicit-target",),
    )
    records = normalize_review_coverage(
        plan=plan(item), observations=[observation(item, CoverageStatus.EXAMINED_FINDING)], findings=[finding]
    )
    assert records[0].coverage_status is CoverageStatus.EXAMINED_FINDING
    assert records[0].finding_ids == (finding.finding_id,)


def test_clear_conflicting_with_current_finding_fails_closed():
    item = attack()
    finding = build_substantive_finding(
        attack=item, invariant=item.invariant, affected_surface_refs=("parse.py",),
        failure_scenario="ambiguous input resolves by first match", severity=FindingSeverity.HIGH,
        supporting_evidence_refs=("fixture",), clearing_evidence_class=ClearingEvidenceClass.REGRESSION_TEST,
        clearing_evidence_refs=("test",),
    )
    record = normalize_review_coverage(plan=plan(item), observations=[observation(item)], findings=[finding])[0]
    assert record.coverage_status is CoverageStatus.MANUAL_REVIEW


def test_not_applicable_requires_reason_and_evidence():
    item = attack()
    record = normalize_review_coverage(plan=plan(item), observations=[observation(item, CoverageStatus.NOT_APPLICABLE)])[0]
    assert record.coverage_status is CoverageStatus.MANUAL_REVIEW


def test_stale_review_head_is_stale():
    item = attack()
    record = normalize_review_coverage(plan=plan(item), observations=[observation(item, head=OLD)])[0]
    assert record.coverage_status is CoverageStatus.STALE


def test_crh1_surface_invalidation_marks_old_coverage_stale():
    item = attack()
    record = normalize_review_coverage(
        plan=plan(item), observations=[observation(item)], current_head_sha=NEW,
        changed_paths_since_review=["parse.py"], material_change_kinds=["finding-repair"],
    )[0]
    assert record.coverage_status is CoverageStatus.STALE
    assert "crh1-affected-surface-invalidated" in record.reason_codes


def test_unrelated_head_change_preserves_compatible_review_coverage():
    item = attack()
    record = normalize_review_coverage(
        plan=plan(item), observations=[observation(item)], current_head_sha=NEW,
        changed_paths_since_review=["docs/unrelated.md"], material_change_kinds=["markdown-only"],
    )[0]
    assert record.coverage_status is CoverageStatus.EXAMINED_CLEAR


def test_duplicate_equivalent_observations_collapse_deterministically():
    item = attack()
    one = normalize_review_coverage(plan=plan(item), observations=[observation(item), observation(item)])
    two = normalize_review_coverage(plan=plan(item), observations=[observation(item)])
    assert one == two
    assert one[0].coverage_id == two[0].coverage_id


def test_contradictory_duplicate_observations_fail_closed():
    item = attack()
    records = normalize_review_coverage(
        plan=plan(item),
        observations=[observation(item), observation(item, CoverageStatus.NOT_APPLICABLE, refs=("review:2",), reasons=("bounded-na",))],
    )
    assert records[0].coverage_status is CoverageStatus.MANUAL_REVIEW


def test_happy_path_only_parser_evidence_is_inadequate():
    item = attack()
    result = assess_test_adequacy(
        attack=item, required_test_obligations=item.bounded_evidence_requirements,
        evidence=TestEvidence(HEAD, ("pytest:happy",), ("selection-result",), ("tests/test_parse.py",)),
    )
    assert result.adequacy_status is AdequacyStatus.INADEQUATE
    assert result.missing_obligations == ("ambiguous-input-case",)


def test_negative_regression_evidence_can_be_adequate_independent_of_review_coverage():
    item = attack()
    result = assess_test_adequacy(
        attack=item, required_test_obligations=item.bounded_evidence_requirements,
        evidence=TestEvidence(HEAD, ("pytest:parser-negative",), item.bounded_evidence_requirements, ("tests/test_parse.py",)),
    )
    assert result.adequacy_status is AdequacyStatus.ADEQUATE
    coverage = normalize_review_coverage(plan=plan(item), observations=[])[0]
    assert coverage.coverage_status is CoverageStatus.UNEXAMINED_BLOCKING


def test_architecture_reasoning_attack_can_have_no_required_test_obligation():
    item = attack()
    result = assess_test_adequacy(attack=item, evidence=None, required_test_obligations=[])
    assert result.adequacy_status is AdequacyStatus.NOT_APPLICABLE
    assert result.missing_obligations == ()


def test_test_only_change_recalculates_adequacy_when_test_surface_changed():
    item = attack()
    result = assess_test_adequacy(
        attack=item, required_test_obligations=item.bounded_evidence_requirements,
        evidence=TestEvidence(HEAD, ("pytest:old",), item.bounded_evidence_requirements, ("tests/test_parse.py",)),
        current_head_sha=NEW, changed_paths_since_test=["tests/test_parse.py"], material_change_kinds=["test-only"],
    )
    assert result.adequacy_status is AdequacyStatus.STALE


def test_unrelated_change_can_preserve_compatible_test_evidence():
    item = attack()
    result = assess_test_adequacy(
        attack=item, required_test_obligations=item.bounded_evidence_requirements,
        evidence=TestEvidence(HEAD, ("pytest:parser-negative",), item.bounded_evidence_requirements, ("tests/test_parse.py",)),
        current_head_sha=NEW, changed_paths_since_test=["docs/unrelated.md"], material_change_kinds=["markdown-only"],
    )
    assert result.adequacy_status is AdequacyStatus.ADEQUATE


def test_required_test_obligations_must_come_from_crh5_attack():
    item = attack()
    with pytest.raises(EvidenceValidationError):
        assess_test_adequacy(attack=item, evidence=None, required_test_obligations=["invented-test-selector-rule"])


def test_property_mutation_recommendation_is_report_only_and_non_authorizing():
    item = attack()
    result = assess_test_adequacy(
        attack=item, evidence=None, required_test_obligations=["ambiguous-input-case"],
        recommendations=["property-test-candidate", "mutation-test-candidate"],
    )
    assert "property-test-candidate" in result.recommendations
    assert "mutation-test-candidate" in result.recommendations
    assert not result.execution_authorized and not result.merge_authorized and not result.external_write_authorized


def test_authority_fields_remain_false():
    item = attack()
    coverage = normalize_review_coverage(plan=plan(item), observations=[])[0]
    adequacy = assess_test_adequacy(attack=item, evidence=None, required_test_obligations=["ambiguous-input-case"])
    assert not coverage.execution_authorized and not coverage.merge_authorized and not coverage.external_write_authorized
    assert not coverage.readiness_authorized and not coverage.protected_setting_authorized
    assert not adequacy.execution_authorized and not adequacy.merge_authorized and not adequacy.external_write_authorized
    assert not adequacy.readiness_authorized and not adequacy.protected_setting_authorized
