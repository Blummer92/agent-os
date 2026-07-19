from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal

from .batch_graph import IssueBatchGraph
from .batch_planning import BatchPlanningResult

SUPPORTED_CONTRACT_VERSIONS = ("0.2.0",)
SUPPORTED_PLANNING_RESULT_VERSIONS = ("0.1.0",)
DECLARED_OPTIONAL_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType(
    {"0.2.0": frozenset()}
)

_CLASSIFICATION_PRECEDENCE = (
    "blocked",
    "needs-decision",
    "sequencing-review",
    "parallel-candidate",
)
_REQUIRED_FIELDS = frozenset(
    {
        "contract_version",
        "planning_result_version",
        "evaluator_commit_sha",
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "supplied_node_ids",
        "graph_digest",
        "planning_result_digest",
        "cohort_summaries",
        "planning_scope",
        "execution_authorized",
        "created_at",
        "handoff_digest",
    }
)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FORBIDDEN_BRANCH_CHARS = frozenset("*?[")


@dataclass(frozen=True)
class HandoffCohort:
    node_ids: tuple[str, ...]
    classification: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_ids", tuple(self.node_ids))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


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
    created_at: str
    handoff_digest: str
    planning_scope: Literal["supplied-graph-only"] = field(
        default="supplied-graph-only", init=False
    )
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "supplied_node_ids", tuple(self.supplied_node_ids))
        object.__setattr__(self, "cohort_summaries", tuple(self.cohort_summaries))


class HandoffValidationOutcome(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    INVALID = "invalid"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True)
class HandoffValidationResult:
    outcome: HandoffValidationOutcome
    local_checks_passed: bool
    reason_codes: tuple[str, ...]
    freshness: Literal["not-evaluated"] = field(default="not-evaluated", init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def compute_graph_digest(graph: IssueBatchGraph) -> str:
    if not isinstance(graph, IssueBatchGraph):
        raise TypeError("graph must be an IssueBatchGraph")
    nodes = []
    for node in sorted(graph.nodes, key=lambda item: item.node_id):
        nodes.append(
            {
                "node_id": node.node_id,
                "readiness": node.readiness.value,
                "readiness_evidence": sorted(set(node.readiness_evidence)),
                "owner": node.owner,
                "source_of_truth": node.source_of_truth,
                "affected_paths": sorted(set(node.affected_paths)),
                "forbidden_paths": sorted(set(node.forbidden_paths)),
                "dependency_ids": sorted(set(node.dependency_ids)),
                "entity_id": node.entity_id,
                "provenance": sorted(set(node.provenance)),
            }
        )
    payload = {
        "nodes": nodes,
        "resolved_dependencies": [
            list(pair) for pair in sorted(set(graph.resolved_dependencies))
        ],
        "unresolved_dependencies": [
            list(pair) for pair in sorted(set(graph.unresolved_dependencies))
        ],
    }
    return _digest(payload)


def compute_planning_result_digest(result: BatchPlanningResult) -> str:
    if not isinstance(result, BatchPlanningResult):
        raise TypeError("result must be a BatchPlanningResult")
    payload = {
        "supplied_node_ids": list(result.supplied_node_ids),
        "overall_classification": result.overall_classification.value,
        "cohorts": [
            {
                "node_ids": list(cohort.node_ids),
                "classification": cohort.classification.value,
                "reason_codes": list(cohort.reason_codes),
                "dependency_pairs": [list(pair) for pair in cohort.dependency_pairs],
                "sequencing_pairs": [list(pair) for pair in cohort.sequencing_pairs],
            }
            for cohort in result.cohorts
        ],
        "batch_reason_codes": list(result.batch_reason_codes),
        "cycle_node_groups": [list(group) for group in result.cycle_node_groups],
        "planning_scope": result.planning_scope,
        "execution_authorized": result.execution_authorized,
    }
    return _digest(payload)


def _cohort_payload(value: HandoffCohort | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, HandoffCohort):
        node_ids = value.node_ids
        classification = value.classification
        reason_codes = value.reason_codes
    elif isinstance(value, Mapping):
        node_ids = value["node_ids"]
        classification = value["classification"]
        reason_codes = value["reason_codes"]
    else:
        raise TypeError("cohort_summaries must contain handoff cohorts or mappings")
    return {
        "node_ids": sorted(node_ids),
        "classification": classification,
        "reason_codes": sorted(reason_codes),
    }


def _handoff_mapping(handoff: SchedulerPlanningHandoff | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(handoff, SchedulerPlanningHandoff):
        return {
            "contract_version": handoff.contract_version,
            "planning_result_version": handoff.planning_result_version,
            "evaluator_commit_sha": handoff.evaluator_commit_sha,
            "repository": handoff.repository,
            "base_branch": handoff.base_branch,
            "evaluated_repository_sha": handoff.evaluated_repository_sha,
            "supplied_node_ids": list(handoff.supplied_node_ids),
            "graph_digest": handoff.graph_digest,
            "planning_result_digest": handoff.planning_result_digest,
            "cohort_summaries": list(handoff.cohort_summaries),
            "planning_scope": handoff.planning_scope,
            "execution_authorized": handoff.execution_authorized,
            "created_at": handoff.created_at,
            "handoff_digest": handoff.handoff_digest,
        }
    if isinstance(handoff, Mapping):
        return dict(handoff)
    raise TypeError("handoff must be a SchedulerPlanningHandoff or mapping")


def _canonical_handoff_payload(
    handoff: SchedulerPlanningHandoff | Mapping[str, Any],
    *,
    include_digest: bool,
) -> dict[str, Any]:
    raw = _handoff_mapping(handoff)
    payload = {key: raw[key] for key in _REQUIRED_FIELDS if key in raw}
    if "supplied_node_ids" in payload:
        payload["supplied_node_ids"] = sorted(payload["supplied_node_ids"])
    if "cohort_summaries" in payload:
        cohorts = [_cohort_payload(value) for value in payload["cohort_summaries"]]
        rank = {value: index for index, value in enumerate(_CLASSIFICATION_PRECEDENCE)}
        cohorts.sort(
            key=lambda item: (
                rank.get(item["classification"], len(rank)),
                item["node_ids"][0] if item["node_ids"] else "",
            )
        )
        payload["cohort_summaries"] = cohorts
    if not include_digest:
        payload.pop("handoff_digest", None)
    return payload


def compute_handoff_digest(
    handoff_without_digest: SchedulerPlanningHandoff | Mapping[str, Any],
) -> str:
    return _digest(_canonical_handoff_payload(handoff_without_digest, include_digest=False))


def serialize_scheduler_planning_handoff(handoff: SchedulerPlanningHandoff) -> bytes:
    if not isinstance(handoff, SchedulerPlanningHandoff):
        raise TypeError("handoff must be a SchedulerPlanningHandoff")
    return _canonical_bytes(_canonical_handoff_payload(handoff, include_digest=True))


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _valid_repository(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip() or value.count("/") != 1:
        return False
    owner, repo = value.split("/", 1)
    return bool(owner and repo)


def _valid_branch(value: object) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith("refs/") or any(char in value for char in _FORBIDDEN_BRANCH_CHARS):
        return False
    if ".." in value or "~" in value or "^" in value:
        return False
    return True


def _is_string_tuple(value: object, *, nonempty: bool = False) -> bool:
    if not isinstance(value, (tuple, list)):
        return False
    if nonempty and not value:
        return False
    return all(isinstance(item, str) and item != "" for item in value)


def _validate_cohorts(value: object) -> tuple[bool, tuple[str, ...]]:
    if not isinstance(value, (tuple, list)):
        return False, ()
    flattened: list[str] = []
    for item in value:
        if isinstance(item, HandoffCohort):
            node_ids = item.node_ids
            classification = item.classification
            reason_codes = item.reason_codes
        elif isinstance(item, Mapping):
            if set(item) != {"node_ids", "classification", "reason_codes"}:
                return False, ()
            node_ids = item.get("node_ids")
            classification = item.get("classification")
            reason_codes = item.get("reason_codes")
        else:
            return False, ()
        if not _is_string_tuple(node_ids, nonempty=True):
            return False, ()
        if tuple(node_ids) != tuple(sorted(node_ids)) or len(node_ids) != len(set(node_ids)):
            return False, ()
        if classification not in _CLASSIFICATION_PRECEDENCE:
            return False, ()
        if not _is_string_tuple(reason_codes):
            return False, ()
        if tuple(reason_codes) != tuple(sorted(reason_codes)):
            return False, ()
        flattened.extend(node_ids)
    return True, tuple(flattened)


def validate_scheduler_planning_handoff(
    handoff: SchedulerPlanningHandoff | Mapping[str, Any],
) -> HandoffValidationResult:
    if not isinstance(handoff, (SchedulerPlanningHandoff, Mapping)):
        return HandoffValidationResult(
            HandoffValidationOutcome.INVALID,
            False,
            ("malformed-field:handoff",),
        )

    try:
        raw = _handoff_mapping(handoff)
    except (TypeError, ValueError, KeyError):
        return HandoffValidationResult(
            HandoffValidationOutcome.INVALID,
            False,
            ("malformed-field:handoff",),
        )

    reasons: set[str] = set()
    contract_version = raw.get("contract_version")
    optional = DECLARED_OPTIONAL_FIELDS.get(contract_version, frozenset())
    for name in sorted(_REQUIRED_FIELDS - set(raw)):
        reasons.add(f"missing-field:{name}")
    if set(raw) - _REQUIRED_FIELDS - optional:
        reasons.add("unknown-field")

    if "contract_version" in raw:
        if not isinstance(contract_version, str) or not _SEMVER_RE.fullmatch(contract_version):
            reasons.add("malformed-field:contract_version")
        elif contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            reasons.add("unsupported-contract-version")

    planning_version = raw.get("planning_result_version")
    if "planning_result_version" in raw:
        if not isinstance(planning_version, str) or not _SEMVER_RE.fullmatch(planning_version):
            reasons.add("malformed-field:planning_result_version")
        elif planning_version not in SUPPORTED_PLANNING_RESULT_VERSIONS:
            reasons.add("unsupported-planning-result-version")

    checks = {
        "evaluator_commit_sha": lambda value: isinstance(value, str) and bool(_SHA40_RE.fullmatch(value)),
        "repository": _valid_repository,
        "base_branch": _valid_branch,
        "evaluated_repository_sha": lambda value: isinstance(value, str) and bool(_SHA40_RE.fullmatch(value)),
        "graph_digest": lambda value: isinstance(value, str) and bool(_SHA256_RE.fullmatch(value)),
        "planning_result_digest": lambda value: isinstance(value, str) and bool(_SHA256_RE.fullmatch(value)),
        "handoff_digest": lambda value: isinstance(value, str) and bool(_SHA256_RE.fullmatch(value)),
        "created_at": _valid_timestamp,
    }
    for name, check in checks.items():
        if name in raw and not check(raw[name]):
            reasons.add(f"malformed-field:{name}")

    supplied = raw.get("supplied_node_ids")
    supplied_valid = _is_string_tuple(supplied, nonempty=True)
    if supplied_valid:
        supplied_tuple = tuple(supplied)
        supplied_valid = (
            supplied_tuple == tuple(sorted(supplied_tuple))
            and len(supplied_tuple) == len(set(supplied_tuple))
        )
    if "supplied_node_ids" in raw and not supplied_valid:
        reasons.add("malformed-field:supplied_node_ids")

    cohorts_valid, flattened = _validate_cohorts(raw.get("cohort_summaries"))
    if "cohort_summaries" in raw and not cohorts_valid:
        reasons.add("malformed-field:cohort_summaries")

    if raw.get("planning_scope") != "supplied-graph-only":
        reasons.add("planning-scope-violation")
    if raw.get("execution_authorized") is not False:
        reasons.add("execution-authorized-violation")

    if supplied_valid and cohorts_valid:
        flattened_sorted = tuple(sorted(flattened))
        if (
            flattened_sorted != tuple(supplied)
            or len(flattened_sorted) != len(set(flattened_sorted))
        ):
            reasons.add("partial-graph-coverage")

    if not reasons and "handoff_digest" in raw:
        try:
            if compute_handoff_digest(raw) != raw["handoff_digest"]:
                reasons.add("handoff-digest-mismatch")
        except (TypeError, ValueError, KeyError):
            reasons.add("malformed-field:handoff")

    if reasons:
        return HandoffValidationResult(
            HandoffValidationOutcome.INVALID,
            False,
            tuple(sorted(reasons)),
        )
    return HandoffValidationResult(
        HandoffValidationOutcome.NEEDS_DECISION,
        True,
        ("external-revalidation-required",),
    )
