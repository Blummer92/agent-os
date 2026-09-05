"""Bounded live route-context acquisition for first-publication activation (#1948).

This module verifies one exact source-capsule lineage against structured GitHub
state and composes existing #1451/#863/#864 owners. It is not a generic claim,
lifecycle, freshness, or route authority and performs no writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from scripts.agent_os_candidate_packet.executable_lane_selection import (
    CandidateIssueEvidence,
    ExecutableLaneSelection,
    select_executable_lanes,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorityProjection,
    FreshnessState,
    LifecycleStage,
    PrimaryIssueClaim,
)
from scripts.agent_os_issue_acceptance.issue_operational_state_acquisition import (
    AcquiredIssueOperationalEvidence,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    AgentOperatingModeDecision,
    EnvironmentCapabilityEvidence,
    RequestedMode,
    evaluate_operating_mode_decision,
)


class LiveRouteContextError(RuntimeError):
    """Exact live route context cannot be proven."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredPullRequest:
    number: int
    branch: str
    head_sha: str
    draft: bool
    merged: bool
    state: str


class ExactLineageGitHubReader(Protocol):
    """Read-only structured GitHub facts for one already-fixed lineage."""

    def current_branch_head(self, repository: str, branch: str) -> str: ...

    def pull_requests_for_head(
        self, repository: str, branch: str
    ) -> tuple[StructuredPullRequest, ...]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ExactSourceLineage:
    source_capsule_id: str
    repository: str
    issue_number: int
    branch: str
    source_sha: str
    tested_sha: str

    def __post_init__(self) -> None:
        if type(self.source_capsule_id) is not str or not self.source_capsule_id.startswith(
            "pre-publication-evidence:"
        ):
            raise ValueError("source_capsule_id is malformed")
        if type(self.repository) is not str or self.repository.count("/") != 1:
            raise ValueError("repository must use owner/name form")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive exact integer")
        if type(self.branch) is not str or not self.branch or self.branch == "main":
            raise ValueError("branch is malformed or protected")
        for name in ("source_sha", "tested_sha"):
            value = getattr(self, name)
            if (
                type(value) is not str
                or len(value) != 40
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{name} must be a lowercase 40-character SHA")


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedLineageState:
    lifecycle_stage: LifecycleStage
    primary_claims: tuple[PrimaryIssueClaim, ...]
    primary_claim: PrimaryIssueClaim | None
    current_head_sha: str
    freshness_state: FreshnessState


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveRouteContext:
    operational: AcquiredIssueOperationalEvidence
    operating_mode: AgentOperatingModeDecision
    lane_selection: ExecutableLaneSelection
    lineage: VerifiedLineageState
    execution_authorization: AuthorityProjection


def verify_exact_lineage(
    lineage: ExactSourceLineage,
    *,
    reader: ExactLineageGitHubReader,
    issue_open: bool,
) -> VerifiedLineageState:
    """Verify the capsule's exact branch/head and classify only that lineage."""
    if type(lineage) is not ExactSourceLineage:
        raise TypeError("lineage must be exact ExactSourceLineage")
    if type(issue_open) is not bool:
        raise TypeError("issue_open must be exact bool")
    head = reader.current_branch_head(lineage.repository, lineage.branch)
    if head != lineage.source_sha or lineage.tested_sha != lineage.source_sha:
        raise LiveRouteContextError("source-lineage-stale")

    prs = reader.pull_requests_for_head(lineage.repository, lineage.branch)
    if type(prs) is not tuple or any(type(item) is not StructuredPullRequest for item in prs):
        raise LiveRouteContextError("pull-request-evidence-malformed")
    matches = tuple(
        item
        for item in prs
        if item.branch == lineage.branch and item.head_sha == head
    )
    if len(matches) > 1:
        raise LiveRouteContextError("source-lineage-ambiguous")
    if not issue_open:
        if matches and not matches[0].merged:
            raise LiveRouteContextError("closed-issue-lineage-conflict")
        stage = LifecycleStage.CLOSED
        claim = None if not matches else _claim(matches[0])
    elif not matches:
        stage = LifecycleStage.IMPLEMENTATION
        claim = None
    else:
        pr = matches[0]
        claim = _claim(pr)
        if pr.merged:
            stage = LifecycleStage.MERGED
        elif pr.state != "open":
            raise LiveRouteContextError("pull-request-state-conflict")
        elif pr.draft:
            stage = LifecycleStage.DRAFT_PR
        else:
            stage = LifecycleStage.REVIEW
    claims = () if claim is None else (claim,)
    return VerifiedLineageState(
        lifecycle_stage=stage,
        primary_claims=claims,
        primary_claim=claim,
        current_head_sha=head,
        freshness_state=FreshnessState.CURRENT,
    )


def build_live_route_context(
    *,
    lineage: ExactSourceLineage,
    verified: VerifiedLineageState,
    operational: AcquiredIssueOperationalEvidence,
    environment: EnvironmentCapabilityEvidence,
    execution_authorization: AuthorityProjection,
) -> LiveRouteContext:
    """Compose existing mode/lane owners for one fixed non-substitutable issue."""
    if type(verified) is not VerifiedLineageState:
        raise TypeError("verified must be exact VerifiedLineageState")
    if type(operational) is not AcquiredIssueOperationalEvidence:
        raise TypeError("operational must be exact AcquiredIssueOperationalEvidence")
    if type(environment) is not EnvironmentCapabilityEvidence:
        raise TypeError("environment must be exact EnvironmentCapabilityEvidence")
    if type(execution_authorization) is not AuthorityProjection:
        raise TypeError("execution_authorization must be exact AuthorityProjection")
    state = operational.operational_state
    if (
        state.repository.casefold() != lineage.repository.casefold()
        or state.issue_number != lineage.issue_number
        or state.lifecycle_stage is not verified.lifecycle_stage
        or state.freshness_state is not FreshnessState.CURRENT
        or state.primary_claim_ids
        != tuple(claim.claim_id for claim in verified.primary_claims)
    ):
        raise LiveRouteContextError("operational-state-lineage-mismatch")

    mode = evaluate_operating_mode_decision(state, RequestedMode.BUILD.value, environment)
    selection = select_executable_lanes(
        campaign_id=lineage.source_capsule_id,
        requested_lane_count=1,
        substitution_allowed=False,
        explicit_request_order=(lineage.issue_number,),
        candidates=(
            CandidateIssueEvidence(
                issue_number=lineage.issue_number,
                operational_state=state,
                mode_decision=mode,
                dependency_depth=0,
                substitutable=False,
            ),
        ),
    )
    if selection.selected_lanes != (lineage.issue_number,):
        raise LiveRouteContextError("source-lineage-not-executable")
    return LiveRouteContext(
        operational=operational,
        operating_mode=mode,
        lane_selection=selection,
        lineage=verified,
        execution_authorization=execution_authorization,
    )


def _claim(value: StructuredPullRequest) -> PrimaryIssueClaim:
    if value.merged:
        state = "merged"
    elif value.state != "open":
        raise LiveRouteContextError("pull-request-state-conflict")
    else:
        state = "draft" if value.draft else "ready"
    return PrimaryIssueClaim(
        pull_request_number=value.number,
        branch=value.branch,
        head_sha=value.head_sha,
        state=state,
    )
