"""Bounded persisted lookup descriptor for one governed Agent OS invocation.

AOS-INV1 (#1218) extends the existing execution-checkpoint/continuation
persistence boundary with one small, immutable reference record. The record
maps an existing content-addressed ``ExecutorHandoff`` identity to canonical
identities needed to reacquire current execution evidence. It does not persist
``SingleIssuePilotInput`` or executable command data and never creates
execution, GitHub, merge, closure, or external-write authority.

Storage stays under the caller-supplied execution-checkpoint store root. One
file is keyed directly by the immutable handoff identity, so a caller holding
only that identity never has to scan issue directories or invent a second
index. Existing checkpoint-store atomic-write and path-safety helpers are
reused; no queue, lock, retry system, daemon, or second lifecycle is introduced.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .identity import canonical_json_bytes, domain_digest
from .store import (
    CheckpointStoreCapacityExceeded,
    CheckpointStoreIntegrityConflict,
    CheckpointStoreUnavailable,
    _atomic_write,
    _ensure_dir,
    _existing_records_footprint,
    _reject_symlink,
)

INVOCATION_DESCRIPTOR_SCHEMA_NAME = "agent-os.governed-invocation-descriptor"
INVOCATION_DESCRIPTOR_SCHEMA_VERSION = "1.0"
INVOCATION_DESCRIPTOR_ID_DOMAIN = "agent-os.governed-invocation-descriptor"

MAX_INVOCATION_DESCRIPTOR_BYTES = 16 * 1024
MAX_INVOCATION_DESCRIPTORS = 4096
MAX_INVOCATION_DESCRIPTOR_STORE_BYTES = 64 * 1024 * 1024
MAX_INVOCATION_DESCRIPTOR_TEXT_BYTES = 4096

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$", re.ASCII)
_HANDOFF_ID_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class InvocationDescriptorNotFound(LookupError):
    """Raised when no persisted descriptor exists for one exact handoff id."""


class InvocationDescriptorIntegrityError(ValueError):
    """Raised when persisted descriptor bytes do not verify canonically."""


@dataclass(frozen=True, slots=True)
class AppendInvocationDescriptorOutcome:
    descriptor_id: str
    handoff_id: str
    path: Path
    already_present: bool


def _bounded_text(
    value: object,
    name: str,
    maximum: int = MAX_INVOCATION_DESCRIPTOR_TEXT_BYTES,
) -> str:
    if type(value) is not str or not value or _CONTROL_RE.search(value):
        raise TypeError(f"{name} must be non-empty control-free exact text")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{name} exceeds its bounded byte length")
    return value


def _identifier(value: object, name: str) -> str:
    text = _bounded_text(value, name, 512)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"{name} must use bounded ASCII identifier syntax")
    return text


def _repository(value: object) -> str:
    text = _bounded_text(value, "repository", 255)
    if not _REPOSITORY_RE.fullmatch(text):
        raise ValueError("repository must use owner/name syntax")
    return text


def _positive_issue(value: object) -> int:
    if type(value) is not int or value < 1:
        raise TypeError("issue_number must be a positive built-in integer")
    return value


def _source_sha(value: object) -> str:
    text = _bounded_text(value, "source_sha", 40)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError("source_sha must be a full lowercase SHA-1 digest")
    return text


def _handoff_id(value: object) -> str:
    text = _bounded_text(value, "handoff_id", 96)
    if not _HANDOFF_ID_RE.fullmatch(text):
        raise ValueError("handoff_id must be a canonical executor-handoff identity")
    return text


def _descriptor_payload(
    value: "GovernedInvocationDescriptor", *, include_id: bool
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": value.schema_name,
        "schema_version": value.schema_version,
        "repository": value.repository,
        "issue_number": value.issue_number,
        "issue_or_handoff_identity": value.issue_or_handoff_identity,
        "handoff_id": value.handoff_id,
        "route_decision_id": value.route_decision_id,
        "execution_service_request_fingerprint": value.execution_service_request_fingerprint,
        "authorization_id": value.authorization_id,
        "source_ref": value.source_ref,
        "source_sha": value.source_sha,
        "checkpoint_id": value.checkpoint_id,
        "resume_plan_id": value.resume_plan_id,
        "environment_profile_id": value.environment_profile_id,
        "environment_health_evidence_id": value.environment_health_evidence_id,
        "required_environment_id": value.required_environment_id,
        "dependency_readiness_evidence_id": value.dependency_readiness_evidence_id,
        "execution_surface_id": value.execution_surface_id,
        "workspace_identity": value.workspace_identity,
        "workflow_runtime_identity": value.workflow_runtime_identity,
        "candidate_packet_id": value.candidate_packet_id,
        "runtime_configuration_fingerprint": value.runtime_configuration_fingerprint,
        "execution_id": value.execution_id,
        "invocation_id": value.invocation_id,
        "repository_implementation_authorized": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "external_writes_authorized": False,
    }
    if include_id:
        payload["descriptor_id"] = value.descriptor_id
    return payload


def invocation_descriptor_id(value: "GovernedInvocationDescriptor") -> str:
    if type(value) is not GovernedInvocationDescriptor:
        raise TypeError("value must be an exact GovernedInvocationDescriptor")
    return domain_digest(
        INVOCATION_DESCRIPTOR_ID_DOMAIN,
        _descriptor_payload(value, include_id=False),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedInvocationDescriptor:
    """Non-authorizing references needed to reacquire one governed invocation."""

    schema_name: Literal["agent-os.governed-invocation-descriptor"]
    schema_version: Literal["1.0"]
    repository: str
    issue_number: int
    issue_or_handoff_identity: str
    handoff_id: str
    route_decision_id: str
    execution_service_request_fingerprint: str
    authorization_id: str
    source_ref: str
    source_sha: str
    checkpoint_id: str
    resume_plan_id: str
    environment_profile_id: str
    environment_health_evidence_id: str
    required_environment_id: str
    dependency_readiness_evidence_id: str
    execution_surface_id: str
    workspace_identity: str
    workflow_runtime_identity: str
    candidate_packet_id: str
    runtime_configuration_fingerprint: str
    execution_id: str
    invocation_id: str
    descriptor_id: str = ""
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != INVOCATION_DESCRIPTOR_SCHEMA_NAME
            or self.schema_version != INVOCATION_DESCRIPTOR_SCHEMA_VERSION
        ):
            raise ValueError("unsupported governed invocation descriptor schema")
        object.__setattr__(self, "repository", _repository(self.repository))
        _positive_issue(self.issue_number)
        object.__setattr__(self, "handoff_id", _handoff_id(self.handoff_id))
        for name in (
            "issue_or_handoff_identity",
            "route_decision_id",
            "execution_service_request_fingerprint",
            "authorization_id",
            "source_ref",
            "checkpoint_id",
            "resume_plan_id",
            "environment_profile_id",
            "environment_health_evidence_id",
            "required_environment_id",
            "dependency_readiness_evidence_id",
            "execution_surface_id",
            "workspace_identity",
            "workflow_runtime_identity",
            "candidate_packet_id",
            "runtime_configuration_fingerprint",
            "execution_id",
            "invocation_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "source_sha", _source_sha(self.source_sha))
        for name in (
            "repository_implementation_authorized",
            "execution_authorized",
            "github_writes_authorized",
            "merge_authorized",
            "issue_closure_authorized",
            "external_writes_authorized",
        ):
            if getattr(self, name) is not False:
                raise ValueError(f"{name} must remain false")
        computed = invocation_descriptor_id(self)
        if self.descriptor_id:
            _identifier(self.descriptor_id, "descriptor_id")
            if self.descriptor_id != computed:
                raise ValueError("descriptor_id does not match descriptor content")
        object.__setattr__(self, "descriptor_id", computed)
        if len(serialize_invocation_descriptor(self)) > MAX_INVOCATION_DESCRIPTOR_BYTES:
            raise ValueError("governed invocation descriptor exceeds serialized bound")

    def to_dict(self) -> dict[str, object]:
        return _descriptor_payload(self, include_id=True)


def serialize_invocation_descriptor(value: GovernedInvocationDescriptor) -> bytes:
    if type(value) is not GovernedInvocationDescriptor:
        raise TypeError("value must be an exact GovernedInvocationDescriptor")
    payload = canonical_json_bytes(_descriptor_payload(value, include_id=True))
    if len(payload) > MAX_INVOCATION_DESCRIPTOR_BYTES:
        raise ValueError("governed invocation descriptor exceeds serialized bound")
    return payload


def deserialize_invocation_descriptor(
    payload: bytes | bytearray | memoryview | str,
) -> GovernedInvocationDescriptor:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        raw = bytes(payload)
    else:
        raise TypeError("payload must be bytes-like or text")
    if len(raw) > MAX_INVOCATION_DESCRIPTOR_BYTES:
        raise ValueError("governed invocation descriptor exceeds serialized bound")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("governed invocation descriptor is not canonical JSON") from exc
    if type(decoded) is not dict:
        raise ValueError("governed invocation descriptor must be an exact object")
    expected = {
        "schema_name",
        "schema_version",
        "repository",
        "issue_number",
        "issue_or_handoff_identity",
        "handoff_id",
        "route_decision_id",
        "execution_service_request_fingerprint",
        "authorization_id",
        "source_ref",
        "source_sha",
        "checkpoint_id",
        "resume_plan_id",
        "environment_profile_id",
        "environment_health_evidence_id",
        "required_environment_id",
        "dependency_readiness_evidence_id",
        "execution_surface_id",
        "workspace_identity",
        "workflow_runtime_identity",
        "candidate_packet_id",
        "runtime_configuration_fingerprint",
        "execution_id",
        "invocation_id",
        "descriptor_id",
        "repository_implementation_authorized",
        "execution_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "issue_closure_authorized",
        "external_writes_authorized",
    }
    if set(decoded) != expected:
        raise ValueError("governed invocation descriptor contains unknown or missing fields")
    for name in (
        "repository_implementation_authorized",
        "execution_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "issue_closure_authorized",
        "external_writes_authorized",
    ):
        if decoded[name] is not False:
            raise ValueError(f"{name} must remain false")
    values = {
        name: decoded[name]
        for name in expected
        if name
        not in {
            "repository_implementation_authorized",
            "execution_authorized",
            "github_writes_authorized",
            "merge_authorized",
            "issue_closure_authorized",
            "external_writes_authorized",
        }
    }
    descriptor = GovernedInvocationDescriptor(**values)
    if serialize_invocation_descriptor(descriptor) != raw:
        raise ValueError("governed invocation descriptor is not canonical byte form")
    return descriptor


def _invocation_directory(store_root: Path | str) -> Path:
    return Path(store_root) / "invocations"


def _filename_for_handoff_id(handoff_id: str) -> str:
    canonical = _handoff_id(handoff_id)
    return f"{canonical.rsplit(':', 1)[-1]}.json"


def append_invocation_descriptor(
    store_root: Path | str,
    descriptor: GovernedInvocationDescriptor,
) -> AppendInvocationDescriptorOutcome:
    """Persist one immutable handoff-keyed descriptor atomically and idempotently."""
    if type(descriptor) is not GovernedInvocationDescriptor:
        raise TypeError("descriptor must be an exact GovernedInvocationDescriptor")
    directory = _invocation_directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    filename = _filename_for_handoff_id(descriptor.handoff_id)
    payload = serialize_invocation_descriptor(descriptor)
    destination = directory / filename
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if (
            count + 1 > MAX_INVOCATION_DESCRIPTORS
            or total_bytes + len(payload) > MAX_INVOCATION_DESCRIPTOR_STORE_BYTES
        ):
            raise CheckpointStoreCapacityExceeded(
                "governed invocation descriptor store is at capacity"
            )
    path, already_present = _atomic_write(directory, filename, payload)
    return AppendInvocationDescriptorOutcome(
        descriptor_id=descriptor.descriptor_id,
        handoff_id=descriptor.handoff_id,
        path=path,
        already_present=already_present,
    )


def load_invocation_descriptor(
    store_root: Path | str,
    handoff_id: str,
) -> GovernedInvocationDescriptor:
    """Load one exact handoff-keyed descriptor, recomputing every identity."""
    canonical_handoff = _handoff_id(handoff_id)
    directory = _invocation_directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename_for_handoff_id(canonical_handoff)
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise InvocationDescriptorNotFound(canonical_handoff) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    if len(payload) > MAX_INVOCATION_DESCRIPTOR_BYTES:
        raise InvocationDescriptorIntegrityError("descriptor exceeds the bounded size")
    try:
        descriptor = deserialize_invocation_descriptor(payload)
    except (TypeError, ValueError) as exc:
        raise InvocationDescriptorIntegrityError(str(exc)) from exc
    if descriptor.handoff_id != canonical_handoff:
        raise InvocationDescriptorIntegrityError(
            "persisted descriptor does not match requested handoff identity"
        )
    if path.name != _filename_for_handoff_id(descriptor.handoff_id):
        raise CheckpointStoreIntegrityConflict(
            "handoff-keyed descriptor filename does not match descriptor identity"
        )
    return descriptor
