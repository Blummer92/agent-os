from __future__ import annotations

from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.risk_triage import (
    CandidateEvidence,
    CandidateState,
    Relationship,
    RiskDisposition,
    RiskFindingEvidence,
    RiskTriageResult,
    triage_risk_finding,
)


def finding(**kwargs: object) -> RiskFindingEvidence:
    return RiskFindingEvidence(
        finding_id="risk-1",
        finding_text="Explicit caller-supplied risk finding.",
        **kwargs,
    )


def candidate(identity: str, **kwargs: object) -> CandidateEvidence:
    return CandidateEvidence(identity=identity, evidence=("caller-supplied",), **kwargs)


def test_repeatability_is_deterministic() -> None:
    evidence = finding(existing_issues=(candidate("#10", relationship=Relationship.EXACT),))
    assert triage_risk_finding(evidence) == triage_risk_finding(evidence)


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (finding(no_action_evidence=True), RiskDisposition.NO_ACTION),
        (finding(current_work=(candidate("work:1", relationship=Relationship.OVERLAP),)), RiskDisposition.RECORD_IN_CURRENT_WORK),
        (finding(canonical_risk_owners=(candidate("risk-owner:543"),)), RiskDisposition.LINK_CANONICAL_RISK_OWNER),
        (finding(existing_issues=(candidate("#12", exact_equivalent=True),)), RiskDisposition.UPDATE_EXISTING_ISSUE_CANDIDATE),
        (finding(existing_issues=(candidate("#12", relationship=Relationship.CHILD),)), RiskDisposition.CREATE_CHILD_ISSUE_CANDIDATE),
        (finding(), RiskDisposition.CREATE_NEW_ISSUE_CANDIDATE),
        (finding(manual_review_required=True), RiskDisposition.NEEDS_DECISION),
    ],
)
def test_all_seven_dispositions(evidence: RiskFindingEvidence, expected: RiskDisposition) -> None:
    assert triage_risk_finding(evidence).disposition is expected


def test_canonical_owner_is_preserved_not_copied_from_prose() -> None:
    result = triage_risk_finding(finding(canonical_risk_owners=(candidate("risk-owner:543"),)))
    assert result.target_identity == "risk-owner:543"
    assert result.target_evidence == ("caller-supplied",)


def test_conflicting_canonical_owners_need_decision() -> None:
    result = triage_risk_finding(
        finding(canonical_risk_owners=(candidate("owner:a"), candidate("owner:b")))
    )
    assert result.disposition is RiskDisposition.NEEDS_DECISION
    assert result.reason_codes == ("canonical-owner.conflict",)


def test_current_work_and_existing_issue_are_distinct_targets() -> None:
    current = triage_risk_finding(
        finding(current_work=(candidate("work:1", exact_equivalent=True),))
    )
    existing = triage_risk_finding(
        finding(existing_issues=(candidate("#22", exact_equivalent=True),))
    )
    assert current.disposition is RiskDisposition.RECORD_IN_CURRENT_WORK
    assert existing.disposition is RiskDisposition.UPDATE_EXISTING_ISSUE_CANDIDATE


def test_child_vs_new_uses_structured_relationship_only() -> None:
    child = triage_risk_finding(
        finding(existing_issues=(candidate("#703", relationship=Relationship.CHILD),))
    )
    new = triage_risk_finding(finding())
    assert child.disposition is RiskDisposition.CREATE_CHILD_ISSUE_CANDIDATE
    assert new.disposition is RiskDisposition.CREATE_NEW_ISSUE_CANDIDATE


def test_near_duplicate_prose_does_not_prove_equivalence() -> None:
    evidence = RiskFindingEvidence(
        finding_id="risk-2",
        finding_text="This sounds exactly like issue 42 but no structured proof was supplied.",
        existing_issues=(candidate("#42", relationship=Relationship.UNKNOWN),),
    )
    result = triage_risk_finding(evidence)
    assert result.disposition is RiskDisposition.NEEDS_DECISION
    assert result.reason_codes == ("relationship.ambiguous",)


@pytest.mark.parametrize("state", [CandidateState.CLOSED, CandidateState.STALE, CandidateState.RETIRED_SCOPE])
def test_noncurrent_candidates_fail_closed(state: CandidateState) -> None:
    result = triage_risk_finding(
        finding(existing_issues=(candidate("#543", state=state, exact_equivalent=True),))
    )
    assert result.disposition is RiskDisposition.NEEDS_DECISION
    assert result.reason_codes == ("candidate.not-current",)


def test_likelihood_and_impact_are_preserved_but_non_authorizing() -> None:
    result = triage_risk_finding(finding(likelihood="high", impact="high"))
    assert result.disposition is RiskDisposition.CREATE_NEW_ISSUE_CANDIDATE
    assert result.likelihood == "high"
    assert result.impact == "high"
    assert result.execution_authorized is False
    assert result.external_write_authorized is False


def test_conflicting_target_types_fail_closed() -> None:
    result = triage_risk_finding(
        finding(
            current_work=(candidate("work:1", exact_equivalent=True),),
            existing_issues=(candidate("#22", exact_equivalent=True),),
        )
    )
    assert result.disposition is RiskDisposition.NEEDS_DECISION
    assert result.reason_codes == ("evidence.conflicting-targets",)


def test_reason_codes_are_bounded_sorted_and_stable() -> None:
    with pytest.raises(ValueError, match="unknown reason code"):
        RiskTriageResult(
            disposition=RiskDisposition.NEEDS_DECISION,
            reason_codes=("unbounded.dynamic.reason",),
            finding_id="risk-1",
        )


def test_core_has_no_network_subprocess_or_github_client_capability() -> None:
    source = Path("scripts/agent_os_issue_acceptance/risk_triage.py").read_text(encoding="utf-8")
    forbidden = ("import requests", "import subprocess", "import socket", "github.com", "gh ")
    for token in forbidden:
        assert token not in source
