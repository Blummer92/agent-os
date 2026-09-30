"""Regression coverage for #2741: verify-open-before-mutate.

Reproduces the incident where fresh branch-refresh defect evidence was
appended to closed/completed issue #1187, and proves the guard now refuses
closed targets fail-closed with a directive to an open owner.
"""
import pytest

from scripts.agent_os_issue_acceptance.defect_evidence_mutation_guard import (
    DefectEvidenceMutationDecision,
    DefectEvidenceMutationGuardResult,
    DefectEvidenceMutationTarget,
    DefectEvidenceRefusalDirective,
    evaluate_defect_evidence_mutation,
)


def target(issue_number, *, kind="defect", open=True, current=True,
           owner=None, lineage=None):
    return DefectEvidenceMutationTarget(
        issue_number=issue_number,
        evidence_kind=kind,
        target_open=open,
        state_current=current,
        open_owner_issue_number=owner,
        historical_lineage_issue_number=lineage,
    )


def test_1187_incident_closed_target_is_refused_with_open_owner():
    result = evaluate_defect_evidence_mutation(
        target(1187, open=False, owner=2637, lineage=1187)
    )
    assert result.decision is DefectEvidenceMutationDecision.REFUSED
    assert result.directive is DefectEvidenceRefusalDirective.ROUTE_TO_OPEN_OWNER
    assert result.open_owner_issue_number == 2637
    assert result.issue_number == 1187
    assert "mutation.target-closed-historical-only" in result.reason_codes


def test_open_target_with_current_state_is_admitted():
    result = evaluate_defect_evidence_mutation(target(2637, open=True))
    assert result.decision is DefectEvidenceMutationDecision.ADMITTED
    assert result.directive is None
    assert result.reason_codes == ("mutation.target-open-verified",)


def test_closed_target_without_open_owner_directs_new_bug():
    result = evaluate_defect_evidence_mutation(target(1187, open=False))
    assert result.decision is DefectEvidenceMutationDecision.REFUSED
    assert result.directive is DefectEvidenceRefusalDirective.CREATE_NEW_BUG
    assert "mutation.no-open-owner-create-new-bug" in result.reason_codes


def test_stale_state_fails_closed_even_when_claiming_open():
    result = evaluate_defect_evidence_mutation(
        target(2637, open=True, current=False)
    )
    assert result.decision is DefectEvidenceMutationDecision.REFUSED
    assert result.directive is DefectEvidenceRefusalDirective.REACQUIRE_TARGET_STATE
    assert result.reason_codes == ("mutation.target-state-not-current",)


def test_stale_state_on_closed_target_requires_reacquire_first():
    result = evaluate_defect_evidence_mutation(
        target(1187, open=False, current=False, owner=2637)
    )
    assert result.directive is DefectEvidenceRefusalDirective.REACQUIRE_TARGET_STATE


def test_process_evidence_uses_the_same_guard():
    admitted = evaluate_defect_evidence_mutation(
        target(2637, kind="process", open=True)
    )
    assert admitted.decision is DefectEvidenceMutationDecision.ADMITTED
    refused = evaluate_defect_evidence_mutation(
        target(1187, kind="process", open=False)
    )
    assert refused.decision is DefectEvidenceMutationDecision.REFUSED


def test_closed_target_is_never_admitted_as_active_owner():
    for owner in (None, 2637):
        result = evaluate_defect_evidence_mutation(
            target(1187, open=False, owner=owner, lineage=1187)
        )
        assert result.decision is DefectEvidenceMutationDecision.REFUSED


def test_guard_performs_no_side_effects():
    result = evaluate_defect_evidence_mutation(target(2637, open=True))
    assert result.side_effects_performed is False


def test_open_owner_cannot_be_the_target_itself():
    with pytest.raises(ValueError):
        target(1187, open=False, owner=1187)


def test_invalid_evidence_kind_fails_closed():
    with pytest.raises(ValueError):
        target(1187, kind="comment", open=True)


def test_admitted_result_cannot_carry_a_directive():
    with pytest.raises(ValueError):
        DefectEvidenceMutationGuardResult(
            decision=DefectEvidenceMutationDecision.ADMITTED,
            directive=DefectEvidenceRefusalDirective.ROUTE_TO_OPEN_OWNER,
            issue_number=2637,
            evidence_kind="defect",
            open_owner_issue_number=None,
            reason_codes=("mutation.target-open-verified",),
        )
