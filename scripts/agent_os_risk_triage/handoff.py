"""Side-effect-free handoff from RIT1 dispositions to existing issue contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .core import Disposition, RiskTriageResult, TargetKind


class HandoffRoute(str, Enum):
    """Finite advisory routes owned by existing downstream contracts."""

    NO_ACTION = "no-action"
    CURRENT_WORK = "current-work"
    CANONICAL_RISK_OWNER = "canonical-risk-owner"
    EXISTING_ISSUE = "existing-issue"
    ISSUE_DRAFT_ADMISSION = "issue-draft-admission"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class RiskTriageHandoff:
    route: HandoffRoute
    reason_codes: tuple[str, ...]
    target_identity: str | None = None
    target_kind: TargetKind | None = None
    target_evidence: tuple[str, ...] = ()
    downstream_contracts: tuple[str, ...] = ()
    mutation_performed: bool = field(default=False, init=False)
    write_authorized: bool = field(default=False, init=False)


_TARGET_ROUTES = {
    Disposition.RECORD_IN_CURRENT_WORK: (HandoffRoute.CURRENT_WORK, TargetKind.CURRENT_WORK),
    Disposition.LINK_CANONICAL_RISK_OWNER: (
        HandoffRoute.CANONICAL_RISK_OWNER,
        TargetKind.CANONICAL_RISK_OWNER,
    ),
    Disposition.UPDATE_EXISTING_ISSUE_CANDIDATE: (
        HandoffRoute.EXISTING_ISSUE,
        TargetKind.EXISTING_ISSUE,
    ),
}

_CREATE_CONTRACTS = (
    "scripts.agent_os_issue_labels.draft",
    "scripts.agent_os_issue_labels.validation",
    "scripts.agent_os_issue_labels.connected_issue_creation",
)


def plan_risk_triage_handoff(result: RiskTriageResult) -> RiskTriageHandoff:
    """Project one RIT1 result into one non-authorizing downstream route."""
    if type(result) is not RiskTriageResult or not _valid_reason_codes(result.reason_codes):
        return _manual_review("handoff.malformed-result")

    if result.mutation_performed or result.write_authorized:
        return _manual_review("handoff.upstream-authority-invalid")

    if result.disposition is Disposition.NO_ACTION:
        if _has_target(result):
            return _manual_review("handoff.unexpected-target")
        return RiskTriageHandoff(HandoffRoute.NO_ACTION, result.reason_codes)

    if result.disposition is Disposition.NEEDS_DECISION:
        if _has_target(result):
            return _manual_review("handoff.unexpected-target")
        return RiskTriageHandoff(HandoffRoute.MANUAL_REVIEW, result.reason_codes)

    target_route = _TARGET_ROUTES.get(result.disposition)
    if target_route is not None:
        route, expected_kind = target_route
        if not _valid_target(result, expected_kind):
            return _manual_review("handoff.target-evidence-missing-or-incompatible")
        return RiskTriageHandoff(
            route=route,
            reason_codes=result.reason_codes,
            target_identity=result.target_identity,
            target_kind=result.target_kind,
            target_evidence=result.target_evidence,
        )

    if result.disposition is Disposition.CREATE_CHILD_ISSUE_CANDIDATE:
        if not _valid_target(result, TargetKind.EXISTING_ISSUE):
            return _manual_review("handoff.child-parent-evidence-missing-or-incompatible")
        return RiskTriageHandoff(
            route=HandoffRoute.ISSUE_DRAFT_ADMISSION,
            reason_codes=result.reason_codes,
            target_identity=result.target_identity,
            target_kind=result.target_kind,
            target_evidence=result.target_evidence,
            downstream_contracts=_CREATE_CONTRACTS,
        )

    if result.disposition is Disposition.CREATE_NEW_ISSUE_CANDIDATE:
        if _has_target(result):
            return _manual_review("handoff.unexpected-target")
        return RiskTriageHandoff(
            route=HandoffRoute.ISSUE_DRAFT_ADMISSION,
            reason_codes=result.reason_codes,
            downstream_contracts=_CREATE_CONTRACTS,
        )

    return _manual_review("handoff.unknown-disposition")


def _valid_reason_codes(reason_codes: object) -> bool:
    return (
        type(reason_codes) is tuple
        and bool(reason_codes)
        and all(type(code) is str and bool(code.strip()) for code in reason_codes)
    )


def _has_target(result: RiskTriageResult) -> bool:
    return (
        result.target_identity is not None
        or result.target_kind is not None
        or bool(result.target_evidence)
    )


def _valid_target(result: RiskTriageResult, expected_kind: TargetKind) -> bool:
    return (
        type(result.target_identity) is str
        and bool(result.target_identity.strip())
        and result.target_kind is expected_kind
        and type(result.target_evidence) is tuple
        and all(type(item) is str and bool(item.strip()) for item in result.target_evidence)
    )


def _manual_review(reason: str) -> RiskTriageHandoff:
    return RiskTriageHandoff(
        route=HandoffRoute.MANUAL_REVIEW,
        reason_codes=(reason,),
    )
