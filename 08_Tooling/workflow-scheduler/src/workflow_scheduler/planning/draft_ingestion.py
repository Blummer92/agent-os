"""Pure-local WSC3 draft proposal ingestion.

This module validates supplied WSC1, IssuePlanCore, and GEX evidence and emits
immutable proposal evidence only. It never creates Scheduler tasks, reads the
system clock, probes a repository, accesses credentials, or performs external
I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from scripts.agent_os_execution_capabilities import (
    RepositoryIdentity,
    RepositoryStateEvidence,
    RepositoryStateValidationResult,
    validate_repository_state_evidence,
)
from scripts.agent_os_issue_acceptance import (
    HandoffCohort,
    HandoffValidationOutcome,
    HandoffValidationResult,
    IssuePlanCurrentStateComparison,
    IssuePlanCurrentStateEvidence,
    IssuePlanCurrentStateOutcome,
    SchedulerPlanningHandoff,
    compare_issueplan_current_state,
    validate_scheduler_planning_handoff,
)

DRAFT_TASK_PROPOSAL_VERSION = "0.1.0"

_WSC3_STATUSES = frozenset(
    {"eligible", "blocked", "stale", "invalid", "needs-decision"}
)
_WSC3_REASON_CODES = frozenset(
    {"hard-dependency-unmet", "planning-state-mismatch", "approval-not-evaluated"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True, slots=True)
class DraftTaskProposal:
    """Immutable, content-verified, unapproved WSC3 proposal evidence."""

    proposal_version: str
    proposal_id: str
    handoff_digest: str
    graph_digest: str
    planning_result_digest: str
    repository: str
    base_branch: str
    evaluated_repository_sha: str
    evaluator_commit_sha: str
    supplied_node_ids: tuple[str, ...]
    cohort_summaries: tuple[HandoffCohort, ...]
    issueplan_current_state_evidence_id: str
    repository_state_evidence_id: str
    created_at: str
    eligibility_status: Literal["eligible"] = field(default="eligible", init=False)
    authorization_status: Literal["not-evaluated"] = field(
        default="not-evaluated", init=False
    )
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.proposal_version != DRAFT_TASK_PROPOSAL_VERSION:
            raise ValueError("unsupported proposal_version")
        for name in ("handoff_digest", "graph_digest", "planning_result_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"{name} must be a SHA-256 digest")
        _require_timestamp(self.created_at)
        node_ids = _strings(self.supplied_node_ids)
        cohorts = _canonical_cohorts(self.cohort_summaries)
        covered = tuple(sorted(node for cohort in cohorts for node in cohort.node_ids))
        if covered != node_ids:
            raise ValueError("cohort_summaries must cover supplied_node_ids exactly")
        object.__setattr__(self, "supplied_node_ids", node_ids)
        object.__setattr__(self, "cohort_summaries", cohorts)
        expected_id = _proposal_id_from_fields(
            proposal_version=self.proposal_version,
            handoff_digest=self.handoff_digest,
            graph_digest=self.graph_digest,
            planning_result_digest=self.planning_result_digest,
            repository=self.repository,
            base_branch=self.base_branch,
            evaluated_repository_sha=self.evaluated_repository_sha,
            evaluator_commit_sha=self.evaluator_commit_sha,
            supplied_node_ids=node_ids,
            cohort_summaries=cohorts,
            issueplan_current_state_evidence_id=(
                self.issueplan_current_state_evidence_id
            ),
            repository_state_evidence_id=self.repository_state_evidence_id,
        )
        if self.proposal_id != expected_id:
            raise ValueError("proposal_id does not match proposal content")


@dataclass(frozen=True, slots=True)
class DraftTaskProposalResult:
    """Fail-closed WSC3 result with upstream evidence preserved."""

    status: str
    proposals: tuple[DraftTaskProposal, ...]
    reason_codes: tuple[str, ...]
    handoff_validation: HandoffValidationResult
    issueplan_comparison: IssuePlanCurrentStateComparison | None
    repository_state_validation: RepositoryStateValidationResult | None
    authorization_status: Literal["not-evaluated"] = field(
        default="not-evaluated", init=False
    )
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.status not in _WSC3_STATUSES:
            raise ValueError("unsupported WSC3 status")
        proposals = tuple(self.proposals)
        if self.status == "eligible" and len(proposals) != 1:
            raise ValueError("eligible results require exactly one proposal")
        if self.status != "eligible" and proposals:
            raise ValueError("non-eligible results cannot contain proposals")
        reasons = tuple(sorted(set(self.reason_codes)))
        allowed = set(_WSC3_REASON_CODES) | set(self.handoff_validation.reason_codes)
        if self.issueplan_comparison is not None:
            allowed.update(self.issueplan_comparison.reason_codes)
        if self.repository_state_validation is not None:
            allowed.update(self.repository_state_validation.reason_codes)
        if not set(reasons) <= allowed:
            raise ValueError("reason_codes contain an unowned or translated value")
        object.__setattr__(self, "proposals", proposals)
        object.__setattr__(self, "reason_codes", reasons)


def build_draft_task_proposals(
    transported_handoff: SchedulerPlanningHandoff | Mapping[str, Any],
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence | None,
    repository_state_evidence: RepositoryStateEvidence | Mapping[str, Any] | None,
    *,
    created_at: str,
) -> DraftTaskProposalResult:
    """Validate supplied evidence and emit one deterministic unapproved proposal.

    The function is stateless. Repeated identical semantic inputs produce the
    same proposal identity; ``created_at`` is explicit provenance and is excluded
    from proposal identity.
    """

    _require_timestamp(created_at)
    handoff_validation = validate_scheduler_planning_handoff(transported_handoff)
    if handoff_validation.outcome == HandoffValidationOutcome.INVALID:
        return _result(
            "invalid",
            handoff_validation.reason_codes,
            handoff_validation,
        )

    handoff = _coerce_validated_handoff(transported_handoff)
    if issueplan_current_state_evidence is None or repository_state_evidence is None:
        return _result(
            "blocked",
            ("hard-dependency-unmet",),
            handoff_validation,
        )
    if not isinstance(issueplan_current_state_evidence, IssuePlanCurrentStateEvidence):
        return _result(
            "invalid",
            ("hard-dependency-unmet",),
            handoff_validation,
        )

    issueplan_comparison = compare_issueplan_current_state(
        issueplan_current_state_evidence,
        issueplan_current_state_evidence,
    )
    issueplan_status = _issueplan_status(issueplan_comparison.outcome)
    if issueplan_status != "eligible":
        return _result(
            issueplan_status,
            issueplan_comparison.reason_codes,
            handoff_validation,
            issueplan_comparison=issueplan_comparison,
        )

    repository_validation = _validate_repository_for_handoff(
        repository_state_evidence,
        handoff,
        issueplan_current_state_evidence,
    )
    if repository_validation.outcome != "valid":
        return _result(
            repository_validation.outcome,
            repository_validation.reason_codes,
            handoff_validation,
            issueplan_comparison=issueplan_comparison,
            repository_state_validation=repository_validation,
        )

    if not _planning_bindings_match(
        handoff,
        issueplan_current_state_evidence,
        repository_validation,
    ):
        return _result(
            "stale",
            ("planning-state-mismatch",),
            handoff_validation,
            issueplan_comparison=issueplan_comparison,
            repository_state_validation=repository_validation,
        )

    proposal = DraftTaskProposal(
        proposal_version=DRAFT_TASK_PROPOSAL_VERSION,
        proposal_id=_proposal_id(
            handoff,
            issueplan_current_state_evidence,
            repository_validation,
        ),
        handoff_digest=handoff.handoff_digest,
        graph_digest=handoff.graph_digest,
        planning_result_digest=handoff.planning_result_digest,
        repository=handoff.repository,
        base_branch=handoff.base_branch,
        evaluated_repository_sha=handoff.evaluated_repository_sha,
        evaluator_commit_sha=handoff.evaluator_commit_sha,
        supplied_node_ids=handoff.supplied_node_ids,
        cohort_summaries=handoff.cohort_summaries,
        issueplan_current_state_evidence_id=issueplan_current_state_evidence.evidence_id,
        repository_state_evidence_id=repository_validation.evidence_id,
        created_at=created_at,
    )
    return _result(
        "eligible",
        ("approval-not-evaluated",),
        handoff_validation,
        proposals=(proposal,),
        issueplan_comparison=issueplan_comparison,
        repository_state_validation=repository_validation,
    )


def _result(
    status: str,
    reasons: tuple[str, ...] | list[str] | set[str],
    handoff_validation: HandoffValidationResult,
    *,
    proposals: tuple[DraftTaskProposal, ...] = (),
    issueplan_comparison: IssuePlanCurrentStateComparison | None = None,
    repository_state_validation: RepositoryStateValidationResult | None = None,
) -> DraftTaskProposalResult:
    return DraftTaskProposalResult(
        status=status,
        proposals=proposals,
        reason_codes=tuple(reasons),
        handoff_validation=handoff_validation,
        issueplan_comparison=issueplan_comparison,
        repository_state_validation=repository_state_validation,
    )


def _issueplan_status(outcome: IssuePlanCurrentStateOutcome) -> str:
    return {
        IssuePlanCurrentStateOutcome.CURRENT: "eligible",
        IssuePlanCurrentStateOutcome.STALE: "stale",
        IssuePlanCurrentStateOutcome.BLOCKED: "blocked",
        IssuePlanCurrentStateOutcome.INVALID: "invalid",
        IssuePlanCurrentStateOutcome.NEEDS_DECISION: "needs-decision",
    }[outcome]


def _validate_repository_for_handoff(
    value: RepositoryStateEvidence | Mapping[str, Any],
    handoff: SchedulerPlanningHandoff,
    issueplan: IssuePlanCurrentStateEvidence,
) -> RepositoryStateValidationResult:
    kwargs = {
        "expected_base_ref": handoff.base_branch,
        "expected_head_sha": handoff.evaluated_repository_sha,
        "expected_requested_sha": handoff.evaluated_repository_sha,
        "expected_contract_fingerprint": issueplan.implementation_contract_fingerprint,
    }
    initial = validate_repository_state_evidence(value, **kwargs)
    identity = initial.repository_identity
    if identity is None:
        return initial
    owner, repository = handoff.repository.split("/", 1)
    expected_identity = RepositoryIdentity(
        host=identity.host,
        owner=owner,
        repository=repository,
        repository_id=identity.repository_id,
        is_fork=identity.is_fork,
        upstream_owner=identity.upstream_owner,
        upstream_repository=identity.upstream_repository,
        upstream_repository_id=identity.upstream_repository_id,
        default_branch=identity.default_branch,
    )
    return validate_repository_state_evidence(
        value,
        expected_repository=expected_identity,
        **kwargs,
    )


def _planning_bindings_match(
    handoff: SchedulerPlanningHandoff,
    issueplan: IssuePlanCurrentStateEvidence,
    repository: RepositoryStateValidationResult,
) -> bool:
    return all(
        (
            issueplan.repository == handoff.repository,
            issueplan.base_branch == handoff.base_branch,
            issueplan.evaluated_repository_sha == handoff.evaluated_repository_sha,
            issueplan.implementation_contract_fingerprint is not None,
            issueplan.graph_reference == handoff.graph_digest,
            issueplan.planning_result_reference == handoff.planning_result_digest,
            issueplan.handoff_reference == handoff.handoff_digest,
            issueplan.supplied_node_ids == handoff.supplied_node_ids,
            repository.head_sha == handoff.evaluated_repository_sha,
            repository.requested_sha == handoff.evaluated_repository_sha,
        )
    )


def _proposal_id(
    handoff: SchedulerPlanningHandoff,
    issueplan: IssuePlanCurrentStateEvidence,
    repository: RepositoryStateValidationResult,
) -> str:
    return _proposal_id_from_fields(
        proposal_version=DRAFT_TASK_PROPOSAL_VERSION,
        handoff_digest=handoff.handoff_digest,
        graph_digest=handoff.graph_digest,
        planning_result_digest=handoff.planning_result_digest,
        repository=handoff.repository,
        base_branch=handoff.base_branch,
        evaluated_repository_sha=handoff.evaluated_repository_sha,
        evaluator_commit_sha=handoff.evaluator_commit_sha,
        supplied_node_ids=handoff.supplied_node_ids,
        cohort_summaries=handoff.cohort_summaries,
        issueplan_current_state_evidence_id=issueplan.evidence_id,
        repository_state_evidence_id=repository.evidence_id,
    )


def _proposal_id_from_fields(
    *,
    proposal_version: str,
    handoff_digest: str,
    graph_digest: str,
    planning_result_digest: str,
    repository: str,
    base_branch: str,
    evaluated_repository_sha: str,
    evaluator_commit_sha: str,
    supplied_node_ids: tuple[str, ...],
    cohort_summaries: tuple[HandoffCohort, ...],
    issueplan_current_state_evidence_id: str,
    repository_state_evidence_id: str,
) -> str:
    payload = {
        "proposal_version": proposal_version,
        "handoff_digest": handoff_digest,
        "graph_digest": graph_digest,
        "planning_result_digest": planning_result_digest,
        "repository": repository,
        "base_branch": base_branch,
        "evaluated_repository_sha": evaluated_repository_sha,
        "evaluator_commit_sha": evaluator_commit_sha,
        "supplied_node_ids": list(_strings(supplied_node_ids)),
        "cohort_summaries": [
            {
                "node_ids": list(cohort.node_ids),
                "classification": cohort.classification,
                "reason_codes": list(cohort.reason_codes),
            }
            for cohort in _canonical_cohorts(cohort_summaries)
        ],
        "issueplan_current_state_evidence_id": issueplan_current_state_evidence_id,
        "repository_state_evidence_id": repository_state_evidence_id,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"draft-task-proposal:{digest}"


def _coerce_validated_handoff(
    value: SchedulerPlanningHandoff | Mapping[str, Any],
) -> SchedulerPlanningHandoff:
    if isinstance(value, SchedulerPlanningHandoff):
        return value
    cohorts = tuple(
        HandoffCohort(
            node_ids=tuple(item["node_ids"]),
            classification=item["classification"],
            reason_codes=tuple(item["reason_codes"]),
        )
        for item in value["cohort_summaries"]
    )
    return SchedulerPlanningHandoff(
        contract_version=value["contract_version"],
        planning_result_version=value["planning_result_version"],
        evaluator_commit_sha=value["evaluator_commit_sha"],
        repository=value["repository"],
        base_branch=value["base_branch"],
        evaluated_repository_sha=value["evaluated_repository_sha"],
        supplied_node_ids=tuple(value["supplied_node_ids"]),
        graph_digest=value["graph_digest"],
        planning_result_digest=value["planning_result_digest"],
        cohort_summaries=cohorts,
        created_at=value["created_at"],
        handoff_digest=value["handoff_digest"],
    )


def _canonical_cohorts(values: tuple[HandoffCohort, ...]) -> tuple[HandoffCohort, ...]:
    cohorts = tuple(values)
    if not all(isinstance(value, HandoffCohort) for value in cohorts):
        raise TypeError("cohort_summaries must contain HandoffCohort values")
    return tuple(
        sorted(
            cohorts,
            key=lambda value: (
                value.classification,
                tuple(value.node_ids),
                tuple(value.reason_codes),
            ),
        )
    )


def _strings(values: tuple[str, ...]) -> tuple[str, ...]:
    items = tuple(values)
    if not items or not all(isinstance(value, str) and value for value in items):
        raise ValueError("supplied_node_ids must contain unique non-empty strings")
    if len(items) != len(set(items)):
        raise ValueError("supplied_node_ids must be unique")
    return tuple(sorted(items))


def _require_timestamp(value: object) -> None:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError("created_at must be an explicit UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("created_at must be a valid UTC timestamp") from exc
