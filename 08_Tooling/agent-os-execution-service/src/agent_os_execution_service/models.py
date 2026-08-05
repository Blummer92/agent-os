from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from scripts.agent_os_execution_capabilities import RepositoryIdentity, RepositoryStateEvidence

EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION = "1.0"
EXECUTION_SERVICE_RESULT_SCHEMA_VERSION = "1.0"
EXECUTION_SERVICE_FINGERPRINT_VERSION = "1.0"
EXECUTION_SERVICE_VERSION = "0.4.0"

MAX_PATH_COUNT = 256
MAX_PATH_LENGTH = 512
MAX_INSPECTED_FILE_COUNT = 10_000
MAX_INSPECTED_BYTE_COUNT = 50_000_000
MAX_TEXT_LENGTH = 4_096
MAX_EVIDENCE_ITEMS = 64
MAX_EVIDENCE_ITEM_BYTES = 4_096
MAX_EVIDENCE_TOTAL_BYTES = 32_768
MAX_REASON_COUNT = 10

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$", re.ASCII)
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", re.ASCII)
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$", re.ASCII)
_EVIDENCE_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$", re.ASCII)
_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", re.ASCII)
_FORBIDDEN_REF_CHARS = frozenset(" ~^:?*[\\")


class ExecutionServiceCapability(str, Enum):
    INSPECT_REPOSITORY = "inspect_repository"
    VERIFY_REPOSITORY_STATE = "verify_repository_state"


class ExecutionServiceStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class ExecutionServiceReason(str, Enum):
    ACCEPTED = "accepted"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    MALFORMED_REQUEST = "malformed_request"
    EXPIRED_REQUEST = "expired_request"
    IDENTITY_MISMATCH = "identity_mismatch"
    STALE_REPOSITORY_STATE = "stale_repository_state"
    CAPABILITY_NOT_AUTHORIZED = "capability_not_authorized"
    INSPECTION_LIMIT_EXCEEDED = "inspection_limit_exceeded"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    SERVICE_UNAVAILABLE = "service_unavailable"


class EvidenceVisibilityPolicy(str, Enum):
    PUBLIC_SUMMARY_ONLY = "public-summary-only"
    INCLUDE_PRIVATE = "include-private"


class ExecutionServiceInvalidationCondition(str, Enum):
    REPOSITORY_IDENTITY_CHANGED = "repository-identity-changed"
    REQUESTED_REF_CHANGED = "requested-ref-changed"
    EXPECTED_SHA_CHANGED = "expected-sha-changed"
    REQUEST_EXPIRED = "request-expired"
    INSPECTION_LIMIT_EXCEEDED = "inspection-limit-exceeded"


@dataclass(frozen=True, slots=True, kw_only=True)
class PrivateEvidence:
    label: str
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_exact_str("label", self.label)
        _require_exact_str("value", self.value)
        if not _EVIDENCE_LABEL_RE.fullmatch(self.label):
            raise ValueError("label must use bounded lowercase ASCII syntax")
        if len(self.value) > MAX_TEXT_LENGTH:
            raise ValueError("evidence value exceeds the text ceiling")
        if len(self.value.encode("utf-8")) > MAX_EVIDENCE_ITEM_BYTES:
            raise ValueError("evidence value exceeds the byte ceiling")


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectedFileEvidence:
    path: str
    size_bytes: int
    sha256: str
    summary: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        _validate_path(self.path)
        _require_nonnegative_int("size_bytes", self.size_bytes)
        if self.size_bytes > MAX_INSPECTED_BYTE_COUNT:
            raise ValueError("file size exceeds the service byte ceiling")
        _require_exact_str("sha256", self.sha256)
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ValueError("sha256 must be a lowercase SHA-256 digest")
        _require_exact_str("summary", self.summary)
        if len(self.summary) > MAX_TEXT_LENGTH:
            raise ValueError("summary exceeds the text ceiling")


@dataclass(frozen=True, slots=True, kw_only=True)
class RepositoryInspectionObservation:
    repository_identity: RepositoryIdentity
    observed_ref: str
    observed_sha: str
    files: tuple[InspectedFileEvidence, ...]
    declared_file_count: int
    declared_byte_count: int
    private_evidence: tuple[PrivateEvidence, ...] = field(default=(), repr=False)
    repository_state_evidence: RepositoryStateEvidence | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_repository_identity(self.repository_identity)
        _validate_ref("observed_ref", self.observed_ref)
        _validate_sha40("observed_sha", self.observed_sha)
        _require_exact_tuple("files", self.files)
        if len(self.files) > MAX_INSPECTED_FILE_COUNT:
            raise ValueError("files exceed the service count ceiling")
        if not all(type(item) is InspectedFileEvidence for item in self.files):
            raise TypeError("files must contain exact InspectedFileEvidence values")
        paths = tuple(item.path for item in self.files)
        if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
            raise ValueError("files must be path-sorted and unique")
        _require_nonnegative_int("declared_file_count", self.declared_file_count)
        _require_nonnegative_int("declared_byte_count", self.declared_byte_count)
        _require_exact_tuple("private_evidence", self.private_evidence)
        if len(self.private_evidence) > MAX_EVIDENCE_ITEMS:
            raise ValueError("private evidence exceeds the item ceiling")
        if not all(type(item) is PrivateEvidence for item in self.private_evidence):
            raise TypeError("private_evidence must contain exact PrivateEvidence values")
        total_private_bytes = sum(len(item.value.encode("utf-8")) for item in self.private_evidence)
        if total_private_bytes > MAX_EVIDENCE_TOTAL_BYTES:
            raise ValueError("private evidence exceeds the total byte ceiling")
        if self.repository_state_evidence is not None and type(self.repository_state_evidence) is not RepositoryStateEvidence:
            raise TypeError("repository_state_evidence must be canonical RepositoryStateEvidence or None")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionServiceRequest:
    schema_version: str
    request_id: str
    request_revision: int
    created_at: str
    expires_at: str
    repository_identity: RepositoryIdentity
    issue_or_handoff_identity: str
    canonical_owner: str
    requesting_actor: str
    capability: ExecutionServiceCapability
    base_branch: str
    base_sha: str
    requested_ref: str
    expected_sha: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    inspected_file_count_limit: int
    inspected_byte_limit: int
    evidence_visibility_policy: EvidenceVisibilityPolicy
    invalidation_conditions: tuple[ExecutionServiceInvalidationCondition, ...]
    request_fingerprint: str = ""

    def __post_init__(self) -> None:
        _require_exact_str("schema_version", self.schema_version)
        if not _VERSION_RE.fullmatch(self.schema_version):
            raise ValueError("schema_version must use MAJOR.MINOR")
        _validate_identifier("request_id", self.request_id)
        _require_positive_int("request_revision", self.request_revision)
        parse_canonical_utc(self.created_at)
        parse_canonical_utc(self.expires_at)
        _validate_repository_identity(self.repository_identity)
        _validate_identifier("issue_or_handoff_identity", self.issue_or_handoff_identity)
        _validate_owner("canonical_owner", self.canonical_owner)
        _validate_owner("requesting_actor", self.requesting_actor)
        if type(self.capability) is not ExecutionServiceCapability:
            raise TypeError("capability must be ExecutionServiceCapability")
        _validate_ref("base_branch", self.base_branch)
        _validate_sha40("base_sha", self.base_sha)
        _validate_ref("requested_ref", self.requested_ref)
        _validate_sha40("expected_sha", self.expected_sha)
        _validate_path_tuple("allowed_paths", self.allowed_paths, require_nonempty=True)
        _validate_path_tuple("forbidden_paths", self.forbidden_paths, require_nonempty=False)
        if any(paths_overlap(a, b) for a in self.allowed_paths for b in self.forbidden_paths):
            raise ValueError("allowed_paths and forbidden_paths must not overlap")
        _require_positive_int("inspected_file_count_limit", self.inspected_file_count_limit)
        _require_positive_int("inspected_byte_limit", self.inspected_byte_limit)
        if self.inspected_file_count_limit > MAX_INSPECTED_FILE_COUNT:
            raise ValueError("inspected_file_count_limit exceeds the service ceiling")
        if self.inspected_byte_limit > MAX_INSPECTED_BYTE_COUNT:
            raise ValueError("inspected_byte_limit exceeds the service ceiling")
        if type(self.evidence_visibility_policy) is not EvidenceVisibilityPolicy:
            raise TypeError("evidence_visibility_policy must be EvidenceVisibilityPolicy")
        _require_exact_tuple("invalidation_conditions", self.invalidation_conditions)
        if not self.invalidation_conditions:
            raise ValueError("invalidation_conditions must not be empty")
        if not all(type(item) is ExecutionServiceInvalidationCondition for item in self.invalidation_conditions):
            raise TypeError("invalidation_conditions must contain exact enum values")
        ordered_conditions = tuple(sorted(self.invalidation_conditions, key=lambda item: item.value))
        if ordered_conditions != self.invalidation_conditions or len(set(self.invalidation_conditions)) != len(self.invalidation_conditions):
            raise ValueError("invalidation_conditions must be sorted and unique")
        computed = execution_service_request_fingerprint(self)
        if self.request_fingerprint:
            _validate_sha256("request_fingerprint", self.request_fingerprint)
            if self.request_fingerprint != computed:
                raise ValueError("request_fingerprint does not match request content")
        object.__setattr__(self, "request_fingerprint", computed)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionServiceResult:
    schema_version: str
    request_id: str
    request_revision: int
    request_fingerprint: str
    evaluated_at: str
    service_version: str
    status: ExecutionServiceStatus
    reasons: tuple[ExecutionServiceReason, ...]
    repository_identity: RepositoryIdentity | None
    requested_ref: str | None
    expected_sha: str | None
    observed_ref: str | None
    observed_sha: str | None
    inspected_file_count: int
    inspected_byte_count: int
    private_evidence: tuple[PrivateEvidence, ...] = field(default=(), repr=False)
    public_summary: str = ""
    result_fingerprint: str = ""
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_exact_str("schema_version", self.schema_version)
        if self.schema_version != EXECUTION_SERVICE_RESULT_SCHEMA_VERSION:
            raise ValueError("schema_version is unsupported")
        _validate_identifier("request_id", self.request_id)
        _require_nonnegative_int("request_revision", self.request_revision)
        _validate_sha256("request_fingerprint", self.request_fingerprint)
        parse_canonical_utc(self.evaluated_at)
        _require_exact_str("service_version", self.service_version)
        if type(self.status) is not ExecutionServiceStatus:
            raise TypeError("status must be ExecutionServiceStatus")
        _require_exact_tuple("reasons", self.reasons)
        if not self.reasons or len(self.reasons) > MAX_REASON_COUNT:
            raise ValueError("reasons must be finite and non-empty")
        if not all(type(item) is ExecutionServiceReason for item in self.reasons):
            raise TypeError("reasons must contain exact ExecutionServiceReason values")
        ordered = tuple(sorted(set(self.reasons), key=lambda item: item.value))
        if ordered != self.reasons:
            raise ValueError("reasons must be sorted and deduplicated")
        if self.status is ExecutionServiceStatus.ACCEPTED:
            if self.reasons != (ExecutionServiceReason.ACCEPTED,):
                raise ValueError("accepted results require exactly the accepted reason")
        elif ExecutionServiceReason.ACCEPTED in self.reasons:
            raise ValueError("non-accepted results cannot include accepted")
        if self.repository_identity is not None:
            _validate_repository_identity(self.repository_identity)
        for name, value in (("requested_ref", self.requested_ref), ("observed_ref", self.observed_ref)):
            if value is not None:
                _validate_ref(name, value)
        for name, value in (("expected_sha", self.expected_sha), ("observed_sha", self.observed_sha)):
            if value is not None:
                _validate_sha40(name, value)
        _require_nonnegative_int("inspected_file_count", self.inspected_file_count)
        _require_nonnegative_int("inspected_byte_count", self.inspected_byte_count)
        if self.inspected_file_count > MAX_INSPECTED_FILE_COUNT or self.inspected_byte_count > MAX_INSPECTED_BYTE_COUNT:
            raise ValueError("inspected counts exceed service ceilings")
        _require_exact_tuple("private_evidence", self.private_evidence)
        if not all(type(item) is PrivateEvidence for item in self.private_evidence):
            raise TypeError("private_evidence must contain exact PrivateEvidence values")
        if len(self.private_evidence) > MAX_EVIDENCE_ITEMS:
            raise ValueError("private_evidence exceeds the item ceiling")
        if sum(len(item.value.encode("utf-8")) for item in self.private_evidence) > MAX_EVIDENCE_TOTAL_BYTES:
            raise ValueError("private_evidence exceeds the total byte ceiling")
        _require_exact_str("public_summary", self.public_summary)
        if len(self.public_summary) > MAX_TEXT_LENGTH:
            raise ValueError("public_summary exceeds the text ceiling")
        computed = execution_service_result_fingerprint(self)
        if self.result_fingerprint:
            _validate_sha256("result_fingerprint", self.result_fingerprint)
            if self.result_fingerprint != computed:
                raise ValueError("result_fingerprint does not match result content")
        object.__setattr__(self, "result_fingerprint", computed)


def parse_canonical_utc(value: object) -> datetime:
    _require_exact_str("timestamp", value)
    if not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError("timestamp must be canonical UTC seconds ending in Z")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("timestamp is not canonical")
    return parsed


def execution_service_request_fingerprint(value: ExecutionServiceRequest) -> str:
    payload = {
        "domain": "agent-os-execution-service-request",
        "fingerprint_version": EXECUTION_SERVICE_FINGERPRINT_VERSION,
        "schema_version": value.schema_version,
        "request_id": value.request_id,
        "request_revision": value.request_revision,
        "created_at": value.created_at,
        "expires_at": value.expires_at,
        "repository_identity": list(value.repository_identity.canonical_key),
        "issue_or_handoff_identity": value.issue_or_handoff_identity,
        "canonical_owner": value.canonical_owner,
        "requesting_actor": value.requesting_actor,
        "capability": value.capability.value,
        "base_branch": value.base_branch,
        "base_sha": value.base_sha,
        "requested_ref": value.requested_ref,
        "expected_sha": value.expected_sha,
        "allowed_paths": list(value.allowed_paths),
        "forbidden_paths": list(value.forbidden_paths),
        "inspected_file_count_limit": value.inspected_file_count_limit,
        "inspected_byte_limit": value.inspected_byte_limit,
        "evidence_visibility_policy": value.evidence_visibility_policy.value,
        "invalidation_conditions": [item.value for item in value.invalidation_conditions],
    }
    return _fingerprint(payload)


def execution_service_result_fingerprint(value: ExecutionServiceResult) -> str:
    payload = {
        "domain": "agent-os-execution-service-result",
        "fingerprint_version": EXECUTION_SERVICE_FINGERPRINT_VERSION,
        "schema_version": value.schema_version,
        "request_id": value.request_id,
        "request_revision": value.request_revision,
        "request_fingerprint": value.request_fingerprint,
        "evaluated_at": value.evaluated_at,
        "service_version": value.service_version,
        "status": value.status.value,
        "reasons": [item.value for item in value.reasons],
        "repository_identity": list(value.repository_identity.canonical_key) if value.repository_identity else None,
        "requested_ref": value.requested_ref,
        "expected_sha": value.expected_sha,
        "observed_ref": value.observed_ref,
        "observed_sha": value.observed_sha,
        "inspected_file_count": value.inspected_file_count,
        "inspected_byte_count": value.inspected_byte_count,
        "private_evidence": [{"label": item.label, "value": item.value} for item in value.private_evidence],
        "public_summary": value.public_summary,
        "side_effects_performed": False,
    }
    return _fingerprint(payload)


def paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def path_is_within(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def _fingerprint(payload: dict[str, object]) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _require_exact_str(name: str, value: object) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")


def _require_exact_tuple(name: str, value: object) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")


def _require_nonnegative_int(name: str, value: object) -> None:
    if type(value) is not int or value < 0:
        raise TypeError(f"{name} must be a non-negative exact integer")


def _require_positive_int(name: str, value: object) -> None:
    if type(value) is not int or value <= 0:
        raise TypeError(f"{name} must be a positive exact integer")


def _validate_identifier(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must use bounded ASCII identifier syntax")


def _validate_owner(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _OWNER_RE.fullmatch(value):
        raise ValueError(f"{name} must use bounded ASCII owner syntax")


def _validate_sha40(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _SHA40_RE.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase commit SHA")


def _validate_sha256(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _validate_ref(name: str, value: object) -> None:
    _require_exact_str(name, value)
    if not _REF_RE.fullmatch(value):
        raise ValueError(f"{name} must use canonical ASCII ref syntax")
    if value.startswith("/") or value.endswith("/") or "//" in value or ".." in value or "@{" in value:
        raise ValueError(f"{name} is not canonical")
    if any(char in value for char in _FORBIDDEN_REF_CHARS):
        raise ValueError(f"{name} contains a forbidden ref character")


def _validate_path(value: object) -> None:
    _require_exact_str("path", value)
    if not value or len(value) > MAX_PATH_LENGTH or value.startswith("/") or "\\" in value:
        raise ValueError("path must be a bounded repository-relative POSIX path")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("path contains a control character")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("path contains a non-canonical segment")


def _validate_path_tuple(name: str, values: object, *, require_nonempty: bool) -> None:
    _require_exact_tuple(name, values)
    if require_nonempty and not values:
        raise ValueError(f"{name} must not be empty")
    if len(values) > MAX_PATH_COUNT:
        raise ValueError(f"{name} exceeds the path count ceiling")
    if not all(type(item) is str for item in values):
        raise TypeError(f"{name} must contain exact strings")
    for item in values:
        _validate_path(item)
    if values != tuple(sorted(values)) or len(set(values)) != len(values):
        raise ValueError(f"{name} must be sorted and unique")
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            if paths_overlap(left, right):
                raise ValueError(f"{name} must not contain overlapping paths")


def _validate_repository_identity(value: object) -> None:
    if type(value) is not RepositoryIdentity:
        raise TypeError("repository_identity must be the canonical exact RepositoryIdentity")
    for name in ("host", "owner", "repository", "default_branch"):
        _require_exact_str(name, getattr(value, name))
    if value.host != value.host.lower() or value.owner != value.owner.lower() or value.repository != value.repository.lower():
        raise ValueError("repository identity host, owner, and repository must be canonical lowercase")
    if not value.host or not value.owner or not value.repository:
        raise ValueError("repository identity values must not be empty")
    if value.repository_id is not None and type(value.repository_id) is not int:
        raise TypeError("repository_id must be an exact integer or None")
    if type(value.is_fork) is not bool:
        raise TypeError("is_fork must be an exact boolean")
    _validate_ref("default_branch", value.default_branch)
