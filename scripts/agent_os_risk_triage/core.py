"""Pure-local deterministic risk-to-issue triage contract.

This module consumes only caller-supplied structured evidence. It performs no
network, subprocess, credential, GitHub, or external-write operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Disposition(str, Enum):
    NO_ACTION = "no-action"
    RECORD_IN_CURRENT_WORK = "record-in-current-work"
    LINK_CANONICAL_RISK_OWNER = "link-canonical-risk-owner"
    UPDATE_EXISTING_ISSUE_CANDIDATE = "update-existing-issue-candidate"
    CREATE_CHILD_ISSUE_CANDIDATE = "create-child-issue-candidate"
    CREATE_NEW_ISSUE_CANDIDATE = "create-new-issue-candidate"
    NEEDS_DECISION = "needs-decision"


class TargetKind(str, Enum):
    CURRENT_WORK = "current-work"
    EXISTING_ISSUE = "existing-issue"
    CANONICAL_RISK_OWNER = "canonical-risk-owner"


class TargetState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    STALE = "stale"
    RETIRED_SCOPE = "retired-scope"
    UNKNOWN = "unknown"


class Relationship(str, Enum):
    EQUIVALENT = "equivalent"
    OVERLAPS = "overlaps"
    CHILD = "child"
    DISTINCT = "distinct"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FindingEvidence:
    finding_id: str
    text: str
    likelihood: str | None = None
    impact: str | None = None
    action_required: bool = True


@dataclass(frozen=True)
class CandidateEvidence:
    kind: TargetKind
    identity: str
    state: TargetState
    relationship: Relationship
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskTriageInput:
    finding: FindingEvidence
    current_work_candidates: tuple[CandidateEvidence, ...] = ()
    existing_issue_candidates: tuple[CandidateEvidence, ...] = ()
    canonical_risk_owners: tuple[CandidateEvidence, ...] = ()
    explicit_uncertainty: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskTriageResult:
    disposition: Disposition
    reason_codes: tuple[str, ...]
    target_identity: str | None = None
    target_kind: TargetKind | None = None
    target_evidence: tuple[str, ...] = ()
    mutation_performed: bool = False
    write_authorized: bool = False


_VALID_STATES = {TargetState.OPEN}
_MATCH_RELATIONSHIPS = {Relationship.EQUIVALENT, Relationship.OVERLAPS}


def triage_risk(request: RiskTriageInput) -> RiskTriageResult:
    """Return exactly one advisory disposition for immutable supplied evidence."""
    if not _valid_request_shape(request):
        return _decision("evidence.malformed")

    if request.explicit_uncertainty:
        return _decision("uncertainty.explicit")

    if not request.finding.action_required:
        return RiskTriageResult(
            disposition=Disposition.NO_ACTION,
            reason_codes=("finding.no-action-required",),
        )

    if _has_mismatched_candidate_kind(request):
        return _decision("candidate.kind-mismatch")

    owner_result = _canonical_owner_result(request.canonical_risk_owners)
    if owner_result is not None:
        return owner_result

    current_result = _candidate_result(
        request.current_work_candidates,
        TargetKind.CURRENT_WORK,
        Disposition.RECORD_IN_CURRENT_WORK,
        "current-work.match",
    )
    if current_result is not None:
        return current_result

    existing_result = _candidate_result(
        request.existing_issue_candidates,
        TargetKind.EXISTING_ISSUE,
        Disposition.UPDATE_EXISTING_ISSUE_CANDIDATE,
        "existing-issue.match",
    )
    if existing_result is not None:
        return existing_result

    invalid = _invalid_candidates(
        request.current_work_candidates
        + request.existing_issue_candidates
        + request.canonical_risk_owners
    )
    if invalid:
        return _decision("candidate.invalid-state")

    if _has_unproven_similarity(
        request.current_work_candidates + request.existing_issue_candidates
    ):
        return _decision("candidate.relationship-unproven")

    child_candidates = tuple(
        candidate
        for candidate in request.existing_issue_candidates
        if candidate.state in _VALID_STATES and candidate.relationship is Relationship.CHILD
    )
    child_identities = {candidate.identity for candidate in child_candidates}
    if len(child_identities) > 1:
        return _decision("child.multiple-candidates")
    if child_candidates:
        return _target_result(
            Disposition.CREATE_CHILD_ISSUE_CANDIDATE,
            "child.explicit-relationship",
            child_candidates[0],
        )

    if _has_conflicting_distinct_targets(
        request.current_work_candidates + request.existing_issue_candidates
    ):
        return _decision("candidate.conflicting-targets")

    return RiskTriageResult(
        disposition=Disposition.CREATE_NEW_ISSUE_CANDIDATE,
        reason_codes=("finding.no-current-target",),
    )


def _valid_request_shape(request: object) -> bool:
    if type(request) is not RiskTriageInput or type(request.finding) is not FindingEvidence:
        return False
    if type(request.finding.action_required) is not bool:
        return False
    if type(request.finding.finding_id) is not str or not request.finding.finding_id.strip():
        return False
    if type(request.finding.text) is not str or not request.finding.text.strip():
        return False
    if any(
        value is not None and type(value) is not str
        for value in (request.finding.likelihood, request.finding.impact)
    ):
        return False
    groups = (
        request.current_work_candidates,
        request.existing_issue_candidates,
        request.canonical_risk_owners,
    )
    if any(type(group) is not tuple for group in groups) or type(request.explicit_uncertainty) is not tuple:
        return False
    if any(type(item) is not str or not item.strip() for item in request.explicit_uncertainty):
        return False
    return all(_valid_candidate(candidate) for group in groups for candidate in group)


def _valid_candidate(candidate: object) -> bool:
    return (
        type(candidate) is CandidateEvidence
        and type(candidate.kind) is TargetKind
        and type(candidate.identity) is str
        and bool(candidate.identity.strip())
        and type(candidate.state) is TargetState
        and type(candidate.relationship) is Relationship
        and type(candidate.evidence) is tuple
        and all(type(item) is str and bool(item.strip()) for item in candidate.evidence)
    )


def _has_mismatched_candidate_kind(request: RiskTriageInput) -> bool:
    groups = (
        (request.current_work_candidates, TargetKind.CURRENT_WORK),
        (request.existing_issue_candidates, TargetKind.EXISTING_ISSUE),
        (request.canonical_risk_owners, TargetKind.CANONICAL_RISK_OWNER),
    )
    return any(
        candidate.kind is not expected_kind
        for candidates, expected_kind in groups
        for candidate in candidates
    )


def _canonical_owner_result(
    candidates: tuple[CandidateEvidence, ...],
) -> RiskTriageResult | None:
    valid = tuple(
        candidate
        for candidate in candidates
        if candidate.kind is TargetKind.CANONICAL_RISK_OWNER
        and candidate.state in _VALID_STATES
        and candidate.relationship in _MATCH_RELATIONSHIPS
    )
    identities = {candidate.identity for candidate in valid}
    if len(identities) > 1:
        return _decision("canonical-owner.conflict")
    if valid:
        return _target_result(
            Disposition.LINK_CANONICAL_RISK_OWNER,
            "canonical-owner.unambiguous",
            valid[0],
        )
    return None


def _candidate_result(
    candidates: tuple[CandidateEvidence, ...],
    kind: TargetKind,
    disposition: Disposition,
    reason: str,
) -> RiskTriageResult | None:
    valid = tuple(
        candidate
        for candidate in candidates
        if candidate.kind is kind
        and candidate.state in _VALID_STATES
        and candidate.relationship in _MATCH_RELATIONSHIPS
    )
    identities = {candidate.identity for candidate in valid}
    if len(identities) > 1:
        return _decision(f"{kind.value}.multiple-matches")
    if valid:
        return _target_result(disposition, reason, valid[0])
    return None


def _invalid_candidates(candidates: tuple[CandidateEvidence, ...]) -> tuple[CandidateEvidence, ...]:
    return tuple(
        candidate
        for candidate in candidates
        if candidate.state in {
            TargetState.CLOSED,
            TargetState.STALE,
            TargetState.RETIRED_SCOPE,
            TargetState.UNKNOWN,
        }
        and candidate.relationship is not Relationship.DISTINCT
    )


def _has_unproven_similarity(candidates: tuple[CandidateEvidence, ...]) -> bool:
    return any(
        candidate.state in _VALID_STATES and candidate.relationship is Relationship.UNKNOWN
        for candidate in candidates
    )


def _has_conflicting_distinct_targets(candidates: tuple[CandidateEvidence, ...]) -> bool:
    live = {
        candidate.identity
        for candidate in candidates
        if candidate.state in _VALID_STATES
        and candidate.relationship not in {Relationship.DISTINCT, Relationship.CHILD}
    }
    return len(live) > 1


def _target_result(
    disposition: Disposition,
    reason: str,
    candidate: CandidateEvidence,
) -> RiskTriageResult:
    return RiskTriageResult(
        disposition=disposition,
        reason_codes=(reason,),
        target_identity=candidate.identity,
        target_kind=candidate.kind,
        target_evidence=candidate.evidence,
    )


def _decision(reason: str) -> RiskTriageResult:
    return RiskTriageResult(
        disposition=Disposition.NEEDS_DECISION,
        reason_codes=(reason,),
    )
