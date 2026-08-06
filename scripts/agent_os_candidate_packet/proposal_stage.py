"""AOS-AUTO1C repository-evidence and WSC3 proposal coordinator (#752).

Turns one verified #751 planning result plus one explicit repository
observation into either canonical ``RepositoryStateEvidence`` *and* a
content-verified WSC3 ``DraftTaskProposal``, or exactly one deterministic
fail-closed result.

The proposal gate
-----------------

``build_draft_task_proposals(...)`` is called only after every one of these
passes, in this order:

1. **Planning input.** The planning result must be a complete
   ``PlanningHandoffStageResult`` -- an ``invalid-input`` or partial result is
   never repaired. It must be WSC3-suppliable and its handoff must have passed
   local validation.
2. **Repository evidence.** The observation must form canonical evidence and
   the canonical validator must return ``valid`` against the base ref, head
   SHA, requested SHA, and implementation-contract fingerprint the planning
   result already committed to. Anything else -- ``stale``, ``blocked``,
   ``needs-decision``, ``invalid`` -- is returned as-is. Repository facts gate
   ahead of the planning outcome because an unverified repository cannot be
   reported as merely blocked upstream.
3. **Repository identity binding.** The observed owner/repository must be the
   repository the handoff names. The canonical validator cannot check this on
   its own, because only the handoff carries the ``owner/repository`` string.
4. **Planning eligibility.** ``blocked`` and ``needs-decision`` planning
   outcomes are preserved, never re-litigated and never upgraded.

WSC3 then owns the remaining verdict -- handoff/IssuePlan/repository binding
drift, IssuePlan currency, and proposal identity -- and its status is mapped
through unchanged. This module re-derives none of it.

The IssuePlan evidence handed to WSC3 is the exact canonical
``IssuePlanCurrentStateEvidence`` object preserved by the planning stage. It
is never rebuilt from an evidence ID, node provenance, a digest, handoff
bytes, or another partial representation.

This module performs no network, subprocess, Git, credential, filesystem
write, Scheduler execution, provider, production, persistence, or
external-system operation, and every result it produces carries
``execution_authorized=False`` and ``side_effects_performed=False``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Literal

from scripts.agent_os_execution_capabilities import RepositoryStateEvidence
from scripts.agent_os_issue_acceptance.scheduler_handoff import (
    HandoffCohort,
    SchedulerPlanningHandoff,
)
from workflow_scheduler.planning.draft_ingestion import (
    DraftTaskProposal,
    DraftTaskProposalResult,
    build_draft_task_proposals,
)

from .planning_stage import PlanningHandoffStageResult, PlanningHandoffStageStatus
from .repository_stage import (
    RepositoryObservation,
    RepositoryStageResult,
    RepositoryStageStatus,
    prepare_repository_state_evidence,
)

WSC3_STATUS_UNMAPPED = "wsc3-status-unmapped"
"""WSC3 returned a status this coordinator cannot classify."""

_REPOSITORY_IDENTITY_MISMATCH = "repo.identity-mismatch"

_COHORT_PAYLOAD_KEYS = frozenset({"node_ids", "classification", "reason_codes"})

# Derived from the canonical dataclass so a new WSC3 field cannot silently drop
# out of the serialized shape.
_DRAFT_TASK_PROPOSAL_PAYLOAD_KEYS = frozenset(
    item.name for item in fields(DraftTaskProposal)
)


class RepositoryProposalStageStatus(str, Enum):
    """Distinct coordinator outcomes.

    ``invalid`` is WSC3 or the canonical repository validator reporting that
    supplied evidence is unusable; ``invalid-input`` is this coordinator
    refusing its own arguments. They are kept apart so a rejected argument can
    never read as rejected evidence.
    """

    ELIGIBLE = "eligible"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"
    INVALID = "invalid"
    INVALID_INPUT = "invalid-input"


_REPOSITORY_STATUS_MAP = {
    RepositoryStageStatus.STALE: RepositoryProposalStageStatus.STALE,
    RepositoryStageStatus.BLOCKED: RepositoryProposalStageStatus.BLOCKED,
    RepositoryStageStatus.NEEDS_DECISION: (
        RepositoryProposalStageStatus.NEEDS_DECISION
    ),
    RepositoryStageStatus.INVALID: RepositoryProposalStageStatus.INVALID,
}

_PLANNING_STATUS_MAP = {
    PlanningHandoffStageStatus.BLOCKED: RepositoryProposalStageStatus.BLOCKED,
    PlanningHandoffStageStatus.NEEDS_DECISION: (
        RepositoryProposalStageStatus.NEEDS_DECISION
    ),
}

_WSC3_STATUS_MAP = {
    "eligible": RepositoryProposalStageStatus.ELIGIBLE,
    "blocked": RepositoryProposalStageStatus.BLOCKED,
    "stale": RepositoryProposalStageStatus.STALE,
    "invalid": RepositoryProposalStageStatus.INVALID,
    "needs-decision": RepositoryProposalStageStatus.NEEDS_DECISION,
}


@dataclass(frozen=True, slots=True)
class RepositoryProposalStageResult:
    """One coordinator outcome carrying every canonical object it produced.

    ``proposal`` is the single proposal inside ``proposal_result`` when the
    stage is eligible -- the same object, surfaced for convenience, never a
    copy. No caller has to reassemble a proposal or a repository-evidence
    identity by hand.
    """

    status: RepositoryProposalStageStatus
    repository_stage: RepositoryStageResult | None
    repository_state_evidence: RepositoryStateEvidence | None
    proposal_result: DraftTaskProposalResult | None
    proposal: DraftTaskProposal | None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, RepositoryProposalStageStatus):
            raise TypeError("status must be a RepositoryProposalStageStatus")
        if self.repository_stage is not None:
            if not isinstance(self.repository_stage, RepositoryStageResult):
                raise TypeError("repository_stage must be a RepositoryStageResult")
            if self.repository_state_evidence is not self.repository_stage.evidence:
                raise ValueError(
                    "repository_state_evidence must be the repository stage's own "
                    "evidence object"
                )
        elif self.repository_state_evidence is not None:
            raise ValueError(
                "repository evidence cannot exist without its repository stage result"
            )
        if self.proposal_result is not None and not isinstance(
            self.proposal_result, DraftTaskProposalResult
        ):
            raise TypeError("proposal_result must be a DraftTaskProposalResult")
        eligible = self.status is RepositoryProposalStageStatus.ELIGIBLE
        if eligible:
            if self.proposal_result is None or self.proposal_result.status != "eligible":
                raise ValueError("eligible results require an eligible WSC3 result")
            if self.proposal is not self.proposal_result.proposals[0]:
                raise ValueError(
                    "proposal must be the WSC3 result's own proposal object"
                )
        elif self.proposal is not None:
            raise ValueError("non-eligible results cannot carry a proposal")
        object.__setattr__(
            self, "reason_codes", tuple(sorted(set(self.reason_codes)))
        )


def prepare_repository_and_proposal(
    planning_stage_result: PlanningHandoffStageResult,
    repository_observation: RepositoryObservation,
    *,
    created_at: str,
) -> RepositoryProposalStageResult:
    """Construct canonical repository evidence and, when eligible, a proposal.

    ``created_at`` is explicit provenance supplied by the caller. This stage
    reads no clock, and WSC3 excludes it from proposal identity, so repeated
    identical semantic inputs keep producing the same proposal identity.
    """
    if not isinstance(planning_stage_result, PlanningHandoffStageResult):
        raise TypeError(
            "planning_stage_result must be a PlanningHandoffStageResult"
        )
    if not isinstance(repository_observation, RepositoryObservation):
        raise TypeError("repository_observation must be a RepositoryObservation")

    planning_reasons = planning_stage_result.reason_codes
    if planning_stage_result.status is PlanningHandoffStageStatus.INVALID_INPUT:
        return _invalid_input(("planning-stage-invalid-input", *planning_reasons))

    issueplan = planning_stage_result.issueplan_current_state_evidence
    handoff = planning_stage_result.handoff
    handoff_validation = planning_stage_result.handoff_validation
    if issueplan is None or handoff is None or handoff_validation is None:
        return _invalid_input(("planning-stage-partial", *planning_reasons))
    if not planning_stage_result.wsc3_suppliable:
        return _invalid_input(("planning-stage-not-suppliable", *planning_reasons))
    if not handoff_validation.local_checks_passed:
        return _invalid_input(
            (
                "planning-handoff-invalid",
                *handoff_validation.reason_codes,
                *planning_reasons,
            )
        )

    repository_stage = prepare_repository_state_evidence(
        repository_observation,
        expected_base_ref=handoff.base_branch,
        expected_head_sha=handoff.evaluated_repository_sha,
        expected_requested_sha=handoff.evaluated_repository_sha,
        expected_contract_fingerprint=issueplan.implementation_contract_fingerprint,
    )
    evidence = repository_stage.evidence
    if repository_stage.status is not RepositoryStageStatus.VALID:
        return _result(
            _REPOSITORY_STATUS_MAP[repository_stage.status],
            repository_stage,
            (*repository_stage.reason_codes, *planning_reasons),
        )

    assert evidence is not None  # guaranteed by RepositoryStageResult
    if not _repository_matches_handoff(evidence, handoff):
        return _result(
            RepositoryProposalStageStatus.STALE,
            repository_stage,
            (_REPOSITORY_IDENTITY_MISMATCH, *planning_reasons),
        )

    if planning_stage_result.status is not PlanningHandoffStageStatus.READY:
        return _result(
            _PLANNING_STATUS_MAP[planning_stage_result.status],
            repository_stage,
            planning_reasons,
        )

    proposal_result = build_draft_task_proposals(
        handoff,
        # The exact preserved canonical object -- never reconstructed here.
        issueplan,
        evidence,
        created_at=created_at,
    )
    status = _WSC3_STATUS_MAP.get(proposal_result.status)
    if status is None:
        # WSC3 constrains its own status vocabulary, but it is another package:
        # a status added there must still land as one deterministic fail-closed
        # result here, never an escaping exception.
        return _result(
            RepositoryProposalStageStatus.INVALID,
            repository_stage,
            (WSC3_STATUS_UNMAPPED, *planning_reasons),
        )
    return RepositoryProposalStageResult(
        status=status,
        repository_stage=repository_stage,
        repository_state_evidence=evidence,
        proposal_result=proposal_result,
        proposal=(
            proposal_result.proposals[0]
            if status is RepositoryProposalStageStatus.ELIGIBLE
            else None
        ),
        reason_codes=(*proposal_result.reason_codes, *planning_reasons),
    )


def draft_task_proposal_to_dict(proposal: DraftTaskProposal) -> dict[str, Any]:
    if not isinstance(proposal, DraftTaskProposal):
        raise TypeError("proposal must be a DraftTaskProposal")
    return {
        "proposal_version": proposal.proposal_version,
        "proposal_id": proposal.proposal_id,
        "handoff_digest": proposal.handoff_digest,
        "graph_digest": proposal.graph_digest,
        "planning_result_digest": proposal.planning_result_digest,
        "repository": proposal.repository,
        "base_branch": proposal.base_branch,
        "evaluated_repository_sha": proposal.evaluated_repository_sha,
        "evaluator_commit_sha": proposal.evaluator_commit_sha,
        "supplied_node_ids": list(proposal.supplied_node_ids),
        "cohort_summaries": [
            {
                "node_ids": list(cohort.node_ids),
                "classification": cohort.classification,
                "reason_codes": list(cohort.reason_codes),
            }
            for cohort in proposal.cohort_summaries
        ],
        "issueplan_current_state_evidence_id": (
            proposal.issueplan_current_state_evidence_id
        ),
        "repository_state_evidence_id": proposal.repository_state_evidence_id,
        "created_at": proposal.created_at,
        "eligibility_status": proposal.eligibility_status,
        "authorization_status": proposal.authorization_status,
        "execution_authorized": False,
    }


def draft_task_proposal_from_dict(payload: Mapping[str, Any]) -> DraftTaskProposal:
    """Reconstruct one proposal, failing closed on identity or authority drift.

    ``proposal_id`` is carried through and re-verified by ``DraftTaskProposal``
    itself, so a tampered payload is rejected rather than re-signed.
    """
    label = "draft task proposal"
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be a mapping")
    supplied = set(payload)
    missing = sorted(_DRAFT_TASK_PROPOSAL_PAYLOAD_KEYS - supplied)
    if missing:
        raise ValueError(f"{label} is missing field(s): " + ", ".join(missing))
    unsupported = sorted(supplied - _DRAFT_TASK_PROPOSAL_PAYLOAD_KEYS)
    if unsupported:
        raise ValueError(f"{label} has unsupported field(s): " + ", ".join(unsupported))
    if payload["execution_authorized"] is not False:
        raise ValueError("execution_authorized must be false")
    if payload["eligibility_status"] != "eligible":
        raise ValueError("a serialized proposal is always eligible")
    if payload["authorization_status"] != "not-evaluated":
        raise ValueError("authorization_status must remain not-evaluated")
    cohorts = payload["cohort_summaries"]
    if not isinstance(cohorts, list):
        raise ValueError("cohort_summaries must be a list")
    for item in cohorts:
        if not isinstance(item, Mapping):
            raise ValueError("each cohort summary must be a mapping")
        missing_keys = sorted(_COHORT_PAYLOAD_KEYS - set(item))
        if missing_keys:
            raise ValueError(
                "cohort summary is missing field(s): " + ", ".join(missing_keys)
            )
    return DraftTaskProposal(
        proposal_version=payload["proposal_version"],
        proposal_id=payload["proposal_id"],
        handoff_digest=payload["handoff_digest"],
        graph_digest=payload["graph_digest"],
        planning_result_digest=payload["planning_result_digest"],
        repository=payload["repository"],
        base_branch=payload["base_branch"],
        evaluated_repository_sha=payload["evaluated_repository_sha"],
        evaluator_commit_sha=payload["evaluator_commit_sha"],
        supplied_node_ids=tuple(payload["supplied_node_ids"]),
        cohort_summaries=tuple(
            HandoffCohort(
                node_ids=tuple(item["node_ids"]),
                classification=item["classification"],
                reason_codes=tuple(item["reason_codes"]),
            )
            for item in cohorts
        ),
        issueplan_current_state_evidence_id=payload[
            "issueplan_current_state_evidence_id"
        ],
        repository_state_evidence_id=payload["repository_state_evidence_id"],
        created_at=payload["created_at"],
    )


def _repository_matches_handoff(
    evidence: RepositoryStateEvidence, handoff: SchedulerPlanningHandoff
) -> bool:
    """Check the one binding only the handoff can state: ``owner/repository``.

    Both sides are normalized here rather than relying on ``RepositoryIdentity``
    already lowercasing its own fields, so this binding cannot start rejecting
    every observation if that upstream normalization ever changes.
    """
    identity = evidence.repository_identity
    observed = f"{identity.owner}/{identity.repository}".strip().lower()
    return observed == handoff.repository.strip().lower()


def _result(
    status: RepositoryProposalStageStatus,
    repository_stage: RepositoryStageResult,
    reason_codes: tuple[str, ...],
) -> RepositoryProposalStageResult:
    return RepositoryProposalStageResult(
        status=status,
        repository_stage=repository_stage,
        repository_state_evidence=repository_stage.evidence,
        proposal_result=None,
        proposal=None,
        reason_codes=reason_codes,
    )


def _invalid_input(reason_codes: tuple[str, ...]) -> RepositoryProposalStageResult:
    return RepositoryProposalStageResult(
        status=RepositoryProposalStageStatus.INVALID_INPUT,
        repository_stage=None,
        repository_state_evidence=None,
        proposal_result=None,
        proposal=None,
        reason_codes=reason_codes,
    )
