from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields, replace
from enum import Enum
from typing import Any, Mapping

from .batch_graph import IssueBatchGraph
from .batch_planning import BatchPlanningResult, PlanningClassification

SUPPORTED_CONTRACT_VERSIONS = frozenset({"0.2.0"})
SUPPORTED_PLANNING_RESULT_VERSIONS = frozenset({"0.1.0"})
PLANNING_SCOPE = "supplied-graph-only"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RFC3339_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_CLASSIFICATION_ORDER = {
    PlanningClassification.BLOCKED.value: 0,
    PlanningClassification.NEEDS_DECISION.value: 1,
    PlanningClassification.SEQUENCING_REVIEW.value: 2,
    PlanningClassification.PARALLEL_CANDIDATE.value: 3,
}


class HandoffValidationOutcome(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    INVALID = "invalid"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True)
class HandoffCohort:
    node_ids: tuple[str, ...]
    classification: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        node_ids = _normalized_string_tuple(self.node_ids, "node_ids")
        reason_codes = _normalized_string_tuple(self.reason_codes, "reason_codes")
        classification = _classification_value(self.classification)
        if not node_ids:
            raise ValueError("node_ids must not be empty")
        object.__setattr__(self, "node_ids", node_ids)
        object.__setattr__(self, "reason_codes", reason_codes)
        object.__setattr__(self, "classification", classification)


@dataclass(frozen=True)
class SchedulerPlanningHandoff:
    contract_version: str
    planning_result_version: str
    evaluator_commit_sha: str
    repository: str
    base_branch: str
    evaluated_repository_sha: str
    supplied_node_ids: tuple[str, ...]
    graph_digest: str
    planning_result_digest: str
    cohort_summaries: tuple[HandoffCohort, ...]
    planning_scope: str
    execution_authorized: bool
    created_at: str
    handoff_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "supplied_node_ids", _normalized_string_tuple(self.supplied_node_ids, "supplied_node_ids"))
        cohorts = tuple(self.cohort_summaries)
        if any(not isinstance(item, HandoffCohort) for item in cohorts):
            raise TypeError("cohort_summaries must contain only HandoffCohort values")
        object.__setattr__(self, "cohort_summaries", _sorted_cohorts(cohorts))


@dataclass(frozen=True)
class HandoffValidationResult:
    outcome: HandoffValidationOutcome
    reason_codes: tuple[str, ...] = ()


def serialize_scheduler_planning_handoff(handoff: SchedulerPlanningHandoff) -> bytes:
    """Return byte-exact canonical JSON for one immutable handoff."""
    if not isinstance(handoff, SchedulerPlanningHandoff):
        raise TypeError("handoff must be a SchedulerPlanningHandoff")
    return _canonical_bytes(_handoff_payload(handoff, include_digest=True))


def compute_graph_digest(graph: IssueBatchGraph) -> str:
    if not isinstance(graph, IssueBatchGraph):
        raise TypeError("graph must be an IssueBatchGraph")
    nodes = []
    for node in sorted(graph.nodes, key=lambda item: item.node_id):
        nodes.append(
            {
                "node_id": node.node_id,
                "readiness": node.readiness.value,
                "readiness_evidence": list(_normalized_string_tuple(node.readiness_evidence, "readiness_evidence")),
                "owner": node.owner,
                "source_of_truth": node.source_of_truth,
                "affected_paths": list(_normalized_string_tuple(node.affected_paths, "affected_paths")),
                "forbidden_paths": list(_normalized_string_tuple(node.forbidden_paths, "forbidden_paths")),
                "dependency_ids": list(_normalized_string_tuple(node.dependency_ids, "dependency_ids")),
                "entity_id": node.entity_id,
                "provenance": list(_normalized_string_tuple(node.provenance, "provenance")),
            }
        )
    payload = {
        "nodes": nodes,
        "resolved_dependencies": [list(pair) for pair in sorted(set(graph.resolved_dependencies))],
        "unresolved_dependencies": [list(pair) for pair in sorted(set(graph.unresolved_dependencies))],
    }
    return _sha256(payload)


def compute_planning_result_digest(result: BatchPlanningResult) -> str:
    if not isinstance(result, BatchPlanningResult):
        raise TypeError("result must be a BatchPlanningResult")
    payload = {
        "supplied_node_ids": list(tuple(sorted(result.supplied_node_ids))),
        "overall_classification": result.overall_classification.value,
        "cohorts": [
            {
                "node_ids": list(tuple(sorted(cohort.node_ids))),
                "classification": cohort.classification.value,
                "reason_codes": list(tuple(sorted(set(cohort.reason_codes)))),
                "dependency_pairs": [list(pair) for pair in sorted(set(cohort.dependency_pairs))],
                "sequencing_pairs": [list(pair) for pair in sorted(set(cohort.sequencing_pairs))],
            }
            for cohort in sorted(
                result.cohorts,
                key=lambda item: (_CLASSIFICATION_ORDER[item.classification.value], tuple(sorted(item.node_ids))),
            )
        ],
        "batch_reason_codes": list(tuple(sorted(set(result.batch_reason_codes)))),
        "cycle_node_groups": [list(group) for group in sorted({tuple(sorted(group)) for group in result.cycle_node_groups})],
    }
    return _sha256(payload)


def compute_handoff_digest(handoff_without_digest: SchedulerPlanningHandoff) -> str:
    if not isinstance(handoff_without_digest, SchedulerPlanningHandoff):
        raise TypeError("handoff_without_digest must be a SchedulerPlanningHandoff")
    return _sha256(_handoff_payload(handoff_without_digest, include_digest=False))


def with_computed_handoff_digest(handoff: SchedulerPlanningHandoff) -> SchedulerPlanningHandoff:
    """Return a new immutable handoff with its canonical digest attached."""
    return replace(handoff, handoff_digest=compute_handoff_digest(handoff))


def validate_scheduler_planning_handoff(
    handoff: SchedulerPlanningHandoff | Mapping[str, Any],
) -> HandoffValidationResult:
    """Perform local structural and self-consistency validation only.

    A successful local validation is `needs-decision`, not `fresh`, because ADR 0002
    requires current repository, evaluator, graph, ownership, and source-of-truth
    revalidation before freshness can be established.
    """
    try:
        candidate = _coerce_handoff(handoff)
    except (TypeError, ValueError, KeyError):
        return HandoffValidationResult(HandoffValidationOutcome.INVALID, ("malformed-handoff",))

    reasons: list[str] = []
    if candidate.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        reasons.append("unsupported-contract-version")
    if candidate.planning_result_version not in SUPPORTED_PLANNING_RESULT_VERSIONS:
        reasons.append("unsupported-planning-result-version")
    if candidate.planning_scope != PLANNING_SCOPE:
        reasons.append("invalid-planning-scope")
    if candidate.execution_authorized is not False:
        reasons.append("execution-authorized-must-be-false")
    if not _COMMIT_SHA_RE.fullmatch(candidate.evaluator_commit_sha):
        reasons.append("malformed-evaluator-commit-sha")
    if not _COMMIT_SHA_RE.fullmatch(candidate.evaluated_repository_sha):
        reasons.append("malformed-evaluated-repository-sha")
    if not _valid_repository(candidate.repository):
        reasons.append("malformed-repository")
    if not _non_empty(candidate.base_branch):
        reasons.append("malformed-base-branch")
    if not _RFC3339_UTC_RE.fullmatch(candidate.created_at):
        reasons.append("malformed-created-at")
    if not candidate.supplied_node_ids:
        reasons.append("empty-supplied-node-ids")
    if len(candidate.supplied_node_ids) != len(set(candidate.supplied_node_ids)):
        reasons.append("duplicate-supplied-node-ids")
    for field_name in ("graph_digest", "planning_result_digest", "handoff_digest"):
        if not _SHA256_RE.fullmatch(getattr(candidate, field_name)):
            reasons.append(f"malformed-{field_name.replace('_', '-')}")

    covered = tuple(sorted(node_id for cohort in candidate.cohort_summaries for node_id in cohort.node_ids))
    if covered != candidate.supplied_node_ids or len(covered) != len(set(covered)):
        reasons.append("partial-or-duplicate-cohort-coverage")
    if candidate.handoff_digest and _SHA256_RE.fullmatch(candidate.handoff_digest):
        if compute_handoff_digest(candidate) != candidate.handoff_digest:
            reasons.append("handoff-digest-mismatch")

    if reasons:
        return HandoffValidationResult(HandoffValidationOutcome.INVALID, tuple(sorted(set(reasons))))
    return HandoffValidationResult(
        HandoffValidationOutcome.NEEDS_DECISION,
        ("current-state-revalidation-required",),
    )


def _coerce_handoff(value: SchedulerPlanningHandoff | Mapping[str, Any]) -> SchedulerPlanningHandoff:
    if isinstance(value, SchedulerPlanningHandoff):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("handoff must be a SchedulerPlanningHandoff or mapping")
    required = {item.name for item in fields(SchedulerPlanningHandoff)}
    unknown = set(value) - required
    missing = required - set(value)
    if missing or unknown:
        raise ValueError("handoff fields do not match the required schema")
    cohorts_raw = value["cohort_summaries"]
    if isinstance(cohorts_raw, (str, bytes)):
        raise TypeError("cohort_summaries must be iterable")
    cohorts = tuple(
        item if isinstance(item, HandoffCohort) else HandoffCohort(**item)
        for item in cohorts_raw
    )
    return SchedulerPlanningHandoff(**{**dict(value), "cohort_summaries": cohorts})


def _handoff_payload(handoff: SchedulerPlanningHandoff, *, include_digest: bool) -> dict[str, Any]:
    payload = {
        "contract_version": handoff.contract_version,
        "planning_result_version": handoff.planning_result_version,
        "evaluator_commit_sha": handoff.evaluator_commit_sha,
        "repository": handoff.repository,
        "base_branch": handoff.base_branch,
        "evaluated_repository_sha": handoff.evaluated_repository_sha,
        "supplied_node_ids": list(tuple(sorted(handoff.supplied_node_ids))),
        "graph_digest": handoff.graph_digest,
        "planning_result_digest": handoff.planning_result_digest,
        "cohort_summaries": [
            {
                "node_ids": list(cohort.node_ids),
                "classification": cohort.classification,
                "reason_codes": list(cohort.reason_codes),
            }
            for cohort in _sorted_cohorts(handoff.cohort_summaries)
        ],
        "planning_scope": handoff.planning_scope,
        "execution_authorized": handoff.execution_authorized,
        "created_at": handoff.created_at,
    }
    if include_digest:
        payload["handoff_digest"] = handoff.handoff_digest
    return payload


def _sorted_cohorts(cohorts: tuple[HandoffCohort, ...]) -> tuple[HandoffCohort, ...]:
    return tuple(
        sorted(
            cohorts,
            key=lambda item: (_CLASSIFICATION_ORDER[item.classification], item.node_ids[0]),
        )
    )


def _classification_value(value: str | PlanningClassification) -> str:
    canonical = value.value if isinstance(value, PlanningClassification) else value
    if canonical not in _CLASSIFICATION_ORDER:
        raise ValueError(f"unknown classification: {canonical}")
    return canonical


def _normalized_string_tuple(values: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be an iterable of strings")
    normalized = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must contain non-empty strings")
        normalized.add(value.strip())
    return tuple(sorted(normalized))


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _valid_repository(value: object) -> bool:
    return isinstance(value, str) and value.count("/") == 1 and all(part.strip() for part in value.split("/"))


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
