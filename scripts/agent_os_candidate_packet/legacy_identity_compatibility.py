"""Explicit legacy approved-packet compatibility path (#3413, decision point 2).

Before #3413, ``prepare_planning_handoff`` hashed *every* readiness reason
code into the planning node identity, including the phase-specific diagnostic
codes named in ``planning_stage.PHASE_SPECIFIC_DIAGNOSTIC_REASON_CODES``.
Packets approved under that composition carry ``planning-handoff`` /
``proposal`` / ``approval-candidate`` identities a current-composition rebuild
can never reproduce, even for the identical candidate.

This module proves compatibility for such packets without silently rewriting
or re-authorizing them: it recomputes the legacy digest chain through the
real public stage constructors (planning node -> graph -> handoff ->
proposal -> approval candidate) with exactly the excluded diagnostic codes
reinstated, and requires the recomputed triple to equal the approved packet's
stored identities. Either composition may verify; anything else fails closed.

The legacy diagnostic sets are closed and explicit: a first-packet approval
always emitted ``validation.first-packet-not-required`` plus exactly one
pre-approval producer code (``dependency-graph.no-dependencies-declared`` or
``dependency-graph.all-dependencies-closed`` -- a blocked/unavailable producer
outcome could never reach approval). Both candidates are tried; acceptance
requires an exact recomputation match, so this is exhaustive verification
over a named set, never a guess.

Fail-closed cases (each yields ``PostApprovalIdentityOutcome.LEGACY_UNPROVABLE``):
- no ``candidate_context`` (the approval candidate cannot be recomputed);
- the legacy recomputation does not reproduce all three stored identities;
- any stage constructor rejects its input.

This module owns no evidence, approval, scheduler, or persistence model; it
reuses the existing stage owners and introduces no parallel pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum

from scripts.agent_os_issue_acceptance.batch_graph import build_issue_batch_graph
from scripts.agent_os_issue_acceptance.batch_planning import evaluate_batch_plan
from scripts.agent_os_issue_acceptance.planning_binding import (
    build_planning_binding_evidence,
)
from scripts.agent_os_issue_acceptance.scheduler_handoff import (
    HandoffCohort,
    compute_graph_digest,
    compute_handoff_digest,
    compute_planning_result_digest,
    serialize_scheduler_planning_handoff,
    validate_scheduler_planning_handoff,
)

from .approval_stage import (
    ApprovalCandidateContext,
    prepare_approval_projection,
)
from .models import CandidatePacket
from .planning_stage import (
    PHASE_SPECIFIC_DIAGNOSTIC_REASON_CODES,
    PlanningHandoffStageResult,
)
from .proposal_stage import (
    RepositoryProposalStageResult,
    RepositoryProposalStageStatus,
    prepare_repository_and_proposal,
)
from .repository_stage import RepositoryObservation

_LEGACY_FIRST_PACKET_DIAGNOSTIC_SETS: tuple[tuple[str, ...], ...] = (
    (
        "validation.first-packet-not-required",
        "dependency-graph.no-dependencies-declared",
    ),
    (
        "validation.first-packet-not-required",
        "dependency-graph.all-dependencies-closed",
    ),
)
"""Closed candidate legacy diagnostic code sets for a first-packet approval."""

_LEGACY_REASON = "candidate-legacy-identity-composition-verified"
_UNPROVABLE_REASON = "candidate-legacy-compatibility-unprovable"
_DRIFT_REASON = "candidate-provenance-drift"

_STRICT_IDENTITY_NAMES = ("source", "issueplan", "repository-evidence")
"""Identities unaffected by the #3413 composition change; always strict."""

_LEGACY_IDENTITY_NAMES = ("planning-handoff", "proposal", "approval-candidate")
"""Identities affected by the #3413 composition change; legacy-eligible."""


class PostApprovalIdentityOutcome(str, Enum):
    """Terminal outcome of post-approval stage-identity verification."""

    VERIFIED = "verified"
    """Strict match under the current identity composition."""

    VERIFIED_LEGACY_COMPOSITION = "verified-legacy-composition"
    """Explicit legacy path: the stored identities provably predate #3413."""

    DRIFT = "drift"
    """Fail closed: a composition-independent identity differs."""

    LEGACY_UNPROVABLE = "legacy-unprovable"
    """Fail closed: the legacy composition could not be proven."""


@dataclass(frozen=True, slots=True)
class PostApprovalIdentityVerdict:
    """One explicit verification outcome for a post-approval identity check."""

    outcome: PostApprovalIdentityOutcome
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    legacy_diagnostic_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, PostApprovalIdentityOutcome):
            raise TypeError("outcome must be a PostApprovalIdentityOutcome")
        object.__setattr__(
            self, "reason_codes", tuple(sorted(set(self.reason_codes)))
        )
        object.__setattr__(
            self,
            "legacy_diagnostic_codes",
            tuple(sorted(set(self.legacy_diagnostic_codes))),
        )
        if self.outcome is PostApprovalIdentityOutcome.VERIFIED_LEGACY_COMPOSITION:
            if not self.legacy_diagnostic_codes:
                raise ValueError(
                    "a legacy verification must name the proven diagnostic codes"
                )
            if not set(self.legacy_diagnostic_codes) <= set(
                PHASE_SPECIFIC_DIAGNOSTIC_REASON_CODES
            ):
                raise ValueError(
                    "legacy diagnostic codes must come from the governed excluded set"
                )


def verify_post_approval_stage_identities(
    *,
    expected_identities: Mapping[str, str],
    current_identities: Mapping[str, str],
    planning_stage_result: PlanningHandoffStageResult,
    approved_packet: CandidatePacket,
    repository_observation: RepositoryObservation,
    candidate_context: ApprovalCandidateContext | None,
    observed_at: str,
) -> PostApprovalIdentityVerdict:
    """Verify rebuilt stage identities against an approved packet.

    Composition-independent identities (``source``, ``issueplan``,
    ``repository-evidence``) always compare strictly: any difference is
    ``DRIFT`` and fails closed. Composition-affected identities
    (``planning-handoff``, ``proposal``, ``approval-candidate``) compare
    strictly first; on mismatch the explicit legacy compatibility path is
    attempted exactly once. A proven legacy composition yields
    ``VERIFIED_LEGACY_COMPOSITION`` naming the proven diagnostic codes; an
    unprovable one yields ``LEGACY_UNPROVABLE``. Nothing here rewrites or
    re-authorizes the approved packet.
    """
    for name in _STRICT_IDENTITY_NAMES:
        if expected_identities.get(name) != current_identities.get(name):
            return PostApprovalIdentityVerdict(
                outcome=PostApprovalIdentityOutcome.DRIFT,
                reason_codes=(_DRIFT_REASON,),
            )
    if all(
        expected_identities.get(name) == current_identities.get(name)
        for name in _LEGACY_IDENTITY_NAMES
    ):
        return PostApprovalIdentityVerdict(
            outcome=PostApprovalIdentityOutcome.VERIFIED,
            reason_codes=("candidate-identities-verified",),
        )
    matched = _matched_legacy_codes(
        planning_stage_result=planning_stage_result,
        approved_packet=approved_packet,
        repository_observation=repository_observation,
        candidate_context=candidate_context,
        observed_at=observed_at,
    )
    if matched is not None:
        return PostApprovalIdentityVerdict(
            outcome=PostApprovalIdentityOutcome.VERIFIED_LEGACY_COMPOSITION,
            reason_codes=(_LEGACY_REASON,),
            legacy_diagnostic_codes=matched,
        )
    return PostApprovalIdentityVerdict(
        outcome=PostApprovalIdentityOutcome.LEGACY_UNPROVABLE,
        reason_codes=(_UNPROVABLE_REASON,),
    )


def legacy_handoff_digest_for_codes(
    planning_stage_result: PlanningHandoffStageResult,
    legacy_codes: tuple[str, ...],
) -> tuple[str, str, PlanningHandoffStageResult] | None:
    """Recompute the pre-#3413 handoff digest with diagnostic codes reinstated.

    Returns ``(legacy_handoff_digest, legacy_graph_digest, legacy_planning)``
    where ``legacy_planning`` is the rebuilt planning stage result, or
    ``None`` when the input cannot support the recomputation. Uses only the
    real public stage constructors; never invents evidence.
    """
    if not isinstance(planning_stage_result, PlanningHandoffStageResult):
        return None
    if not set(legacy_codes) <= set(PHASE_SPECIFIC_DIAGNOSTIC_REASON_CODES):
        raise ValueError("legacy codes must come from the governed excluded set")
    node = planning_stage_result.node
    handoff = planning_stage_result.handoff
    issueplan = planning_stage_result.issueplan_current_state_evidence
    if node is None or handoff is None or issueplan is None:
        return None

    legacy_node = replace(
        node,
        readiness_evidence=tuple(sorted(set(node.readiness_evidence) | set(legacy_codes))),
    )
    legacy_graph = build_issue_batch_graph((legacy_node,))
    legacy_graph_digest = compute_graph_digest(legacy_graph)
    legacy_planning_result = evaluate_batch_plan(legacy_graph)
    legacy_handoff = replace(
        handoff,
        graph_digest=legacy_graph_digest,
        planning_result_digest=compute_planning_result_digest(legacy_planning_result),
        cohort_summaries=tuple(
            HandoffCohort(
                node_ids=cohort.node_ids,
                classification=cohort.classification.value,
                reason_codes=cohort.reason_codes,
            )
            for cohort in legacy_planning_result.cohorts
        ),
        handoff_digest="",
    )
    legacy_handoff_digest = compute_handoff_digest(legacy_handoff)
    legacy_handoff = replace(legacy_handoff, handoff_digest=legacy_handoff_digest)

    try:
        legacy_planning = replace(
            planning_stage_result,
            node=legacy_node,
            graph=legacy_graph,
            planning_result=legacy_planning_result,
            handoff=legacy_handoff,
            serialized_handoff=serialize_scheduler_planning_handoff(legacy_handoff),
            handoff_validation=validate_scheduler_planning_handoff(legacy_handoff),
            planning_binding=(
                build_planning_binding_evidence(
                    issueplan, legacy_handoff, created_at=handoff.created_at
                )
                if issueplan.implementation_contract_fingerprint is not None
                else None
            ),
        )
    except (TypeError, ValueError):
        return None
    if not legacy_planning.handoff_validation.local_checks_passed:
        return None
    return legacy_handoff_digest, legacy_graph_digest, legacy_planning


def _matched_legacy_codes(
    *,
    planning_stage_result: PlanningHandoffStageResult,
    approved_packet: CandidatePacket,
    repository_observation: RepositoryObservation,
    candidate_context: ApprovalCandidateContext | None,
    observed_at: str,
) -> tuple[str, ...] | None:
    """Return the proven legacy diagnostic code set, or None if unprovable.

    For each closed candidate code set, reinstate the codes on the rebuilt
    planning node and recompute the digest chain through the real public
    stage constructors. The first set whose recomputed
    (planning-handoff, proposal, approval-candidate) triple exactly equals
    the approved packet's stored identities is the proven composition.
    """
    if candidate_context is None:
        return None
    if not isinstance(planning_stage_result, PlanningHandoffStageResult):
        return None
    if type(approved_packet) is not CandidatePacket:
        return None
    if not isinstance(repository_observation, RepositoryObservation):
        return None
    node = planning_stage_result.node
    handoff = planning_stage_result.handoff
    issueplan = planning_stage_result.issueplan_current_state_evidence
    if node is None or handoff is None or issueplan is None:
        return None
    stored = dict(approved_packet.stage_identities)
    for legacy_codes in _LEGACY_FIRST_PACKET_DIAGNOSTIC_SETS:
        triple = _legacy_identity_triple(
            planning_stage_result=planning_stage_result,
            legacy_codes=legacy_codes,
            repository_observation=repository_observation,
            candidate_context=candidate_context,
            observed_at=observed_at,
        )
        if triple is None:
            continue
        if all(stored.get(name) == value for name, value in triple.items()):
            return legacy_codes
    return None


def _legacy_identity_triple(
    *,
    planning_stage_result: PlanningHandoffStageResult,
    legacy_codes: tuple[str, ...],
    repository_observation: RepositoryObservation,
    candidate_context: ApprovalCandidateContext,
    observed_at: str,
) -> dict[str, str] | None:
    """Recompute the pre-#3413 identity triple through the real stages.

    Returns ``{"planning-handoff": ..., "proposal": ...,
    "approval-candidate": ...}`` or ``None`` when any stage constructor
    rejects the legacy-composed input (fail-closed, never a partial triple).
    """
    recomputed = legacy_handoff_digest_for_codes(planning_stage_result, legacy_codes)
    if recomputed is None:
        return None
    legacy_handoff_digest, _, legacy_planning = recomputed

    try:
        legacy_proposal_result = prepare_repository_and_proposal(
            legacy_planning, repository_observation, created_at=observed_at
        )
    except (TypeError, ValueError):
        return None
    if (
        legacy_proposal_result.status is not RepositoryProposalStageStatus.ELIGIBLE
        or legacy_proposal_result.proposal is None
    ):
        return None

    try:
        legacy_approval = prepare_approval_projection(
            legacy_proposal_result,
            candidate_context=candidate_context,
            approval_decision=None,
            evaluated_at=observed_at,
            projected_at=observed_at,
        )
    except (TypeError, ValueError):
        return None
    pending = legacy_approval.pending_candidate
    if pending is None:
        return None
    return {
        "planning-handoff": legacy_handoff_digest,
        "proposal": legacy_proposal_result.proposal.proposal_id,
        "approval-candidate": f"{pending.approval_id}@{pending.approval_revision}",
    }


__all__ = [
    "PostApprovalIdentityOutcome",
    "PostApprovalIdentityVerdict",
    "legacy_handoff_digest_for_codes",
    "verify_post_approval_stage_identities",
]
