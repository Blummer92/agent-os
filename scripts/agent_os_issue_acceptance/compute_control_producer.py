"""Canonical production composition boundary for #1419 compute control (#1439).

This module deliberately owns no decision semantics.  It accepts already-owned
canonical Agent OS evidence for one exact issue identity, verifies the bounded
identity joins needed to safely compose that evidence, builds or consumes the
existing #1097 Coding Command Center handoff, and invokes the existing #1419
``build_compute_control_projection`` function unchanged.

It performs no GitHub, network, filesystem, subprocess, Scheduler, provider,
Cloud Build, GCP, or Notion I/O; creates no authority; dispatches nothing; and
persists nothing.  External callers remain responsible for reacquiring current
evidence through the owning contracts before invoking this producer.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_remote_validation.models import ValidationPlan
from scripts.agent_os_remote_validation.provenance import EvidenceApplicabilityProjection

from .coding_command_center_handoff import (
    CodingCommandCenterEvidence,
    CodingCommandCenterHandoff,
    build_coding_command_center_handoff,
)
from .compute_control_projection import (
    ActiveExecutionReference,
    ComputeControlEvidence,
    ComputeControlProjection,
    ValidationHeadReference,
    build_compute_control_projection,
    serialize_compute_control_projection,
)
from .issue_operational_state import (
    ClaimState,
    IssueOperationalState,
    PrimaryIssueClaim,
)


@dataclass(frozen=True, slots=True)
class ComputeControlProductionEvidence:
    """Already-owned canonical evidence needed for one #1419 production call.

    Exactly one of ``handoff`` or ``handoff_evidence`` is required.  Supplying
    ``handoff_evidence`` lets this boundary call #1097 immediately before #1419;
    supplying ``handoff`` lets a caller reuse a separately produced canonical
    #1097 record.  Neither path re-derives handoff or compute semantics.

    ``primary_claim`` is the exact canonical claim that supplied the current
    single-PR binding represented by ``operational_state``.  Requiring it when
    the state has a single claim prevents a caller from pairing a current head
    SHA with a different PR/branch lineage merely because both values are
    individually well formed.
    """

    operational_state: IssueOperationalState
    current_head_sha: str | None
    primary_claim: PrimaryIssueClaim | None = None
    handoff: CodingCommandCenterHandoff | None = None
    handoff_evidence: CodingCommandCenterEvidence | None = None
    validation_plan: ValidationPlan | None = None
    evidence_applicability: EvidenceApplicabilityProjection | None = None
    validation_head_reference: ValidationHeadReference | None = None
    active_execution: ActiveExecutionReference | None = None
    measured_compute_metadata_reference: str | None = None

    def __post_init__(self) -> None:
        if type(self.operational_state) is not IssueOperationalState:
            raise TypeError("operational_state must be exact IssueOperationalState")
        # Re-run the content-addressed state invariant so a tampered frozen
        # object cannot cross this production boundary.
        self.operational_state.__post_init__()

        if (self.handoff is None) == (self.handoff_evidence is None):
            raise ValueError("provide exactly one of handoff or handoff_evidence")

        if self.handoff is not None and type(self.handoff) is not CodingCommandCenterHandoff:
            raise TypeError("handoff must be exact CodingCommandCenterHandoff or None")
        if self.handoff_evidence is not None:
            if type(self.handoff_evidence) is not CodingCommandCenterEvidence:
                raise TypeError("handoff_evidence must be exact CodingCommandCenterEvidence or None")
            self.handoff_evidence.__post_init__()
            if self.handoff_evidence.operational_state.state_id != self.operational_state.state_id:
                raise ValueError("handoff evidence and operational state describe different identities")

        self._validate_primary_claim_binding()

        # The existing #1419 ComputeControlEvidence constructor remains the
        # canonical type/bounds validator for these supplied downstream inputs;
        # this producer does not duplicate those contracts.

    def _validate_primary_claim_binding(self) -> None:
        state = self.operational_state
        claim = self.primary_claim

        if state.claim_state is ClaimState.SINGLE:
            if type(claim) is not PrimaryIssueClaim:
                raise ValueError("single-claim operational state requires its exact PrimaryIssueClaim")
            claim.__post_init__()
            if len(state.primary_pr_numbers) != 1 or len(state.primary_claim_ids) != 1:
                raise ValueError("single-claim operational state has inconsistent claim identity")
            if claim.pull_request_number != state.primary_pr_numbers[0]:
                raise ValueError("primary claim pull request conflicts with operational state")
            if claim.claim_id != state.primary_claim_ids[0]:
                raise ValueError("primary claim identity conflicts with operational state")
            if claim.branch != state.active_branch:
                raise ValueError("primary claim branch conflicts with operational state")
            if self.current_head_sha != claim.head_sha:
                raise ValueError("current head conflicts with the canonical primary claim")
            return

        if claim is not None:
            raise ValueError("primary_claim is only valid for a single-claim operational state")


def produce_compute_control_projection(
    evidence: ComputeControlProductionEvidence,
) -> ComputeControlProjection:
    """Produce one canonical #1419 projection from supplied current evidence."""

    if type(evidence) is not ComputeControlProductionEvidence:
        raise TypeError("evidence must be exact ComputeControlProductionEvidence")
    # Re-run producer invariants so tampered frozen objects fail closed.
    evidence.__post_init__()

    handoff = evidence.handoff
    if handoff is None:
        assert evidence.handoff_evidence is not None  # guaranteed by invariant
        handoff = build_coding_command_center_handoff(evidence.handoff_evidence)

    return build_compute_control_projection(
        ComputeControlEvidence(
            handoff=handoff,
            operational_state=evidence.operational_state,
            current_head_sha=evidence.current_head_sha,
            validation_plan=evidence.validation_plan,
            evidence_applicability=evidence.evidence_applicability,
            validation_head_reference=evidence.validation_head_reference,
            active_execution=evidence.active_execution,
            measured_compute_metadata_reference=evidence.measured_compute_metadata_reference,
        )
    )


def produce_serialized_compute_control_projection(
    evidence: ComputeControlProductionEvidence,
) -> dict[str, object]:
    """Produce and serialize the canonical #1419 contract without new semantics."""

    return serialize_compute_control_projection(produce_compute_control_projection(evidence))
