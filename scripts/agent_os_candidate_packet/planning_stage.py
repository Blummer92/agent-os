"""Pure-local #751 coordinator from readiness evidence through Scheduler handoff."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from scripts.agent_os_issue_acceptance.batch_graph import (
    IssueBatchGraph,
    IssueBatchNode,
    build_issue_batch_graph,
)
from scripts.agent_os_issue_acceptance.batch_planning import (
    BatchPlanningResult,
    PlanningClassification,
    evaluate_batch_plan,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    IssuePlanCurrentStateEvidence,
)
from scripts.agent_os_issue_acceptance.readiness import ReadinessOutcome
from scripts.agent_os_issue_acceptance.scheduler_handoff import (
    HandoffCohort,
    HandoffValidationResult,
    SchedulerPlanningHandoff,
    SUPPORTED_CONTRACT_VERSIONS,
    SUPPORTED_PLANNING_RESULT_VERSIONS,
    compute_graph_digest,
    compute_handoff_digest,
    compute_planning_result_digest,
    serialize_scheduler_planning_handoff,
    validate_scheduler_planning_handoff,
)

from .stage_models import (
    DependencyIdentityStatus,
    IssueReadinessStageResult,
    IssueReadinessStageStatus,
)

_OPTIONAL_GOVERNED_FIELD_STATES = frozenset(
    {"absent", "null", "intentionally-omitted"}
)


class PlanningHandoffStageStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"
    INVALID_INPUT = "invalid-input"


@dataclass(frozen=True, slots=True)
class PlanningHandoffStageResult:
    """One planning-stage outcome plus the evidence a downstream stage needs.

    ``issueplan_current_state_evidence`` retains the exact canonical
    ``IssuePlanCurrentStateEvidence`` object this stage already consumed, so a
    downstream consumer (AOS-AUTO1C, #752) can forward it to WSC3 without
    rebuilding it from an evidence ID, node provenance, digest, or another
    partial representation. It is the same object, not a copy: nothing here
    reconstructs, normalizes, or duplicates it, and handoff bytes, digests, and
    classifications are unaffected by its presence.

    Compatibility, stated precisely: the field is trailing with a default, so
    every existing positional and keyword call site still *binds*. An
    invalid-input result built the pre-#752 way is unchanged. Direct
    construction of a *complete* result, however, now requires the evidence,
    exactly as it already requires ``node``, ``graph``, ``planning_result``,
    ``handoff``, ``serialized_handoff``, and ``handoff_validation``: exempting
    only this field would let a complete result ship without the object WSC3
    needs. ``prepare_planning_handoff(...)`` supplies it, so callers that use
    the constructor directly to assemble a complete result are the only ones
    affected.
    """

    status: PlanningHandoffStageStatus
    node: IssueBatchNode | None
    graph: IssueBatchGraph | None
    planning_result: BatchPlanningResult | None
    handoff: SchedulerPlanningHandoff | None
    serialized_handoff: bytes | None
    handoff_validation: HandoffValidationResult | None
    wsc3_suppliable: bool
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence | None = None
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, PlanningHandoffStageStatus):
            raise TypeError("status must be a PlanningHandoffStageStatus")
        complete = self.status != PlanningHandoffStageStatus.INVALID_INPUT
        values = (
            self.node,
            self.graph,
            self.planning_result,
            self.handoff,
            self.serialized_handoff,
            self.handoff_validation,
            self.issueplan_current_state_evidence,
        )
        if complete and any(value is None for value in values):
            raise ValueError("complete planning results require every canonical object")
        if not complete and any(value is not None for value in values):
            raise ValueError("invalid-input results must not carry partial objects")
        if self.issueplan_current_state_evidence is not None and not isinstance(
            self.issueplan_current_state_evidence, IssuePlanCurrentStateEvidence
        ):
            raise TypeError(
                "issueplan_current_state_evidence must be an "
                "IssuePlanCurrentStateEvidence"
            )
        object.__setattr__(
            self, "reason_codes", tuple(sorted(set(self.reason_codes)))
        )


def prepare_planning_handoff(
    readiness_stage_result: IssueReadinessStageResult,
    *,
    evaluator_sha: str,
    created_at: str,
) -> PlanningHandoffStageResult:
    """Construct node, graph, plan, and handoff without external I/O or authority."""
    if not isinstance(readiness_stage_result, IssueReadinessStageResult):
        raise TypeError("readiness_stage_result must be an IssueReadinessStageResult")

    if readiness_stage_result.status not in {
        IssueReadinessStageStatus.READY,
        IssueReadinessStageStatus.BLOCKED,
        IssueReadinessStageStatus.NEEDS_DECISION,
    }:
        return _invalid(("readiness-stage-unresolved",))

    snapshot = readiness_stage_result.snapshot
    issueplan = readiness_stage_result.issueplan_current_state_evidence
    readiness = readiness_stage_result.readiness_result
    dependency_evidence = readiness_stage_result.dependency_identity_evidence
    if (
        snapshot is None
        or issueplan is None
        or readiness is None
        or dependency_evidence is None
    ):
        return _invalid(("readiness-stage-partial",))
    if not issueplan.base_branch:
        return _invalid(("missing-base-branch",))
    if not issueplan.evaluated_repository_sha:
        return _invalid(("missing-evaluated-repository-sha",))
    if issueplan.repository != snapshot.repository:
        return _invalid(("repository-binding-mismatch",))

    try:
        owner = _decode_governed_text(
            issueplan.source_snapshot.governed_fields, "owner_agent"
        )
        source_of_truth = _decode_governed_text(
            issueplan.source_snapshot.governed_fields, "source_of_truth"
        )
    except ValueError as error:
        return _invalid((str(error),))

    node_readiness = readiness.outcome
    dependency_ids: tuple[str, ...]
    stage_reasons = set(readiness_stage_result.reason_codes)
    if dependency_evidence.status == DependencyIdentityStatus.RESOLVED:
        dependency_ids = dependency_evidence.dependency_ids
    elif dependency_evidence.status == DependencyIdentityStatus.ABSENT:
        dependency_ids = ()
    else:
        dependency_ids = ()
        stage_reasons.update(dependency_evidence.reason_codes)
        stage_reasons.add("dependency-identity-incomplete")
        if node_readiness is ReadinessOutcome.READY:
            node_readiness = ReadinessOutcome.NEEDS_DECISION

    entity_id = issueplan.entity_ids[0] if len(issueplan.entity_ids) == 1 else None
    if len(issueplan.entity_ids) > 1:
        stage_reasons.add("multiple-entity-identities")
        if node_readiness is ReadinessOutcome.READY:
            node_readiness = ReadinessOutcome.NEEDS_DECISION

    node = IssueBatchNode(
        node_id=f"issue-{snapshot.issue_number}",
        readiness=node_readiness,
        readiness_evidence=(
            *sorted(stage_reasons),
            f"issueplan-evidence:{issueplan.evidence_id}",
        ),
        owner=owner,
        source_of_truth=source_of_truth,
        affected_paths=issueplan.allowed_files,
        forbidden_paths=issueplan.forbidden_paths,
        dependency_ids=dependency_ids,
        entity_id=entity_id,
        provenance=(
            f"issue-snapshot:{snapshot.source_revision}",
            f"issueplan-evidence:{issueplan.evidence_id}",
            *issueplan.source_snapshot.provenance_references,
            *dependency_evidence.provenance,
        ),
    )
    graph = build_issue_batch_graph((node,))
    planning_result = evaluate_batch_plan(graph)
    graph_digest = compute_graph_digest(graph)
    planning_result_digest = compute_planning_result_digest(planning_result)
    cohort_summaries = tuple(
        HandoffCohort(
            node_ids=cohort.node_ids,
            classification=cohort.classification.value,
            reason_codes=cohort.reason_codes,
        )
        for cohort in planning_result.cohorts
    )
    without_digest: dict[str, Any] = {
        "contract_version": SUPPORTED_CONTRACT_VERSIONS[-1],
        "planning_result_version": SUPPORTED_PLANNING_RESULT_VERSIONS[-1],
        "evaluator_commit_sha": evaluator_sha,
        "repository": snapshot.repository,
        "base_branch": issueplan.base_branch,
        "evaluated_repository_sha": issueplan.evaluated_repository_sha,
        "supplied_node_ids": planning_result.supplied_node_ids,
        "graph_digest": graph_digest,
        "planning_result_digest": planning_result_digest,
        "cohort_summaries": cohort_summaries,
        "planning_scope": "supplied-graph-only",
        "execution_authorized": False,
        "created_at": created_at,
    }
    handoff_fields = {
        name: value
        for name, value in without_digest.items()
        if name not in {"planning_scope", "execution_authorized"}
    }
    handoff = SchedulerPlanningHandoff(
        **handoff_fields,
        handoff_digest=compute_handoff_digest(without_digest),
    )
    serialized = serialize_scheduler_planning_handoff(handoff)
    reconstructed = reconstruct_scheduler_planning_handoff(serialized)
    if reconstructed != handoff:
        return _invalid(("handoff-reconstruction-mismatch",))
    if serialize_scheduler_planning_handoff(reconstructed) != serialized:
        return _invalid(("handoff-serialization-drift",))

    validation = validate_scheduler_planning_handoff(reconstructed)
    if not validation.local_checks_passed:
        return _invalid(validation.reason_codes)

    stage_reasons.update(validation.reason_codes)
    status = _stage_status(planning_result.overall_classification)
    return PlanningHandoffStageResult(
        status=status,
        node=node,
        graph=graph,
        planning_result=planning_result,
        handoff=handoff,
        serialized_handoff=serialized,
        handoff_validation=validation,
        wsc3_suppliable=True,
        reason_codes=tuple(stage_reasons),
        # The exact object consumed above -- not a rebuilt equivalent.
        issueplan_current_state_evidence=issueplan,
    )


def reconstruct_scheduler_planning_handoff(
    payload: bytes | str | Mapping[str, Any],
) -> SchedulerPlanningHandoff:
    """Strictly reconstruct one canonical handoff and reject digest/schema drift."""
    if isinstance(payload, bytes):
        try:
            raw: object = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("serialized handoff must be canonical UTF-8 JSON") from error
    elif isinstance(payload, str):
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("serialized handoff must be JSON") from error
    elif isinstance(payload, Mapping):
        raw = dict(payload)
    else:
        raise TypeError("payload must be bytes, text, or a mapping")
    if not isinstance(raw, Mapping):
        raise ValueError("handoff payload must be a mapping")

    validation = validate_scheduler_planning_handoff(raw)
    if not validation.local_checks_passed:
        reasons = ",".join(validation.reason_codes)
        raise ValueError(f"invalid SchedulerPlanningHandoff: {reasons}")

    cohorts = tuple(
        HandoffCohort(
            node_ids=tuple(item["node_ids"]),
            classification=item["classification"],
            reason_codes=tuple(item["reason_codes"]),
        )
        for item in raw["cohort_summaries"]
    )
    handoff = SchedulerPlanningHandoff(
        contract_version=raw["contract_version"],
        planning_result_version=raw["planning_result_version"],
        evaluator_commit_sha=raw["evaluator_commit_sha"],
        repository=raw["repository"],
        base_branch=raw["base_branch"],
        evaluated_repository_sha=raw["evaluated_repository_sha"],
        supplied_node_ids=tuple(raw["supplied_node_ids"]),
        graph_digest=raw["graph_digest"],
        planning_result_digest=raw["planning_result_digest"],
        cohort_summaries=cohorts,
        created_at=raw["created_at"],
        handoff_digest=raw["handoff_digest"],
    )
    return handoff


def _decode_governed_text(
    governed_fields: tuple[tuple[str, str, str | None], ...], field_name: str
) -> str | None:
    """Decode one canonical JSON string at the planning consumption boundary."""
    match = next(
        (item for item in governed_fields if item[0] == field_name),
        None,
    )
    if match is None:
        return None

    _, state, canonical_value = match
    if state in _OPTIONAL_GOVERNED_FIELD_STATES:
        return None
    if state != "present":
        raise ValueError(f"{field_name}-governed-value-{state}")
    if canonical_value is None:
        raise ValueError(f"{field_name}-governed-value-missing")

    try:
        decoded = json.loads(canonical_value)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError(f"{field_name}-governed-value-malformed") from error
    if not isinstance(decoded, str):
        raise ValueError(f"{field_name}-governed-value-not-string")
    if not decoded.strip():
        raise ValueError(f"{field_name}-governed-value-empty")
    if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
        raise ValueError(f"{field_name}-governed-value-control-character")
    return decoded


def _stage_status(
    classification: PlanningClassification,
) -> PlanningHandoffStageStatus:
    if classification is PlanningClassification.BLOCKED:
        return PlanningHandoffStageStatus.BLOCKED
    if classification in {
        PlanningClassification.NEEDS_DECISION,
        PlanningClassification.SEQUENCING_REVIEW,
    }:
        return PlanningHandoffStageStatus.NEEDS_DECISION
    return PlanningHandoffStageStatus.READY


def _invalid(reason_codes: tuple[str, ...]) -> PlanningHandoffStageResult:
    return PlanningHandoffStageResult(
        status=PlanningHandoffStageStatus.INVALID_INPUT,
        node=None,
        graph=None,
        planning_result=None,
        handoff=None,
        serialized_handoff=None,
        handoff_validation=None,
        wsc3_suppliable=False,
        reason_codes=reason_codes,
        issueplan_current_state_evidence=None,
    )
