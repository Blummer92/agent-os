"""Pure, injected cancellation contract for one proven-superseded Cloud Build.

Cancellation is a request, never proof of execution termination.  This module
performs no network, Cloud SDK, Scheduler, retry, lease-release, or GitHub work;
a caller supplies exact currentness/supersession/identity evidence and an
injected cancellation client.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .models import ProviderObservationStatus


class CancellationEligibility(str, Enum):
    CANCEL_ELIGIBLE = "cancel-eligible"
    NOT_SUPERSEDED = "not-superseded"
    NOT_RUNNING = "not-running"
    IDENTITY_MISMATCH = "identity-mismatch"
    CANCELLATION_ALREADY_REQUESTED = "cancellation-already-requested"
    AMBIGUOUS = "ambiguous"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildCancellationEvidence:
    repository_matches: bool
    pr_matches: bool
    obsolete_sha: str
    current_head_sha: str | None
    supersession_proven: bool
    lane_plan_dispatch_match: bool
    invocation_id_known: bool
    build_id: str | None
    project_id: str | None
    location: str | None
    observation_status: ProviderObservationStatus
    execution_lease_match: bool
    final_head_aggregate_preserved: bool
    identity_ambiguous: bool = False
    prior_request_accepted: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class CancellationDecision:
    outcome: CancellationEligibility
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildCancellationRequest:
    build_id: str
    project_id: str
    location: str
    invocation_id: str
    obsolete_sha: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildCancellationOutcome:
    accepted: bool
    diagnostic: str = ""


@runtime_checkable
class CloudBuildCancellationClient(Protocol):
    def cancel(self, request: CloudBuildCancellationRequest) -> CloudBuildCancellationOutcome: ...


def evaluate_cancellation(evidence: CloudBuildCancellationEvidence) -> CancellationDecision:
    """Return one fail-closed eligibility decision from exact bounded evidence."""
    if type(evidence) is not CloudBuildCancellationEvidence:
        raise TypeError("evidence must be exact CloudBuildCancellationEvidence")
    if evidence.identity_ambiguous:
        return CancellationDecision(outcome=CancellationEligibility.AMBIGUOUS, reason="identity/currentness/provider evidence is ambiguous")
    if evidence.prior_request_accepted:
        return CancellationDecision(outcome=CancellationEligibility.CANCELLATION_ALREADY_REQUESTED, reason="cancellation request was already accepted")
    if evidence.observation_status is not ProviderObservationStatus.WORKING:
        return CancellationDecision(outcome=CancellationEligibility.NOT_RUNNING, reason="exact provider observation is not WORKING")
    if evidence.current_head_sha is None or evidence.current_head_sha == evidence.obsolete_sha or not evidence.supersession_proven:
        return CancellationDecision(outcome=CancellationEligibility.NOT_SUPERSEDED, reason="exact newer current head and supersession proof are required")
    identities_match = all((
        evidence.repository_matches,
        evidence.pr_matches,
        evidence.lane_plan_dispatch_match,
        evidence.invocation_id_known,
        bool(evidence.build_id),
        bool(evidence.project_id),
        bool(evidence.location),
        evidence.execution_lease_match,
        evidence.final_head_aggregate_preserved,
    ))
    if not identities_match:
        return CancellationDecision(outcome=CancellationEligibility.IDENTITY_MISMATCH, reason="one or more required exact identity bindings do not match")
    return CancellationDecision(outcome=CancellationEligibility.CANCEL_ELIGIBLE, reason="exact superseded WORKING build is eligible for one cancellation request")


class SupersededBuildCancellation:
    """One-shot injected cancellation requester; acceptance is not termination."""
    def __init__(self, *, client: CloudBuildCancellationClient) -> None:
        if not isinstance(client, CloudBuildCancellationClient):
            raise TypeError("client does not satisfy CloudBuildCancellationClient")
        self._client = client
        self._requested = False

    def request(self, evidence: CloudBuildCancellationEvidence, *, invocation_id: str) -> CloudBuildCancellationOutcome | None:
        decision = evaluate_cancellation(evidence)
        if decision.outcome is not CancellationEligibility.CANCEL_ELIGIBLE:
            return None
        if self._requested:
            return None
        self._requested = True
        return self._client.cancel(CloudBuildCancellationRequest(
            build_id=evidence.build_id or "",
            project_id=evidence.project_id or "",
            location=evidence.location or "",
            invocation_id=invocation_id,
            obsolete_sha=evidence.obsolete_sha,
        ))
