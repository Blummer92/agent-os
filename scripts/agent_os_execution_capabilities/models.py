from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal

from .reason_codes import is_approved_reason_code, normalize_reason_codes

CAPABILITY_EVIDENCE_SCHEMA_NAME = "agent-os-capability-evidence"
CAPABILITY_EVIDENCE_SCHEMA_VERSION = "1.0"
CAPABILITY_EVIDENCE_SERIALIZER_VERSION = "1.0"

_CAPABILITY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INDETERMINATE = "indeterminate"
    NOT_REQUIRED = "not-required"


class EvidenceStrength(str, Enum):
    DECLARED = "declared"
    OBSERVED = "observed"
    EXERCISED = "exercised"


class ExecutionDecision(str, Enum):
    PROCEED = "proceed"
    PROCEED_WITH_LIMITS = "proceed-with-limits"
    HANDOFF_REQUIRED = "handoff-required"
    NEEDS_DECISION = "needs-decision"


class RepositoryEvidenceType(str, Enum):
    BRANCH_HEAD = "branch-head"
    SYNTHETIC_PR_MERGE = "synthetic-pr-merge"
    BASE_SHA = "base-sha"
    UNCOMMITTED_WORKTREE = "uncommitted-worktree"


class WorktreeState(str, Enum):
    CLEAN = "clean"
    DIRTY = "dirty"
    UNTRACKED = "untracked"
    IGNORED = "ignored"
    DETACHED = "detached"
    SHALLOW = "shallow"
    UNRESOLVED_OPERATION = "unresolved-operation"
    UNCOMMITTED = "uncommitted"


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryIdentity:
    host: str
    owner: str
    repository: str
    repository_id: int | None = None
    is_fork: bool = False
    upstream_owner: str | None = None
    upstream_repository: str | None = None
    upstream_repository_id: int | None = None
    default_branch: str = "main"

    def __post_init__(self) -> None:
        for name in ("host", "owner", "repository", "default_branch"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TypeError(f"{name} must be a non-empty string")
        if not isinstance(self.is_fork, bool):
            raise TypeError("is_fork must be boolean")
        if self.repository_id is not None and (
            not isinstance(self.repository_id, int) or isinstance(self.repository_id, bool)
        ):
            raise TypeError("repository_id must be an integer or None")
        if self.upstream_repository_id is not None and (
            not isinstance(self.upstream_repository_id, int)
            or isinstance(self.upstream_repository_id, bool)
        ):
            raise TypeError("upstream_repository_id must be an integer or None")
        object.__setattr__(self, "host", self.host.strip().lower())
        object.__setattr__(self, "owner", self.owner.strip().lower())
        object.__setattr__(self, "repository", self.repository.strip().lower())
        object.__setattr__(self, "default_branch", self.default_branch.strip())
        if self.is_fork:
            if not self.upstream_owner or not self.upstream_repository:
                raise ValueError("fork identities require upstream owner and repository")
            object.__setattr__(self, "upstream_owner", self.upstream_owner.strip().lower())
            object.__setattr__(
                self, "upstream_repository", self.upstream_repository.strip().lower()
            )
        elif any(
            value is not None
            for value in (
                self.upstream_owner,
                self.upstream_repository,
                self.upstream_repository_id,
            )
        ):
            raise ValueError("non-fork identities cannot declare an upstream")

    @property
    def canonical_key(self) -> tuple[object, ...]:
        return (
            self.host,
            self.owner,
            self.repository,
            self.repository_id,
            self.is_fork,
            self.upstream_owner,
            self.upstream_repository,
            self.upstream_repository_id,
            self.default_branch,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityEvidence:
    capability_id: str
    status: CapabilityStatus
    evidence_strength: EvidenceStrength
    operation_scope: str
    repository_scope: str | None = None
    ref_scope: str | None = None
    sha_scope: str | None = None
    principal_type: str | None = None
    runtime_fingerprint: str | None = None
    freshness_boundary: str | None = None
    reason_code: str = "adapter.evidence-unproven"
    reason: str = ""
    required_handoff: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not _CAPABILITY_ID_RE.fullmatch(
            self.capability_id
        ):
            raise ValueError("capability_id must be lowercase kebab-case")
        if not isinstance(self.status, CapabilityStatus):
            raise TypeError("status must be a CapabilityStatus")
        if not isinstance(self.evidence_strength, EvidenceStrength):
            raise TypeError("evidence_strength must be an EvidenceStrength")
        if not isinstance(self.operation_scope, str) or not self.operation_scope.strip():
            raise TypeError("operation_scope must be a non-empty string")
        for name in (
            "repository_scope",
            "ref_scope",
            "principal_type",
            "runtime_fingerprint",
            "freshness_boundary",
            "required_handoff",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise TypeError(f"{name} must be a non-empty string or None")
        if self.sha_scope is not None and (
            not isinstance(self.sha_scope, str) or not _SHA40_RE.fullmatch(self.sha_scope)
        ):
            raise ValueError("sha_scope must be a full lowercase commit SHA or None")
        if not is_approved_reason_code(self.reason_code):
            raise ValueError("reason_code must use the bounded GEX vocabulary")
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityEvidenceEnvelope:
    schema_name: str
    evidence_schema_version: str
    serializer_version: str
    producer_adapter: str
    producer_adapter_version: str
    correlation_id: str
    environment_class: str
    repository_identity: RepositoryIdentity | None
    base_ref: str | None
    head_ref: str | None
    observed_sha: str | None
    contract_fingerprint: str | None
    capabilities: tuple[CapabilityEvidence, ...]
    invalidation_reasons: tuple[str, ...]
    handoffs: tuple[str, ...]
    decision: ExecutionDecision
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != CAPABILITY_EVIDENCE_SCHEMA_NAME:
            raise ValueError("schema_name is unsupported")
        if not isinstance(self.evidence_schema_version, str) or not _VERSION_RE.fullmatch(
            self.evidence_schema_version
        ):
            raise ValueError("evidence_schema_version must use MAJOR.MINOR")
        if not isinstance(self.serializer_version, str) or not _VERSION_RE.fullmatch(
            self.serializer_version
        ):
            raise ValueError("serializer_version must use MAJOR.MINOR")
        for name in (
            "producer_adapter",
            "producer_adapter_version",
            "correlation_id",
            "environment_class",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TypeError(f"{name} must be a non-empty string")
        if self.repository_identity is not None and not isinstance(
            self.repository_identity, RepositoryIdentity
        ):
            raise TypeError("repository_identity must be RepositoryIdentity or None")
        for name in ("base_ref", "head_ref"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise TypeError(f"{name} must be a non-empty string or None")
        if self.observed_sha is not None and (
            not isinstance(self.observed_sha, str)
            or not _SHA40_RE.fullmatch(self.observed_sha)
        ):
            raise ValueError("observed_sha must be a full lowercase commit SHA or None")
        if self.contract_fingerprint is not None and (
            not isinstance(self.contract_fingerprint, str)
            or not _SHA256_RE.fullmatch(self.contract_fingerprint)
        ):
            raise ValueError("contract_fingerprint must be a SHA-256 hex digest or None")
        if not isinstance(self.decision, ExecutionDecision):
            raise TypeError("decision must be an ExecutionDecision")
        capabilities = tuple(sorted(tuple(self.capabilities), key=lambda item: item.capability_id))
        if not all(isinstance(item, CapabilityEvidence) for item in capabilities):
            raise TypeError("capabilities must contain CapabilityEvidence values")
        ids = tuple(item.capability_id for item in capabilities)
        if len(ids) != len(set(ids)):
            raise ValueError("capability IDs must be unique")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(
            self, "invalidation_reasons", normalize_reason_codes(self.invalidation_reasons)
        )
        object.__setattr__(self, "handoffs", _normalize_strings(self.handoffs, "handoffs"))


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryStateEvidence:
    schema_name: str
    evidence_schema_version: str
    producer_adapter: str
    producer_adapter_version: str
    correlation_id: str
    repository_identity: RepositoryIdentity
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    requested_ref: str | None
    requested_sha: str | None
    observed_sha: str
    tested_sha: str | None
    pushed_sha: str | None
    proposed_pr_sha: str | None
    synthetic_merge_sha: str | None
    external_build_sha: str | None
    evidence_type: RepositoryEvidenceType
    contract_fingerprint: str
    worktree_state: tuple[WorktreeState, ...]
    observed_at: str
    freshness_boundary: str
    evidence_id: str = ""
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != CAPABILITY_EVIDENCE_SCHEMA_NAME:
            raise ValueError("schema_name is unsupported")
        if not isinstance(self.evidence_schema_version, str) or not _VERSION_RE.fullmatch(
            self.evidence_schema_version
        ):
            raise ValueError("evidence_schema_version must use MAJOR.MINOR")
        if not isinstance(self.repository_identity, RepositoryIdentity):
            raise TypeError("repository_identity must be a RepositoryIdentity")
        if not isinstance(self.evidence_type, RepositoryEvidenceType):
            raise TypeError("evidence_type must be a RepositoryEvidenceType")
        for name in (
            "producer_adapter",
            "producer_adapter_version",
            "correlation_id",
            "base_ref",
            "head_ref",
            "observed_at",
            "freshness_boundary",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TypeError(f"{name} must be a non-empty string")
        for name in ("requested_ref",):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise TypeError(f"{name} must be a non-empty string or None")
        for name in (
            "base_sha",
            "head_sha",
            "observed_sha",
            "tested_sha",
            "requested_sha",
            "pushed_sha",
            "proposed_pr_sha",
            "synthetic_merge_sha",
            "external_build_sha",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not _SHA40_RE.fullmatch(value)
            ):
                raise ValueError(f"{name} must be a full lowercase commit SHA or None")
        if not isinstance(self.contract_fingerprint, str) or not _SHA256_RE.fullmatch(
            self.contract_fingerprint
        ):
            raise ValueError("contract_fingerprint must be a SHA-256 hex digest")
        states = tuple(sorted(set(self.worktree_state), key=lambda item: item.value))
        if not states or not all(isinstance(item, WorktreeState) for item in states):
            raise TypeError("worktree_state must contain WorktreeState values")
        if WorktreeState.CLEAN in states and len(states) != 1:
            raise ValueError("clean worktree state cannot be combined with findings")
        object.__setattr__(self, "worktree_state", states)
        computed_id = repository_state_evidence_id(self)
        if self.evidence_id and self.evidence_id != computed_id:
            raise ValueError("evidence_id does not match repository-state content")
        object.__setattr__(self, "evidence_id", computed_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryStateValidationResult:
    decision: ExecutionDecision
    valid: bool
    evidence_id: str
    tested_sha: str | None
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    execution_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ExecutionDecision):
            raise TypeError("decision must be an ExecutionDecision")
        if not isinstance(self.valid, bool):
            raise TypeError("valid must be boolean")
        if not isinstance(self.evidence_id, str):
            raise TypeError("evidence_id must be a string")
        if self.tested_sha is not None and (
            not isinstance(self.tested_sha, str) or not _SHA40_RE.fullmatch(self.tested_sha)
        ):
            raise ValueError("tested_sha must be a full lowercase commit SHA or None")
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))
        object.__setattr__(self, "details", tuple(str(item) for item in self.details))


def repository_state_evidence_payload(value: RepositoryStateEvidence) -> dict[str, Any]:
    return {
        "schema_name": value.schema_name,
        "evidence_schema_version": value.evidence_schema_version,
        "producer_adapter": value.producer_adapter,
        "producer_adapter_version": value.producer_adapter_version,
        "correlation_id": value.correlation_id,
        "repository_identity": _canonicalize(asdict(value.repository_identity)),
        "base_ref": value.base_ref,
        "base_sha": value.base_sha,
        "head_ref": value.head_ref,
        "head_sha": value.head_sha,
        "requested_ref": value.requested_ref,
        "requested_sha": value.requested_sha,
        "observed_sha": value.observed_sha,
        "tested_sha": value.tested_sha,
        "pushed_sha": value.pushed_sha,
        "proposed_pr_sha": value.proposed_pr_sha,
        "synthetic_merge_sha": value.synthetic_merge_sha,
        "external_build_sha": value.external_build_sha,
        "evidence_type": value.evidence_type.value,
        "contract_fingerprint": value.contract_fingerprint,
        "worktree_state": [item.value for item in value.worktree_state],
        "observed_at": value.observed_at,
        "freshness_boundary": value.freshness_boundary,
        "execution_authorized": False,
    }


def repository_state_evidence_id(value: RepositoryStateEvidence) -> str:
    payload = json.dumps(
        repository_state_evidence_payload(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_strings(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, (tuple, list, set, frozenset)):
        raise TypeError(f"{name} must be a collection of strings")
    normalized = tuple(sorted(set(values)))
    if not all(isinstance(item, str) and item for item in normalized):
        raise TypeError(f"{name} must contain non-empty strings")
    return normalized


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonicalize(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value
