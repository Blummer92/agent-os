"""Pure self-defect triage bridge for Agent OS issue handoffs.

This module performs no GitHub I/O. The ChatGPT execution interface supplies
canonical contract evidence and bounded GitHub issue-search candidates; the
GitHub Service Agent remains the sole writer. Existing continuation, recovery,
and issue-create adapters remain authoritative for their own domains.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum


class SelfDefectClass(str, Enum):
    EXPECTED_DOMAIN_FAILURE = "expected-domain-failure"
    EXECUTION_SURFACE_CAPABILITY = "execution-surface-capability"
    AUTHORIZATION_OR_GOVERNANCE_BLOCKER = "authorization-or-governance-blocker"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"
    AGENT_OS_CONTRACT_VIOLATION = "agent-os-contract-violation"


class SelfDefectAction(str, Enum):
    NO_META_BUG = "no-meta-bug"
    ROUTE_EXISTING_CAPABILITY = "route-existing-capability"
    STOP_EXPLICITLY = "stop-explicitly"
    MANUAL_REVIEW = "manual-review"
    HARDEN_EXISTING_ISSUE = "harden-existing-issue"
    CREATE_FOCUSED_ISSUE = "create-focused-issue"


@dataclass(frozen=True, slots=True)
class DefectObservation:
    repository: str
    mission_identity: str
    governing_contract: str
    failure_signature: str
    expected_behavior: str
    observed_behavior: str
    evidence_sufficient: bool
    original_mission_actionable: bool


@dataclass(frozen=True, slots=True)
class IssueCandidate:
    issue_number: int
    governing_contract: str
    failure_signature: str
    state: str = "open"


@dataclass(frozen=True, slots=True)
class SelfDefectDecision:
    classification: SelfDefectClass
    action: SelfDefectAction
    defect_identity: str | None
    existing_issue_number: int | None
    continue_original_mission: bool
    mutation_allowed: bool
    reason_codes: tuple[str, ...]


def build_defect_identity(observation: DefectObservation) -> str:
    """Return a stable semantic identity without inventing recovery state."""
    payload = {
        "domain": "agent-os.self-defect.v1",
        "repository": _required(observation.repository, "repository"),
        "governing_contract": _required(
            observation.governing_contract, "governing_contract"
        ),
        "failure_signature": _required(
            observation.failure_signature, "failure_signature"
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def decide_self_defect(
    observation: DefectObservation,
    *,
    classification: SelfDefectClass,
    candidates: tuple[IssueCandidate, ...] = (),
    prior_mutation_identities: tuple[str, ...] = (),
) -> SelfDefectDecision:
    """Project one bounded handoff decision; never perform a mutation."""
    _validate_observation(observation)
    if type(classification) is not SelfDefectClass:
        raise ValueError("classification must be SelfDefectClass")
    for candidate in candidates:
        _validate_candidate(candidate)

    if classification is SelfDefectClass.EXPECTED_DOMAIN_FAILURE:
        return _decision(classification, SelfDefectAction.NO_META_BUG, observation)
    if classification is SelfDefectClass.EXECUTION_SURFACE_CAPABILITY:
        return _decision(
            classification,
            SelfDefectAction.ROUTE_EXISTING_CAPABILITY,
            observation,
            reasons=("consume-1237",),
        )
    if classification is SelfDefectClass.AUTHORIZATION_OR_GOVERNANCE_BLOCKER:
        return _decision(
            classification,
            SelfDefectAction.STOP_EXPLICITLY,
            observation,
            reasons=("authority-boundary",),
        )
    if (
        classification is SelfDefectClass.INSUFFICIENT_EVIDENCE
        or not observation.evidence_sufficient
    ):
        return _decision(
            SelfDefectClass.INSUFFICIENT_EVIDENCE,
            SelfDefectAction.MANUAL_REVIEW,
            observation,
            reasons=("insufficient-canonical-evidence",),
        )

    identity = build_defect_identity(observation)
    matches = tuple(
        candidate
        for candidate in candidates
        if candidate.governing_contract == observation.governing_contract
        and candidate.failure_signature == observation.failure_signature
    )
    closed_matches = tuple(candidate for candidate in matches if candidate.state == "closed")
    if closed_matches:
        return SelfDefectDecision(
            classification=classification,
            action=SelfDefectAction.MANUAL_REVIEW,
            defect_identity=identity,
            existing_issue_number=None,
            continue_original_mission=False,
            mutation_allowed=False,
            reason_codes=("closed-match-requires-regression-lifecycle-decision",),
        )

    issue_numbers = tuple(
        sorted({candidate.issue_number for candidate in matches if candidate.state == "open"})
    )
    if len(issue_numbers) > 1:
        return SelfDefectDecision(
            classification=classification,
            action=SelfDefectAction.MANUAL_REVIEW,
            defect_identity=identity,
            existing_issue_number=None,
            continue_original_mission=False,
            mutation_allowed=False,
            reason_codes=("ambiguous-existing-issue-ownership",),
        )

    target_number = issue_numbers[0] if issue_numbers else None
    mutation_identity = _mutation_identity(identity, target_number)
    if mutation_identity in prior_mutation_identities:
        return SelfDefectDecision(
            classification=classification,
            action=(
                SelfDefectAction.HARDEN_EXISTING_ISSUE
                if target_number is not None
                else SelfDefectAction.CREATE_FOCUSED_ISSUE
            ),
            defect_identity=identity,
            existing_issue_number=target_number,
            continue_original_mission=observation.original_mission_actionable,
            mutation_allowed=False,
            reason_codes=("equivalent-mutation-already-recorded",),
        )

    return SelfDefectDecision(
        classification=classification,
        action=(
            SelfDefectAction.HARDEN_EXISTING_ISSUE
            if target_number is not None
            else SelfDefectAction.CREATE_FOCUSED_ISSUE
        ),
        defect_identity=identity,
        existing_issue_number=target_number,
        continue_original_mission=observation.original_mission_actionable,
        mutation_allowed=True,
        reason_codes=(
            "known-defect" if target_number is not None else "novel-defect",
            "github-service-agent-write-owner",
            "mutation-is-intermediate-not-terminal",
        ),
    )


def mutation_identity_for(decision: SelfDefectDecision) -> str | None:
    if decision.defect_identity is None:
        return None
    return _mutation_identity(decision.defect_identity, decision.existing_issue_number)


def _decision(
    classification: SelfDefectClass,
    action: SelfDefectAction,
    observation: DefectObservation,
    *,
    reasons: tuple[str, ...] = (),
) -> SelfDefectDecision:
    return SelfDefectDecision(
        classification=classification,
        action=action,
        defect_identity=None,
        existing_issue_number=None,
        continue_original_mission=(
            observation.original_mission_actionable
            and action
            not in {SelfDefectAction.STOP_EXPLICITLY, SelfDefectAction.MANUAL_REVIEW}
        ),
        mutation_allowed=False,
        reason_codes=reasons,
    )


def _mutation_identity(defect_identity: str, issue_number: int | None) -> str:
    target = f"issue:{issue_number}" if issue_number is not None else "issue:create"
    return f"self-defect:{defect_identity}:{target}"


def _validate_observation(observation: DefectObservation) -> None:
    _required(observation.repository, "repository")
    _required(observation.mission_identity, "mission_identity")
    _required(observation.governing_contract, "governing_contract")
    _required(observation.failure_signature, "failure_signature")
    _required(observation.expected_behavior, "expected_behavior")
    _required(observation.observed_behavior, "observed_behavior")
    if type(observation.evidence_sufficient) is not bool:
        raise ValueError("evidence_sufficient must be a boolean")
    if type(observation.original_mission_actionable) is not bool:
        raise ValueError("original_mission_actionable must be a boolean")


def _validate_candidate(candidate: IssueCandidate) -> None:
    if type(candidate) is not IssueCandidate:
        raise ValueError("candidates must contain IssueCandidate values")
    if type(candidate.issue_number) is not int or candidate.issue_number <= 0:
        raise ValueError("candidate issue_number must be a positive integer")
    _required(candidate.governing_contract, "candidate governing_contract")
    _required(candidate.failure_signature, "candidate failure_signature")
    if candidate.state not in {"open", "closed"}:
        raise ValueError("candidate state must be open or closed")


def _required(value: str, name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")
    return value
