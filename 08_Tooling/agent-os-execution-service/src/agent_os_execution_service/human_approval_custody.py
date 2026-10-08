"""Production human-approval custody composition for #1982.

Option C persists candidate-preparer provenance before human approval. Option A
reacquires one exact repository-owner GitHub comment as the later human decision.
The composition reuses #753 candidate/approval semantics, #755 compilation, and
#1978 custody persistence. It creates no execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from scripts.agent_os_candidate_packet.approval_stage import ApprovalDecision
from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet
from scripts.agent_os_candidate_packet.legacy_identity_compatibility import (
    PostApprovalIdentityOutcome,
    verify_post_approval_stage_identities,
)
from scripts.agent_os_candidate_packet.models import CandidatePacketPhase
from scripts.agent_os_issue_acceptance.approval_records import ApprovalState

from .candidate_approval_provenance import (
    CandidateApprovalProvenanceEvidence,
    load_candidate_approval_provenance,
)
from .execution_authorization_source import ExecutionAuthorizationSourceTransport
from .post_approval_dependency_identities import (
    post_approval_dependency_identity_evidence,
)
from .pre_publication_evidence_capsule import build_approval_custody_evidence
from .pre_publication_evidence_store import append_pre_publication_evidence
from .production_host_bootstrap import (
    ProductionHostConfiguration,
    load_production_host_configuration,
)

_APPROVAL_PREFIX = "/agent-os approve-candidate "


class HumanApprovalCustodyError(RuntimeError):
    """Current approval/candidate evidence cannot safely produce custody."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HumanApprovalDecisionEvidence:
    candidate_provenance_id: str
    source_comment_id: int
    authorizer_id: str
    decision_at: str
    approval_decision: ApprovalDecision
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def reacquire_human_approval_decision(
    *,
    transport: ExecutionAuthorizationSourceTransport,
    repository: str,
    issue_number: int,
    candidate_provenance_id: str,
) -> HumanApprovalDecisionEvidence:
    """Read one exact owner-authored fixed approval command from complete comments."""
    try:
        snapshot = transport.read_authorization_source(repository, issue_number)
    except (TypeError, ValueError, RuntimeError, OSError) as exc:
        raise HumanApprovalCustodyError("approval-source-unavailable") from exc
    if (
        snapshot.repository.casefold() != repository.casefold()
        or snapshot.issue_number != issue_number
        or snapshot.owner_type != "User"
        or not snapshot.comments_complete
    ):
        raise HumanApprovalCustodyError("approval-source-not-complete")
    expected_body = _APPROVAL_PREFIX + candidate_provenance_id
    matches = [
        item
        for item in snapshot.comments
        if item.author_login.casefold() == snapshot.owner_login.casefold()
        and item.body == expected_body
    ]
    if not matches:
        raise HumanApprovalCustodyError("human-approval-missing")
    comment_ids = [item.comment_id for item in matches]
    if len(comment_ids) != len(set(comment_ids)):
        raise HumanApprovalCustodyError("human-approval-source-ambiguous")
    current = sorted(matches, key=lambda item: (item.created_at, item.comment_id))[-1]
    decision = ApprovalDecision(
        state=ApprovalState.APPROVED,
        decision_id=f"github-comment:{current.comment_id}",
        authorizer_id=snapshot.owner_login,
        decision_at=current.created_at,
        # No reason codes: ApprovalDecision reason codes must use the ratified
        # #347 vocabulary, and the fixed-command provenance is already carried
        # by decision_id/authorizer_id. (#3413 integration: a non-vocabulary
        # code here made record_approval_decision always reject, so custody
        # could never complete.)
        reason_codes=(),
    )
    return HumanApprovalDecisionEvidence(
        candidate_provenance_id=candidate_provenance_id,
        source_comment_id=current.comment_id,
        authorizer_id=snapshot.owner_login,
        decision_at=current.created_at,
        approval_decision=decision,
    )


def produce_human_approval_custody(
    *,
    candidate_provenance_id: str,
    transport: ExecutionAuthorizationSourceTransport,
    issue_reader,
    repository_reader,
    repository_observation,
    candidate_runtime_inputs,
    observed_at: str,
    configuration: ProductionHostConfiguration | None = None,
) -> str:
    """Reacquire the approved candidate, compile EXECUTION_CANDIDATE, and persist #1978 custody."""
    config = configuration or load_production_host_configuration()
    if type(config) is not ProductionHostConfiguration:
        raise HumanApprovalCustodyError("host-configuration-malformed")
    provenance = load_candidate_approval_provenance(
        config.checkpoint_store_root, candidate_provenance_id
    )
    if type(provenance) is not CandidateApprovalProvenanceEvidence:
        raise HumanApprovalCustodyError("candidate-provenance-malformed")
    packet = provenance.approval_ready_packet
    decision = reacquire_human_approval_decision(
        transport=transport,
        repository=packet.repository,
        issue_number=packet.issue_number,
        candidate_provenance_id=provenance.evidence_id,
    )
    if decision.authorizer_id.casefold() == provenance.candidate_context.authorizer_id.casefold():
        raise HumanApprovalCustodyError("self-approval-forbidden")

    prepared = prepare_candidate_packet(
        repository=packet.repository,
        issue_number=packet.issue_number,
        issue_reader=issue_reader,
        repository_reader=repository_reader,
        observed_at=observed_at,
        base_branch=packet.base_branch,
        evaluated_repository_sha=packet.base_sha,
        invocation_id=packet.invocation_id,
        evaluator_sha=packet.evaluator_sha,
        # #3413 point 3: post-approval consumers reuse canonical dependency
        # identities from the structured IssuePlan depends_on governed field --
        # never prose, labels, CI, or guessed state. None keeps the existing
        # fail-closed dependency-identity.not-supplied path.
        dependency_identity_evidence=post_approval_dependency_identity_evidence(
            issue_reader=issue_reader,
            repository=packet.repository,
            issue_number=packet.issue_number,
            observed_at=observed_at,
        ),
        repository_observation=repository_observation,
        candidate_context=provenance.candidate_context,
        approval_decision=decision.approval_decision,
        requested_phase=CandidatePacketPhase.EXECUTION_CANDIDATE,
        candidate_runtime_inputs=candidate_runtime_inputs,
        external_build_sha=packet.external_build_sha,
        compiler_evaluated_at=observed_at,
    )
    execution_packet = prepared.packet
    approval_stage = prepared.approval_stage_result
    if (
        execution_packet is None
        or execution_packet.phase is not CandidatePacketPhase.EXECUTION_CANDIDATE
        or execution_packet.evidence_completeness != "complete"
        or execution_packet.disposition != "verified"
        or approval_stage is None
        or approval_stage.decision_revision is None
    ):
        raise HumanApprovalCustodyError("execution-candidate-not-verified")

    # #3413 point 2: composition-independent identities compare strictly;
    # composition-affected identities fall back to the explicit legacy
    # compatibility path, which proves (or fails to prove) a pre-#3413
    # composition by recomputation. Old approvals are never silently
    # rewritten or re-authorized.
    verdict = verify_post_approval_stage_identities(
        expected_identities=dict(packet.stage_identities),
        current_identities=dict(execution_packet.stage_identities),
        planning_stage_result=prepared.planning_stage_result,
        approved_packet=packet,
        repository_observation=repository_observation,
        candidate_context=provenance.candidate_context,
        observed_at=observed_at,
    )
    if verdict.outcome is PostApprovalIdentityOutcome.DRIFT:
        raise HumanApprovalCustodyError("candidate-provenance-drift")
    if verdict.outcome is PostApprovalIdentityOutcome.LEGACY_UNPROVABLE:
        raise HumanApprovalCustodyError("candidate-legacy-compatibility-unprovable")

    capsule = build_approval_custody_evidence(
        candidate_packet=execution_packet,
        approval_record=approval_stage.decision_revision,
    )
    outcome = append_pre_publication_evidence(config.checkpoint_store_root, capsule)
    if outcome.capsule_id != capsule.capsule_id:
        raise HumanApprovalCustodyError("approval-custody-persistence-mismatch")
    return outcome.capsule_id


__all__ = [
    "HumanApprovalCustodyError",
    "HumanApprovalDecisionEvidence",
    "produce_human_approval_custody",
    "reacquire_human_approval_decision",
]
