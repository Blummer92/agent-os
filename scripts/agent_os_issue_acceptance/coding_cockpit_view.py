"""Bounded operator view for the Agent OS Coding Cockpit.

This module composes the existing CodingCommandCenterHandoff and its canonical
IssueOperationalState. It adds presentation only: no state, authority, routing,
validation, execution, or external-write semantics are derived here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .coding_command_center_handoff import CodingCommandCenterHandoff
from .issue_operational_state import IssueOperationalState, OperationalOutcome

_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CodingCockpitView:
    repository: str
    issue_number: int
    pull_request_number: int | None
    branch: str | None
    exact_head_sha: str | None
    state: str
    current_stage: str
    owner_or_route: str | None
    validation_state: str
    validation_evidence_reference: str | None
    freshness: str
    primary_blocker: str | None
    manual_review_required: bool
    smallest_next_action: str
    execution_surface: str | None
    canonical_state_reference: str
    source_revision: str
    handoff_target: str | None
    authority_created: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def build_coding_cockpit_view(
    handoff: CodingCommandCenterHandoff,
    operational_state: IssueOperationalState,
) -> CodingCockpitView:
    """Compose a concise cockpit view from existing canonical projections."""
    if type(handoff) is not CodingCommandCenterHandoff:
        raise TypeError("handoff must be exact CodingCommandCenterHandoff")
    if type(operational_state) is not IssueOperationalState:
        raise TypeError("operational_state must be exact IssueOperationalState")
    handoff.__post_init__()
    operational_state.__post_init__()
    if (
        handoff.repository != operational_state.repository
        or handoff.issue_number != operational_state.issue_number
        or handoff.canonical_state_reference != operational_state.state_id
        or handoff.source_revision != operational_state.source_revision
    ):
        raise ValueError("cockpit inputs do not identify the same canonical state")

    claims = operational_state.primary_claims
    branch = claims[0].branch if len(claims) == 1 else None
    claim_head = claims[0].head_sha if len(claims) == 1 else None
    if handoff.observed_head_sha is not None and claim_head is not None and handoff.observed_head_sha != claim_head:
        raise ValueError("cockpit head identity conflicts with canonical primary claim")
    exact_head = handoff.observed_head_sha or claim_head

    manual_review = operational_state.outcome in {
        OperationalOutcome.NEEDS_DECISION,
        OperationalOutcome.STALE,
        OperationalOutcome.CONFLICTING,
        OperationalOutcome.INVALID,
    }
    route = handoff.executor_route
    if route == "human_decision":
        manual_review = True

    return CodingCockpitView(
        repository=handoff.repository,
        issue_number=handoff.issue_number,
        pull_request_number=handoff.pull_request_number,
        branch=branch,
        exact_head_sha=exact_head,
        state=operational_state.outcome.value,
        current_stage=handoff.current_stage,
        owner_or_route=route,
        validation_state=operational_state.validation_state.value,
        validation_evidence_reference=handoff.validation_evidence_reference,
        freshness=operational_state.freshness_state.value,
        primary_blocker=handoff.primary_blocker,
        manual_review_required=manual_review,
        smallest_next_action=handoff.smallest_next_action,
        execution_surface=route,
        canonical_state_reference=handoff.canonical_state_reference,
        source_revision=handoff.source_revision,
        handoff_target=handoff.handoff_target,
    )


def render_coding_cockpit_view(view: CodingCockpitView) -> str:
    """Render the concise solo-operator cockpit without creating semantics."""
    if type(view) is not CodingCockpitView:
        raise TypeError("view must be exact CodingCockpitView")
    pr = str(view.pull_request_number) if view.pull_request_number is not None else _UNAVAILABLE
    branch = view.branch or _UNAVAILABLE
    head = view.exact_head_sha or _UNAVAILABLE
    route = view.owner_or_route or _UNAVAILABLE
    evidence = view.validation_evidence_reference or _UNAVAILABLE
    blocker = view.primary_blocker or _UNAVAILABLE
    handoff = view.handoff_target or _UNAVAILABLE
    return "\n".join(
        (
            f"Current mission: {view.repository}#{view.issue_number} | PR {pr} | {branch} | {head}",
            f"State: {view.state} ({view.current_stage})",
            f"Owner / route: {route}",
            f"Validation: {view.validation_state} | evidence={evidence} | freshness={view.freshness}",
            f"Blocker: {blocker}",
            f"Manual review required: {'yes' if view.manual_review_required else 'no'}",
            f"Next action: {view.smallest_next_action}",
            f"Execution surface: {route}",
            f"Handoff: {handoff}",
            f"Evidence: state={view.canonical_state_reference}; source_revision={view.source_revision}",
            "Authority: display-only; no authority created",
        )
    )
