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
from scripts.agent_os_issue_acceptance.planning_binding import (
    PlanningBindingEvidence,
    build_planning_binding_evidence,
    reconstruct_planning_binding_evidence,
    serialize_planning_binding_evidence,
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
    reconstruct_batch_planning_result,
    reconstruct_handoff_validation_result,
    reconstruct_issue_batch_graph,
    serialize_batch_planning_result,
    serialize_handoff_validation_result,
    serialize_issue_batch_graph,
    serialize_scheduler_planning_handoff,
    validate_scheduler_planning_handoff,
)

from .stage_models import (
    STAGE_SCHEMA_VERSION,
    DependencyIdentityStatus,
    IssueReadinessStageResult,
    IssueReadinessStageStatus,
    issueplan_current_state_evidence_from_dict,
    issueplan_current_state_evidence_to_dict,
    require_exact_keys,
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

    ``planning_binding`` is the post-planning attestation joining that exact
    IssuePlan identity to the graph, planning-result, and handoff digests
    produced after the identity was fixed. It is optional: a complete result
    built from an IssuePlan that carries no pre-planning context has nothing to
    bind, and downstream consumers then fall back to the legacy
    IssuePlan-reference route. Like the evidence above it is retained by
    identity, never rebuilt.
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
    planning_binding: PlanningBindingEvidence | None = None
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
        if not complete and self.planning_binding is not None:
            raise ValueError("invalid-input results must not carry partial objects")
        if self.issueplan_current_state_evidence is not None and not isinstance(
            self.issueplan_current_state_evidence, IssuePlanCurrentStateEvidence
        ):
            raise TypeError(
                "issueplan_current_state_evidence must be an "
                "IssuePlanCurrentStateEvidence"
            )
        if self.planning_binding is not None and not isinstance(
            self.planning_binding, PlanningBindingEvidence
        ):
            raise TypeError("planning_binding must be a PlanningBindingEvidence")
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

    # The binding can only be built once the handoff exists, and only when the
    # IssuePlan carries the pre-planning context it must attest to. Without that
    # context there is nothing to bind, and the legacy route still applies.
    planning_binding: PlanningBindingEvidence | None = None
    if issueplan.implementation_contract_fingerprint is not None:
        try:
            planning_binding = build_planning_binding_evidence(
                issueplan, handoff, created_at=created_at
            )
        except (TypeError, ValueError) as error:
            return _invalid((f"planning-binding-rejected:{error}",))

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
        planning_binding=planning_binding,
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


_PLANNING_STAGE_RESULT_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "graph",
        "planning_result",
        "handoff",
        "handoff_validation",
        "wsc3_suppliable",
        "reason_codes",
        "issueplan_current_state_evidence",
        "planning_binding",
        "execution_authorized",
        "side_effects_performed",
    }
)


def planning_handoff_stage_result_to_dict(
    result: PlanningHandoffStageResult,
) -> dict[str, Any]:
    """Serialize one canonical PlanningHandoffStageResult, delegating every nested object.

    ``node`` and ``serialized_handoff`` are not carried as independent payload
    fields: ``node`` is always the graph's own single supplied node and
    ``serialized_handoff`` is always the exact bytes ``handoff`` itself
    canonically serializes to, so ``planning_handoff_stage_result_from_dict``
    rebuilds both from the graph and handoff rather than transporting a
    duplicate copy.
    """
    if not isinstance(result, PlanningHandoffStageResult):
        raise TypeError("result must be a PlanningHandoffStageResult")
    payload = {
        "schema_version": STAGE_SCHEMA_VERSION,
        "status": result.status.value,
        "graph": (
            None
            if result.graph is None
            else json.loads(serialize_issue_batch_graph(result.graph))
        ),
        "planning_result": (
            None
            if result.planning_result is None
            else json.loads(serialize_batch_planning_result(result.planning_result))
        ),
        "handoff": (
            None
            if result.handoff is None
            else json.loads(serialize_scheduler_planning_handoff(result.handoff))
        ),
        "handoff_validation": (
            None
            if result.handoff_validation is None
            else json.loads(
                serialize_handoff_validation_result(result.handoff_validation)
            )
        ),
        "wsc3_suppliable": result.wsc3_suppliable,
        "reason_codes": list(result.reason_codes),
        "issueplan_current_state_evidence": (
            None
            if result.issueplan_current_state_evidence is None
            else issueplan_current_state_evidence_to_dict(
                result.issueplan_current_state_evidence
            )
        ),
        "planning_binding": (
            None
            if result.planning_binding is None
            else json.loads(
                serialize_planning_binding_evidence(result.planning_binding)
            )
        ),
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    if planning_handoff_stage_result_from_dict(payload) != result:
        raise ValueError("result has noncanonical planning handoff stage fields")
    return payload


def planning_handoff_stage_result_from_dict(
    payload: Mapping[str, Any],
) -> PlanningHandoffStageResult:
    """Reconstruct one canonical PlanningHandoffStageResult, failing closed on drift.

    Cross-object bindings are re-verified rather than trusted: the graph and
    planning-result digests must match the handoff's own digests, the handoff
    validation must equal what re-running ``validate_scheduler_planning_handoff``
    on the handoff itself produces, and any planning binding must equal what
    ``build_planning_binding_evidence`` rebuilds from the carried IssuePlan
    evidence and handoff.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("planning handoff stage result must be a mapping")
    if payload.get("schema_version") != STAGE_SCHEMA_VERSION:
        raise ValueError("unsupported stage schema_version")
    require_exact_keys(
        payload, _PLANNING_STAGE_RESULT_PAYLOAD_KEYS, "planning handoff stage result"
    )
    if payload["execution_authorized"] is not False:
        raise ValueError("execution_authorized must be false")
    if payload["side_effects_performed"] is not False:
        raise ValueError("side_effects_performed must be false")
    if type(payload["wsc3_suppliable"]) is not bool:
        raise ValueError("wsc3_suppliable must be an exact boolean")

    status = PlanningHandoffStageStatus(payload["status"])

    graph_payload = payload["graph"]
    planning_result_payload = payload["planning_result"]
    handoff_payload = payload["handoff"]
    handoff_validation_payload = payload["handoff_validation"]
    issueplan_payload = payload["issueplan_current_state_evidence"]
    planning_binding_payload = payload["planning_binding"]

    graph = (
        None if graph_payload is None else reconstruct_issue_batch_graph(graph_payload)
    )
    planning_result = (
        None
        if planning_result_payload is None
        else reconstruct_batch_planning_result(planning_result_payload)
    )
    handoff = (
        None
        if handoff_payload is None
        else reconstruct_scheduler_planning_handoff(handoff_payload)
    )
    handoff_validation = (
        None
        if handoff_validation_payload is None
        else reconstruct_handoff_validation_result(handoff_validation_payload)
    )
    issueplan = (
        None
        if issueplan_payload is None
        else issueplan_current_state_evidence_from_dict(issueplan_payload)
    )
    planning_binding = (
        None
        if planning_binding_payload is None
        else reconstruct_planning_binding_evidence(planning_binding_payload)
    )

    if graph is not None and handoff is not None:
        if compute_graph_digest(graph) != handoff.graph_digest:
            raise ValueError("graph does not bind to the handoff's graph_digest")
    if planning_result is not None and handoff is not None:
        if compute_planning_result_digest(planning_result) != handoff.planning_result_digest:
            raise ValueError(
                "planning result does not bind to the handoff's planning_result_digest"
            )
    if handoff is not None and handoff_validation is not None:
        if validate_scheduler_planning_handoff(handoff) != handoff_validation:
            raise ValueError("handoff validation does not match the carried handoff")
    if planning_binding is not None:
        if handoff is None or issueplan is None:
            raise ValueError(
                "planning binding requires both the handoff and IssuePlan evidence"
            )
        rebuilt_binding = build_planning_binding_evidence(
            issueplan, handoff, created_at=planning_binding.created_at
        )
        if rebuilt_binding != planning_binding:
            raise ValueError(
                "planning binding does not match the IssuePlan evidence and handoff"
            )

    node: IssueBatchNode | None = None
    if graph is not None:
        if not graph.nodes:
            raise ValueError("graph must contain the stage node")
        node = graph.nodes[0]

    serialized_handoff = (
        None if handoff is None else serialize_scheduler_planning_handoff(handoff)
    )

    reason_codes = payload["reason_codes"]
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise ValueError("reason_codes must be a list of strings")

    return PlanningHandoffStageResult(
        status=status,
        node=node,
        graph=graph,
        planning_result=planning_result,
        handoff=handoff,
        serialized_handoff=serialized_handoff,
        handoff_validation=handoff_validation,
        wsc3_suppliable=payload["wsc3_suppliable"],
        reason_codes=tuple(reason_codes),
        issueplan_current_state_evidence=issueplan,
        planning_binding=planning_binding,
    )


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
