"""Provenance and stage-payload-digest construction for the #755 compiler.

This module never re-derives a stage identity: every digest below is the
canonical serialized payload the owning stage module already produces (and
already self-verifies) through its own ``..._to_dict`` transport. It only
orders those payloads into the packet's provenance manifest and per-stage
digest list.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .approval_stage import ApprovalProjectionStageResult, approval_projection_stage_result_to_dict
from .models import CandidatePacketCompilerInput, CandidatePacketPhase
from .planning_stage import planning_handoff_stage_result_to_dict
from .proposal_stage import repository_proposal_stage_result_to_dict
from .stage_models import canonical_bytes, issue_readiness_stage_result_to_dict

_DIGEST_DOMAIN_PREFIX = "candidate-packet-stage"


def _stage_digest(stage_name: str, payload: Any) -> str:
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return f"{_DIGEST_DOMAIN_PREFIX}:{stage_name}:{digest}"


def build_stage_payload_digests(
    compiler_input: CandidatePacketCompilerInput,
) -> tuple[tuple[str, str], ...]:
    """Ordered ``(stage_name, digest)`` pairs, one per included canonical stage.

    Calling each stage's own ``..._to_dict`` transport both produces the
    payload to hash *and* re-verifies that stage's internal identity (every
    transport in this package already rejects noncanonical fields before
    returning), so this function is the compiler's "recompute every supplied
    identity through its canonical verifier" step for provenance purposes.
    """
    digests: list[tuple[str, str]] = [
        (
            "readiness",
            _stage_digest(
                "readiness", issue_readiness_stage_result_to_dict(compiler_input.readiness_stage_result)
            ),
        ),
        (
            "planning",
            _stage_digest(
                "planning", planning_handoff_stage_result_to_dict(compiler_input.planning_stage_result)
            ),
        ),
        (
            "proposal",
            _stage_digest(
                "proposal",
                repository_proposal_stage_result_to_dict(compiler_input.proposal_stage_result),
            ),
        ),
    ]
    if compiler_input.approval_stage_result is not None:
        digests.append(
            (
                "approval",
                _stage_digest(
                    "approval",
                    approval_projection_stage_result_to_dict(compiler_input.approval_stage_result),
                ),
            )
        )
    if (
        compiler_input.requested_phase is CandidatePacketPhase.EXECUTION_CANDIDATE
        and compiler_input.execution_packet_stage_result is not None
    ):
        from .execution_packet_stage import execution_packet_stage_result_to_dict

        digests.append(
            (
                "execution-packet",
                _stage_digest(
                    "execution-packet",
                    execution_packet_stage_result_to_dict(
                        compiler_input.execution_packet_stage_result
                    ),
                ),
            )
        )
    return tuple(digests)


def build_stage_identities(
    compiler_input: CandidatePacketCompilerInput,
) -> tuple[tuple[str, str], ...]:
    """Ordered ``(stage_name, primary_identity)`` pairs for the packet header."""
    readiness = compiler_input.readiness_stage_result
    planning = compiler_input.planning_stage_result
    proposal = compiler_input.proposal_stage_result

    identities: list[tuple[str, str]] = [
        ("source", readiness.snapshot.source_revision),
        ("issueplan", readiness.issueplan_current_state_evidence.evidence_id),
        ("planning-handoff", planning.handoff.handoff_digest),
        ("repository-evidence", proposal.repository_state_evidence.evidence_id),
        ("proposal", proposal.proposal.proposal_id),
    ]

    approval = compiler_input.approval_stage_result
    if approval is not None and approval.pending_candidate is not None:
        identities.append(
            (
                "approval-candidate",
                f"{approval.pending_candidate.approval_id}"
                f"@{approval.pending_candidate.approval_revision}",
            )
        )
        if (
            compiler_input.requested_phase is CandidatePacketPhase.EXECUTION_CANDIDATE
            and approval.decision_revision is not None
        ):
            identities.append(
                (
                    "approval-decision",
                    f"{approval.decision_revision.approval_id}"
                    f"@{approval.decision_revision.approval_revision}",
                )
            )
        if (
            compiler_input.requested_phase is CandidatePacketPhase.EXECUTION_CANDIDATE
            and approval.projection is not None
        ):
            identities.append(("projection", approval.projection.projection_id))

    execution_packet = compiler_input.execution_packet_stage_result
    if (
        compiler_input.requested_phase is CandidatePacketPhase.EXECUTION_CANDIDATE
        and execution_packet is not None
        and execution_packet.packet_complete
    ):
        identities.append(("validation-subject", execution_packet.validation_stage.subject_id or ""))
        identities.append(
            ("validation-plan", execution_packet.validation_stage.validation_plan_id or "")
        )
        identities.append(("execution-request", execution_packet.request_fingerprint or ""))
        identities.append(("command-plan", execution_packet.command_plan_id or ""))
        identities.append(
            ("runtime-configuration", execution_packet.runtime_configuration_fingerprint or "")
        )

    return tuple(identities)


def build_provenance_manifest(compiler_input: CandidatePacketCompilerInput) -> tuple[str, ...]:
    """Ordered ``"stage:identity"`` provenance trail for the compiled packet."""
    return tuple(f"{stage}:{identity}" for stage, identity in build_stage_identities(compiler_input))
