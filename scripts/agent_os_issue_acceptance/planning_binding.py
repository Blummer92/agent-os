"""Canonical post-planning binding evidence for the Agent OS candidate pipeline.

The binding joins one exact IssuePlan current-state identity to the repository
context and Scheduler planning artifacts produced after the IssuePlan identity
was fixed. It is pure-local, immutable, deterministic, and non-authorizing.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .issueplan_current_state import IssuePlanCurrentStateEvidence
from .scheduler_handoff import SchedulerPlanningHandoff

PLANNING_BINDING_SCHEMA_VERSION = "1.0"

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_ISSUEPLAN_ID_RE = re.compile(r"^issueplan-current-state:[0-9a-f]{64}$")
_BINDING_ID_RE = re.compile(r"^planning-binding:[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FORBIDDEN_BRANCH_CHARS = frozenset("*?[")

_BINDING_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "binding_id",
        "issueplan_current_state_evidence_id",
        "repository",
        "base_branch",
        "evaluated_repository_sha",
        "implementation_contract_fingerprint",
        "handoff_contract_version",
        "planning_result_version",
        "graph_digest",
        "planning_result_digest",
        "handoff_digest",
        "supplied_node_ids",
        "created_at",
        "execution_authorized",
        "side_effects_performed",
    }
)


@dataclass(frozen=True, slots=True)
class PlanningBindingEvidence:
    """Immutable attestation binding one IssuePlan to post-planning artifacts."""

    schema_version: str
    binding_id: str
    issueplan_current_state_evidence_id: str
    repository: str
    base_branch: str
    evaluated_repository_sha: str
    implementation_contract_fingerprint: str
    handoff_contract_version: str
    planning_result_version: str
    graph_digest: str
    planning_result_digest: str
    handoff_digest: str
    supplied_node_ids: tuple[str, ...]
    created_at: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != PLANNING_BINDING_SCHEMA_VERSION:
            raise ValueError("unsupported planning binding schema version")
        if not isinstance(self.binding_id, str) or not _BINDING_ID_RE.fullmatch(
            self.binding_id
        ):
            raise ValueError("binding_id is malformed")
        if not isinstance(
            self.issueplan_current_state_evidence_id, str
        ) or not _ISSUEPLAN_ID_RE.fullmatch(
            self.issueplan_current_state_evidence_id
        ):
            raise ValueError("issueplan_current_state_evidence_id is malformed")
        _require_repository(self.repository)
        _require_branch(self.base_branch)
        _require_sha40(self.evaluated_repository_sha, "evaluated_repository_sha")
        _require_sha256(
            self.implementation_contract_fingerprint,
            "implementation_contract_fingerprint",
        )
        _require_semver(self.handoff_contract_version, "handoff_contract_version")
        _require_semver(self.planning_result_version, "planning_result_version")
        _require_sha256(self.graph_digest, "graph_digest")
        _require_sha256(self.planning_result_digest, "planning_result_digest")
        _require_sha256(self.handoff_digest, "handoff_digest")
        node_ids = _require_node_ids(self.supplied_node_ids)
        _require_timestamp(self.created_at)
        object.__setattr__(self, "supplied_node_ids", node_ids)

        expected_id = "planning-binding:" + compute_planning_binding_fingerprint(self)
        if self.binding_id != expected_id:
            raise ValueError("binding_id does not match planning binding content")


def build_planning_binding_evidence(
    issueplan_current_state_evidence: IssuePlanCurrentStateEvidence,
    handoff: SchedulerPlanningHandoff,
    *,
    created_at: str,
) -> PlanningBindingEvidence:
    """Build one canonical binding from exact caller-supplied evidence objects."""

    if not isinstance(
        issueplan_current_state_evidence, IssuePlanCurrentStateEvidence
    ):
        raise TypeError(
            "issueplan_current_state_evidence must be an "
            "IssuePlanCurrentStateEvidence"
        )
    if not isinstance(handoff, SchedulerPlanningHandoff):
        raise TypeError("handoff must be a SchedulerPlanningHandoff")

    issueplan = issueplan_current_state_evidence
    required_context = {
        "repository": issueplan.repository,
        "base_branch": issueplan.base_branch,
        "evaluated_repository_sha": issueplan.evaluated_repository_sha,
        "implementation_contract_fingerprint": (
            issueplan.implementation_contract_fingerprint
        ),
    }
    missing = sorted(name for name, value in required_context.items() if value is None)
    if missing:
        raise ValueError(
            "IssuePlan current-state evidence is missing binding field(s): "
            + ", ".join(missing)
        )

    if issueplan.repository != handoff.repository:
        raise ValueError("repository binding mismatch")
    if issueplan.base_branch != handoff.base_branch:
        raise ValueError("base_branch binding mismatch")
    if issueplan.evaluated_repository_sha != handoff.evaluated_repository_sha:
        raise ValueError("evaluated_repository_sha binding mismatch")

    values = {
        "schema_version": PLANNING_BINDING_SCHEMA_VERSION,
        "issueplan_current_state_evidence_id": issueplan.evidence_id,
        "repository": issueplan.repository,
        "base_branch": issueplan.base_branch,
        "evaluated_repository_sha": issueplan.evaluated_repository_sha,
        "implementation_contract_fingerprint": (
            issueplan.implementation_contract_fingerprint
        ),
        "handoff_contract_version": handoff.contract_version,
        "planning_result_version": handoff.planning_result_version,
        "graph_digest": handoff.graph_digest,
        "planning_result_digest": handoff.planning_result_digest,
        "handoff_digest": handoff.handoff_digest,
        "supplied_node_ids": tuple(handoff.supplied_node_ids),
        "created_at": created_at,
    }
    fingerprint = _fingerprint_from_values(values)
    return PlanningBindingEvidence(
        binding_id=f"planning-binding:{fingerprint}",
        **values,
    )


def compute_planning_binding_fingerprint(evidence: PlanningBindingEvidence) -> str:
    """Return the SHA-256 semantic fingerprint for one binding evidence object."""

    if not isinstance(evidence, PlanningBindingEvidence):
        raise TypeError("evidence must be a PlanningBindingEvidence")
    return _fingerprint_from_values(
        {
            "schema_version": evidence.schema_version,
            "issueplan_current_state_evidence_id": (
                evidence.issueplan_current_state_evidence_id
            ),
            "repository": evidence.repository,
            "base_branch": evidence.base_branch,
            "evaluated_repository_sha": evidence.evaluated_repository_sha,
            "implementation_contract_fingerprint": (
                evidence.implementation_contract_fingerprint
            ),
            "handoff_contract_version": evidence.handoff_contract_version,
            "planning_result_version": evidence.planning_result_version,
            "graph_digest": evidence.graph_digest,
            "planning_result_digest": evidence.planning_result_digest,
            "handoff_digest": evidence.handoff_digest,
            "supplied_node_ids": evidence.supplied_node_ids,
        }
    )


def serialize_planning_binding_evidence(evidence: PlanningBindingEvidence) -> bytes:
    """Serialize one binding to byte-stable canonical UTF-8 JSON."""

    if not isinstance(evidence, PlanningBindingEvidence):
        raise TypeError("evidence must be a PlanningBindingEvidence")
    return _canonical_bytes(_binding_payload(evidence))


def reconstruct_planning_binding_evidence(
    payload: bytes | str | Mapping[str, Any],
) -> PlanningBindingEvidence:
    """Strictly reconstruct one binding, rejecting schema or identity drift."""

    raw = _decode_payload(payload)
    _require_exact_keys(raw)
    if raw["execution_authorized"] is not False:
        raise ValueError("execution_authorized must be false")
    if raw["side_effects_performed"] is not False:
        raise ValueError("side_effects_performed must be false")
    supplied_node_ids = raw["supplied_node_ids"]
    if not isinstance(supplied_node_ids, list):
        raise ValueError("supplied_node_ids must be a list of strings")
    if not all(isinstance(item, str) for item in supplied_node_ids):
        raise ValueError("supplied_node_ids must contain only strings")

    return PlanningBindingEvidence(
        schema_version=raw["schema_version"],
        binding_id=raw["binding_id"],
        issueplan_current_state_evidence_id=raw[
            "issueplan_current_state_evidence_id"
        ],
        repository=raw["repository"],
        base_branch=raw["base_branch"],
        evaluated_repository_sha=raw["evaluated_repository_sha"],
        implementation_contract_fingerprint=raw[
            "implementation_contract_fingerprint"
        ],
        handoff_contract_version=raw["handoff_contract_version"],
        planning_result_version=raw["planning_result_version"],
        graph_digest=raw["graph_digest"],
        planning_result_digest=raw["planning_result_digest"],
        handoff_digest=raw["handoff_digest"],
        supplied_node_ids=tuple(supplied_node_ids),
        created_at=raw["created_at"],
    )


def _fingerprint_from_values(values: Mapping[str, Any]) -> str:
    semantic_payload = {
        "schema_version": values["schema_version"],
        "issueplan_current_state_evidence_id": values[
            "issueplan_current_state_evidence_id"
        ],
        "repository": values["repository"],
        "base_branch": values["base_branch"],
        "evaluated_repository_sha": values["evaluated_repository_sha"],
        "implementation_contract_fingerprint": values[
            "implementation_contract_fingerprint"
        ],
        "handoff_contract_version": values["handoff_contract_version"],
        "planning_result_version": values["planning_result_version"],
        "graph_digest": values["graph_digest"],
        "planning_result_digest": values["planning_result_digest"],
        "handoff_digest": values["handoff_digest"],
        "supplied_node_ids": list(_require_node_ids(values["supplied_node_ids"])),
    }
    return hashlib.sha256(_canonical_bytes(semantic_payload)).hexdigest()


def _binding_payload(evidence: PlanningBindingEvidence) -> dict[str, Any]:
    return {
        "schema_version": evidence.schema_version,
        "binding_id": evidence.binding_id,
        "issueplan_current_state_evidence_id": (
            evidence.issueplan_current_state_evidence_id
        ),
        "repository": evidence.repository,
        "base_branch": evidence.base_branch,
        "evaluated_repository_sha": evidence.evaluated_repository_sha,
        "implementation_contract_fingerprint": (
            evidence.implementation_contract_fingerprint
        ),
        "handoff_contract_version": evidence.handoff_contract_version,
        "planning_result_version": evidence.planning_result_version,
        "graph_digest": evidence.graph_digest,
        "planning_result_digest": evidence.planning_result_digest,
        "handoff_digest": evidence.handoff_digest,
        "supplied_node_ids": list(evidence.supplied_node_ids),
        "created_at": evidence.created_at,
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode_payload(payload: bytes | str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload, bytes):
        try:
            raw: object = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "planning binding payload must be canonical UTF-8 JSON"
            ) from error
    elif isinstance(payload, str):
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("planning binding payload must be JSON") from error
    elif isinstance(payload, Mapping):
        raw = dict(payload)
    else:
        raise TypeError("payload must be bytes, text, or a mapping")
    if not isinstance(raw, Mapping):
        raise ValueError("planning binding payload must be a mapping")
    return raw


def _require_exact_keys(payload: Mapping[str, Any]) -> None:
    supplied = set(payload)
    missing = sorted(_BINDING_PAYLOAD_KEYS - supplied)
    if missing:
        raise ValueError(
            "planning binding payload is missing field(s): " + ", ".join(missing)
        )
    unsupported = sorted(supplied - _BINDING_PAYLOAD_KEYS)
    if unsupported:
        raise ValueError(
            "planning binding payload has unsupported field(s): "
            + ", ".join(unsupported)
        )


def _require_repository(value: object) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or value.count("/") != 1
    ):
        raise ValueError("repository must be owner/repository")
    owner, repository = value.split("/", 1)
    if not owner or not repository or _has_control_character(value):
        raise ValueError("repository must be owner/repository")
    return value


def _require_branch(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("base_branch is malformed")
    if (
        value.startswith("refs/")
        or any(character in value for character in _FORBIDDEN_BRANCH_CHARS)
        or any(token in value for token in ("..", "~", "^"))
        or _has_control_character(value)
    ):
        raise ValueError("base_branch is malformed")
    return value


def _require_sha40(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA40_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a 40-character lowercase SHA")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return value


def _require_semver(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SEMVER_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be semantic version text")
    return value


def _require_node_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError("supplied_node_ids must be a sequence of strings")
    node_ids = tuple(value)
    if not node_ids:
        raise ValueError("supplied_node_ids must not be empty")
    if not all(
        isinstance(item, str)
        and bool(item)
        and item == item.strip()
        and not _has_control_character(item)
        for item in node_ids
    ):
        raise ValueError("supplied_node_ids must contain non-empty strings")
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("supplied_node_ids must not contain duplicates")
    if node_ids != tuple(sorted(node_ids)):
        raise ValueError("supplied_node_ids must be sorted")
    return node_ids


def _require_timestamp(value: object) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError("created_at must be a UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError("created_at must be a UTC timestamp") from error
    return value


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)
