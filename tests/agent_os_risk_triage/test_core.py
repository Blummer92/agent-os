from dataclasses import FrozenInstanceError

import pytest

from scripts.agent_os_risk_triage import (
    CandidateEvidence,
    Disposition,
    FindingEvidence,
    Relationship,
    RiskTriageInput,
    TargetKind,
    TargetState,
    triage_risk,
)


def finding(**kwargs):
    values = {"finding_id": "risk-1", "text": "bounded finding"}
    values.update(kwargs)
    return FindingEvidence(**values)


def candidate(kind, identity, relationship, state=TargetState.OPEN, evidence=("supplied",)):
    return CandidateEvidence(kind, identity, state, relationship, evidence)


def test_repeatability_and_immutability():
    request = RiskTriageInput(finding=finding())
    assert triage_risk(request) == triage_risk(request)
    with pytest.raises(FrozenInstanceError):
        request.finding.text = "changed"


def test_no_action():
    result = triage_risk(RiskTriageInput(finding=finding(action_required=False)))
    assert result.disposition is Disposition.NO_ACTION


def test_no_action_is_not_overridden_by_supplied_target():
    target = candidate(TargetKind.EXISTING_ISSUE, "issue:10", Relationship.EQUIVALENT)
    result = triage_risk(
        RiskTriageInput(
            finding=finding(action_required=False),
            existing_issue_candidates=(target,),
        )
    )
    assert result.disposition is Disposition.NO_ACTION
    assert result.target_identity is None


def test_unambiguous_canonical_owner_wins_and_preserves_evidence():
    owner = candidate(
        TargetKind.CANONICAL_RISK_OWNER,
        "issue:543",
        Relationship.EQUIVALENT,
        evidence=("risk-owner-map supplied by caller",),
    )
    existing = candidate(TargetKind.EXISTING_ISSUE, "issue:900", Relationship.EQUIVALENT)
    result = triage_risk(
        RiskTriageInput(
            finding=finding(), canonical_risk_owners=(owner,), existing_issue_candidates=(existing,)
        )
    )
    assert result.disposition is Disposition.LINK_CANONICAL_RISK_OWNER
    assert result.target_identity == "issue:543"
    assert result.target_evidence == ("risk-owner-map supplied by caller",)


def test_duplicate_canonical_owner_evidence_resolves_same_identity():
    owners = (
        candidate(TargetKind.CANONICAL_RISK_OWNER, "issue:543", Relationship.EQUIVALENT),
        candidate(TargetKind.CANONICAL_RISK_OWNER, "issue:543", Relationship.OVERLAPS),
    )
    result = triage_risk(RiskTriageInput(finding=finding(), canonical_risk_owners=owners))
    assert result.disposition is Disposition.LINK_CANONICAL_RISK_OWNER
    assert result.target_identity == "issue:543"


def test_conflicting_canonical_owners_need_decision():
    owners = (
        candidate(TargetKind.CANONICAL_RISK_OWNER, "issue:1", Relationship.EQUIVALENT),
        candidate(TargetKind.CANONICAL_RISK_OWNER, "issue:2", Relationship.EQUIVALENT),
    )
    result = triage_risk(RiskTriageInput(finding=finding(), canonical_risk_owners=owners))
    assert result.disposition is Disposition.NEEDS_DECISION
    assert result.reason_codes == ("canonical-owner.conflict",)


def test_record_in_current_work():
    target = candidate(TargetKind.CURRENT_WORK, "pr:10", Relationship.OVERLAPS)
    result = triage_risk(RiskTriageInput(finding=finding(), current_work_candidates=(target,)))
    assert result.disposition is Disposition.RECORD_IN_CURRENT_WORK
    assert result.target_identity == "pr:10"


def test_duplicate_current_work_evidence_resolves_same_identity():
    targets = (
        candidate(TargetKind.CURRENT_WORK, "pr:10", Relationship.EQUIVALENT),
        candidate(TargetKind.CURRENT_WORK, "pr:10", Relationship.OVERLAPS),
    )
    result = triage_risk(RiskTriageInput(finding=finding(), current_work_candidates=targets))
    assert result.disposition is Disposition.RECORD_IN_CURRENT_WORK
    assert result.target_identity == "pr:10"


def test_update_existing_issue_candidate():
    target = candidate(TargetKind.EXISTING_ISSUE, "issue:10", Relationship.EQUIVALENT)
    result = triage_risk(RiskTriageInput(finding=finding(), existing_issue_candidates=(target,)))
    assert result.disposition is Disposition.UPDATE_EXISTING_ISSUE_CANDIDATE


def test_create_child_issue_candidate_from_explicit_relationship():
    parent = candidate(TargetKind.EXISTING_ISSUE, "issue:10", Relationship.CHILD)
    result = triage_risk(RiskTriageInput(finding=finding(), existing_issue_candidates=(parent,)))
    assert result.disposition is Disposition.CREATE_CHILD_ISSUE_CANDIDATE
    assert result.target_identity == "issue:10"


def test_duplicate_child_evidence_resolves_same_identity():
    parents = (
        candidate(TargetKind.EXISTING_ISSUE, "issue:10", Relationship.CHILD),
        candidate(TargetKind.EXISTING_ISSUE, "issue:10", Relationship.CHILD),
    )
    result = triage_risk(RiskTriageInput(finding=finding(), existing_issue_candidates=parents))
    assert result.disposition is Disposition.CREATE_CHILD_ISSUE_CANDIDATE
    assert result.target_identity == "issue:10"


def test_create_new_issue_candidate_when_no_target_is_supplied():
    result = triage_risk(RiskTriageInput(finding=finding()))
    assert result.disposition is Disposition.CREATE_NEW_ISSUE_CANDIDATE


def test_near_duplicate_without_structured_proof_needs_decision():
    maybe = candidate(TargetKind.EXISTING_ISSUE, "issue:10", Relationship.UNKNOWN)
    result = triage_risk(RiskTriageInput(finding=finding(), existing_issue_candidates=(maybe,)))
    assert result.disposition is Disposition.NEEDS_DECISION
    assert result.reason_codes == ("candidate.relationship-unproven",)


@pytest.mark.parametrize(
    "state",
    [TargetState.CLOSED, TargetState.STALE, TargetState.RETIRED_SCOPE, TargetState.UNKNOWN],
)
def test_invalid_candidate_state_fails_closed(state):
    old = candidate(TargetKind.EXISTING_ISSUE, "issue:10", Relationship.EQUIVALENT, state=state)
    result = triage_risk(RiskTriageInput(finding=finding(), existing_issue_candidates=(old,)))
    assert result.disposition is Disposition.NEEDS_DECISION
    assert result.reason_codes == ("candidate.invalid-state",)


def test_likelihood_and_impact_are_non_authorizing_evidence():
    low = triage_risk(RiskTriageInput(finding=finding(likelihood="low", impact="low")))
    high = triage_risk(RiskTriageInput(finding=finding(likelihood="high", impact="critical")))
    assert low.disposition is high.disposition is Disposition.CREATE_NEW_ISSUE_CANDIDATE
    assert low.reason_codes == high.reason_codes


def test_multiple_current_matches_need_decision():
    targets = (
        candidate(TargetKind.CURRENT_WORK, "pr:10", Relationship.EQUIVALENT),
        candidate(TargetKind.CURRENT_WORK, "pr:11", Relationship.OVERLAPS),
    )
    result = triage_risk(RiskTriageInput(finding=finding(), current_work_candidates=targets))
    assert result.disposition is Disposition.NEEDS_DECISION


def test_explicit_uncertainty_needs_decision():
    result = triage_risk(
        RiskTriageInput(finding=finding(), explicit_uncertainty=("human evidence conflicts",))
    )
    assert result.disposition is Disposition.NEEDS_DECISION
    assert result.reason_codes == ("uncertainty.explicit",)


def test_result_never_authorizes_or_performs_write():
    result = triage_risk(RiskTriageInput(finding=finding()))
    assert result.write_authorized is False
    assert result.mutation_performed is False


def test_reason_codes_are_bounded_and_stable():
    scenarios = [
        RiskTriageInput(finding=finding(action_required=False)),
        RiskTriageInput(finding=finding()),
        RiskTriageInput(finding=finding(), explicit_uncertainty=("x",)),
    ]
    codes = {code for request in scenarios for code in triage_risk(request).reason_codes}
    assert codes == {
        "finding.no-action-required",
        "finding.no-current-target",
        "uncertainty.explicit",
    }


def test_core_has_no_network_or_github_dependencies():
    import scripts.agent_os_risk_triage.core as core

    source = open(core.__file__, encoding="utf-8").read()
    forbidden = ("requests", "urllib", "httpx", "subprocess", "PyGithub", "github.Github")
    assert all(token not in source for token in forbidden)
