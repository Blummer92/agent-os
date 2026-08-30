"""Pure-local deterministic risk-to-issue triage for #1296.

The core consumes caller-supplied structured evidence only.  It performs no
retrieval, mutation, subprocess, credential, network, or authorization work.
Every result is advisory and preserves explicit target identity where one is
supplied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class RiskDisposition(str, Enum):
    NO_ACTION = "no-action"
    RECORD_IN_CURRENT_WORK = "record-in-current-work"
    LINK_CANONICAL_RISK_OWNER = "link-canonical-risk-owner"
    UPDATE_EXISTING_ISSUE_CANDIDATE = "update-existing-issue-candidate"
    CREATE_CHILD_ISSUE_CANDIDATE = "create-child-issue-candidate"
    CREATE_NEW_ISSUE_CANDIDATE = "create-new-issue-candidate"
    NEEDS_DECISION = "needs-decision"


class CandidateState(str, Enum):
    CURRENT = "current"
    CLOSED = "closed"
    STALE = "stale"
    RETIRED_SCOPE = "retired-scope"
    UNKNOWN = "unknown"


class Relationship(str, Enum):
    EXACT = "exact"
    OVERLAP = "overlap"
    CHILD = "child"
    NONE = "none"
    UNKNOWN = "unknown"


_REASON_CODES = frozenset(
    {
        "finding.no-action",
        "current-work.explicit-target",
        "canonical-owner.explicit-target",
        "existing-issue.explicit-target",
        "issue-candidate.child-relationship",
        "issue-candidate.new-risk",
        "evidence.manual-review",
        "evidence.conflicting-targets",
        "canonical-owner.conflict",
        "candidate.not-current",
        "relationship.ambiguous",
        "equivalence.unproven",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateEvidence:
    identity: str
    state: CandidateState = CandidateState.CURRENT
    relationship: Relationship = Relationship.UNKNOWN
    exact_equivalent: bool = False
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.identity.strip():
            raise ValueError("candidate identity must be non-empty")
        if len(self.evidence) > 32:
            raise ValueError("candidate evidence is bounded to 32 entries")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskFindingEvidence:
    finding_id: str
    finding_text: str
    likelihood: str | None = None
    impact: str | None = None
    current_work: tuple[CandidateEvidence, ...] = ()
    existing_issues: tuple[CandidateEvidence, ...] = ()
    canonical_risk_owners: tuple[CandidateEvidence, ...] = ()
    manual_review_required: bool = False
    no_action_evidence: bool = False

    def __post_init__(self) -> None:
        if not self.finding_id.strip():
            raise ValueError("finding_id must be non-empty")
        if not self.finding_text.strip():
            raise ValueError("finding_text must be non-empty")
        for values, name in (
            (self.current_work, "current_work"),
            (self.existing_issues, "existing_issues"),
            (self.canonical_risk_owners, "canonical_risk_owners"),
        ):
            if len(values) > 16:
                raise ValueError(f"{name} is bounded to 16 candidates")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskTriageResult:
    disposition: RiskDisposition
    reason_codes: tuple[str, ...]
    target_identity: str | None = None
    target_evidence: tuple[str, ...] = ()
    finding_id: str
    likelihood: str | None = None
    impact: str | None = None
    execution_authorized: Literal[False] = field(default=False, init=False)
    external_write_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("at least one reason code is required")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason codes must be sorted and unique")
        if any(code not in _REASON_CODES for code in self.reason_codes):
            raise ValueError("unknown reason code")


def _valid_current(candidates: tuple[CandidateEvidence, ...]) -> tuple[CandidateEvidence, ...]:
    return tuple(c for c in candidates if c.state is CandidateState.CURRENT)


def _invalid_present(candidates: tuple[CandidateEvidence, ...]) -> bool:
    return any(c.state is not CandidateState.CURRENT for c in candidates)


def _result(
    evidence: RiskFindingEvidence,
    disposition: RiskDisposition,
    *reasons: str,
    target: CandidateEvidence | None = None,
) -> RiskTriageResult:
    return RiskTriageResult(
        disposition=disposition,
        reason_codes=tuple(sorted(set(reasons))),
        target_identity=None if target is None else target.identity,
        target_evidence=() if target is None else target.evidence,
        finding_id=evidence.finding_id,
        likelihood=evidence.likelihood,
        impact=evidence.impact,
    )


def triage_risk_finding(evidence: RiskFindingEvidence) -> RiskTriageResult:
    """Return one advisory disposition from explicit structured evidence.

    Precedence is intentionally fail-closed.  Manual-review evidence,
    conflicting targets, invalid/stale supplied targets, or ambiguity are
    resolved before any positive target recommendation.  Free-form finding text
    is never used for equivalence or near-duplicate inference.
    """
    if type(evidence) is not RiskFindingEvidence:
        raise TypeError("evidence must be exact RiskFindingEvidence")

    if evidence.manual_review_required:
        return _result(evidence, RiskDisposition.NEEDS_DECISION, "evidence.manual-review")

    groups = (evidence.current_work, evidence.existing_issues, evidence.canonical_risk_owners)
    if any(_invalid_present(group) for group in groups):
        return _result(evidence, RiskDisposition.NEEDS_DECISION, "candidate.not-current")

    current_work = _valid_current(evidence.current_work)
    existing = _valid_current(evidence.existing_issues)
    owners = _valid_current(evidence.canonical_risk_owners)

    if len(owners) > 1:
        return _result(evidence, RiskDisposition.NEEDS_DECISION, "canonical-owner.conflict")
    if len(current_work) > 1 or len(existing) > 1:
        return _result(evidence, RiskDisposition.NEEDS_DECISION, "evidence.conflicting-targets")

    explicit_targets = int(bool(current_work)) + int(bool(existing)) + int(bool(owners))
    if explicit_targets > 1:
        return _result(evidence, RiskDisposition.NEEDS_DECISION, "evidence.conflicting-targets")

    if owners:
        return _result(
            evidence,
            RiskDisposition.LINK_CANONICAL_RISK_OWNER,
            "canonical-owner.explicit-target",
            target=owners[0],
        )

    if current_work:
        target = current_work[0]
        if target.exact_equivalent or target.relationship in {Relationship.EXACT, Relationship.OVERLAP}:
            return _result(
                evidence,
                RiskDisposition.RECORD_IN_CURRENT_WORK,
                "current-work.explicit-target",
                target=target,
            )
        return _result(evidence, RiskDisposition.NEEDS_DECISION, "equivalence.unproven", target=target)

    if existing:
        target = existing[0]
        if target.exact_equivalent or target.relationship in {Relationship.EXACT, Relationship.OVERLAP}:
            return _result(
                evidence,
                RiskDisposition.UPDATE_EXISTING_ISSUE_CANDIDATE,
                "existing-issue.explicit-target",
                target=target,
            )
        if target.relationship is Relationship.CHILD:
            return _result(
                evidence,
                RiskDisposition.CREATE_CHILD_ISSUE_CANDIDATE,
                "issue-candidate.child-relationship",
                target=target,
            )
        if target.relationship is Relationship.UNKNOWN:
            return _result(evidence, RiskDisposition.NEEDS_DECISION, "relationship.ambiguous", target=target)

    if evidence.no_action_evidence:
        return _result(evidence, RiskDisposition.NO_ACTION, "finding.no-action")

    return _result(evidence, RiskDisposition.CREATE_NEW_ISSUE_CANDIDATE, "issue-candidate.new-risk")


__all__ = [
    "CandidateEvidence",
    "CandidateState",
    "Relationship",
    "RiskDisposition",
    "RiskFindingEvidence",
    "RiskTriageResult",
    "triage_risk_finding",
]
