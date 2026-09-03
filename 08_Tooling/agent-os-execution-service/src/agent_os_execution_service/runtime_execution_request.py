"""Canonical durable runtime-execution request with legacy read compatibility.

AOS-EXECSIMPL1 (#1338) introduces one content-addressed runtime request that
bundles the immutable route, handoff, current-invocation descriptor, and restart
capsule already required to resume governed execution. AOS-NCCE5 (#1487) adds
one already-produced canonical #1419 compute-control projection to the current
request schema so governed resume can consume that exact upstream evidence
without deriving compute semantics locally. The request creates no authority:
all authorization/currentness/dependency/lease checks remain with their existing
owners and are reacquired before Scheduler admission.

Schema ``1.0`` remains readable as a legacy request with no compute-control
projection. Schema ``1.1`` is the current write shape and requires exactly one
canonical projection. New reads prefer this request and fall back to the legacy
record graph only when the canonical request is absent. A present but malformed
request fails closed and never falls back silently.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from scripts.agent_os_execution_checkpoint.identity import canonical_json_bytes
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    GovernedInvocationDescriptor,
    deserialize_invocation_descriptor,
    load_invocation_descriptor,
)
from scripts.agent_os_execution_checkpoint.store import (
    CheckpointStoreCapacityExceeded,
    CheckpointStoreIntegrityConflict,
    CheckpointStoreUnavailable,
    _atomic_write,
    _ensure_dir,
    _existing_records_footprint,
    _reject_symlink,
)
from scripts.agent_os_issue_acceptance.compute_control_projection import (
    ComputeControlProjection,
    ComputeDisposition,
    serialize_compute_control_projection,
)

from .executor_routing import ExecutorHandoff, ExecutorRoute, ExecutorRouteDecision
from .governed_resume_restart_capsule import (
    GovernedResumeRestartCapsule,
    deserialize_restart_capsule,
    load_restart_capsule,
    serialize_restart_capsule,
)
from .handoff_store import load_executor_handoff
from .route_decision_store import load_route_decision

RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME = "agent-os.runtime-execution-request"
RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSION = "1.1"
RUNTIME_EXECUTION_REQUEST_LEGACY_SCHEMA_VERSION = "1.0"
_SUPPORTED_RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSIONS = frozenset(
    {
        RUNTIME_EXECUTION_REQUEST_LEGACY_SCHEMA_VERSION,
        RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSION,
    }
)
MAX_RUNTIME_EXECUTION_REQUEST_BYTES = 3 * 1024 * 1024
MAX_RUNTIME_EXECUTION_REQUESTS = 4096
MAX_RUNTIME_EXECUTION_REQUEST_STORE_BYTES = 512 * 1024 * 1024

_HANDOFF_ID_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)
_REQUEST_ID_RE = re.compile(r"^runtime-execution-request:[0-9a-f]{64}$", re.ASCII)


class RuntimeExecutionRequestNotFound(LookupError):
    """No canonical runtime request exists for the supplied handoff identity."""


class RuntimeExecutionRequestIntegrityError(ValueError):
    """Persisted runtime request bytes or bindings are invalid."""


@dataclass(frozen=True, slots=True)
class AppendRuntimeExecutionRequestOutcome:
    request_id: str
    handoff_id: str
    path: Path
    already_present: bool


@dataclass(frozen=True, slots=True)
class RuntimeExecutionRequestLoadResult:
    request: "RuntimeExecutionRequest"
    source: Literal["runtime-execution-request", "legacy-artifacts"]


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeExecutionRequest:
    """One immutable non-authorizing packet for governed runtime reconstruction."""

    schema_name: Literal["agent-os.runtime-execution-request"]
    schema_version: Literal["1.0", "1.1"]
    route_decision: ExecutorRouteDecision
    handoff: ExecutorHandoff
    invocation_descriptor: GovernedInvocationDescriptor
    restart_capsule: GovernedResumeRestartCapsule
    compute_control_projection: ComputeControlProjection | None = None
    request_id: str = ""
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME:
            raise ValueError("unsupported runtime execution request schema name")
        if self.schema_version not in _SUPPORTED_RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSIONS:
            raise ValueError("unsupported runtime execution request schema version")
        if type(self.route_decision) is not ExecutorRouteDecision:
            raise TypeError("route_decision must be an exact ExecutorRouteDecision")
        if type(self.handoff) is not ExecutorHandoff:
            raise TypeError("handoff must be an exact ExecutorHandoff")
        if type(self.invocation_descriptor) is not GovernedInvocationDescriptor:
            raise TypeError(
                "invocation_descriptor must be an exact GovernedInvocationDescriptor"
            )
        if type(self.restart_capsule) is not GovernedResumeRestartCapsule:
            raise TypeError("restart_capsule must be an exact GovernedResumeRestartCapsule")
        if self.schema_version == RUNTIME_EXECUTION_REQUEST_LEGACY_SCHEMA_VERSION:
            if self.compute_control_projection is not None:
                raise ValueError(
                    "legacy runtime execution request cannot carry compute-control projection"
                )
        else:
            if type(self.compute_control_projection) is not ComputeControlProjection:
                raise TypeError(
                    "current runtime execution request requires exact ComputeControlProjection"
                )
            self.compute_control_projection.__post_init__()
        _validate_bindings(self)
        computed = runtime_execution_request_id(self)
        if self.request_id:
            if not _REQUEST_ID_RE.fullmatch(self.request_id):
                raise ValueError("request_id is malformed")
            if self.request_id != computed:
                raise ValueError("request_id does not match request content")
        object.__setattr__(self, "request_id", computed)
        if len(serialize_runtime_execution_request(self)) > MAX_RUNTIME_EXECUTION_REQUEST_BYTES:
            raise ValueError("runtime execution request exceeds the serialized size bound")

    @property
    def handoff_id(self) -> str:
        return self.handoff.handoff_id


def _capsule_payload(value: GovernedResumeRestartCapsule) -> dict[str, object]:
    payload = json.loads(serialize_restart_capsule(value).decode("utf-8"))
    if type(payload) is not dict:
        raise ValueError("restart capsule serializer did not produce an object")
    return payload


def _payload(value: RuntimeExecutionRequest, *, include_id: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": value.schema_name,
        "schema_version": value.schema_version,
        "route_decision": value.route_decision.to_dict(),
        "handoff": value.handoff.to_dict(),
        "invocation_descriptor": value.invocation_descriptor.to_dict(),
        "restart_capsule": _capsule_payload(value.restart_capsule),
        "repository_implementation_authorized": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "external_writes_authorized": False,
    }
    if value.schema_version == RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSION:
        assert value.compute_control_projection is not None
        payload["compute_control_projection"] = serialize_compute_control_projection(
            value.compute_control_projection
        )
    if include_id:
        payload["request_id"] = value.request_id
    return payload


def runtime_execution_request_id(value: RuntimeExecutionRequest) -> str:
    if type(value) is not RuntimeExecutionRequest:
        raise TypeError("value must be an exact RuntimeExecutionRequest")
    digest = hashlib.sha256(
        b"agent-os.runtime-execution-request:v1\0"
        + canonical_json_bytes(_payload(value, include_id=False))
    ).hexdigest()
    return f"runtime-execution-request:{digest}"


def _validate_bindings(value: RuntimeExecutionRequest) -> None:
    route = value.route_decision
    handoff = value.handoff
    descriptor = value.invocation_descriptor
    capsule = value.restart_capsule
    packet = capsule.candidate_packet

    if route.selected_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
        raise ValueError("runtime execution request requires the governed-runner route")
    if handoff.destination_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
        raise ValueError("runtime execution request handoff is not governed-runner bound")
    if handoff.route_decision_id != route.decision_id:
        raise ValueError("handoff route decision binding drifted")
    if descriptor.route_decision_id != route.decision_id:
        raise ValueError("descriptor route decision binding drifted")
    if descriptor.handoff_id != handoff.handoff_id or capsule.handoff_id != handoff.handoff_id:
        raise ValueError("runtime request handoff identity drifted")
    if (
        descriptor.repository.casefold() != route.repository.casefold()
        or handoff.repository.casefold() != route.repository.casefold()
    ):
        raise ValueError("runtime request repository binding drifted")
    if packet.repository.casefold() != descriptor.repository.casefold():
        raise ValueError("restart capsule repository binding drifted")
    if packet.issue_number != descriptor.issue_number:
        raise ValueError("restart capsule issue binding drifted")
    if packet.invocation_id != descriptor.invocation_id:
        raise ValueError("restart capsule invocation binding drifted")
    if packet.candidate_sha != descriptor.source_sha:
        raise ValueError("restart capsule source binding drifted: SHA mismatch")
    if packet.packet_id != descriptor.candidate_packet_id:
        raise ValueError("restart capsule candidate packet binding drifted")
    if (
        capsule.required_environment_spec.required_environment_id
        != descriptor.required_environment_id
    ):
        raise ValueError("runtime request required-environment binding drifted")
    if descriptor.issue_or_handoff_identity != handoff.issue_or_handoff_identity:
        raise ValueError("runtime request subject binding drifted")
    if (
        descriptor.execution_service_request_fingerprint
        != route.execution_service_request_fingerprint_or_none
    ):
        raise ValueError("runtime request execution-service binding drifted")
    if (
        handoff.execution_service_request_fingerprint_or_none
        != descriptor.execution_service_request_fingerprint
    ):
        raise ValueError("handoff execution-service binding drifted")
    if (
        descriptor.authorization_id != route.authorization_id_or_none
        or handoff.authorization_id_or_none != descriptor.authorization_id
    ):
        raise ValueError("runtime request authorization binding drifted")
    if (
        descriptor.source_ref != handoff.source_ref_or_none
        or descriptor.source_sha != handoff.source_sha_or_none
    ):
        raise ValueError("runtime request source binding drifted")
    if (
        descriptor.checkpoint_id != handoff.checkpoint_id_or_none
        or descriptor.checkpoint_id != route.checkpoint_id_or_none
    ):
        raise ValueError("runtime request checkpoint binding drifted")
    if (
        descriptor.resume_plan_id != handoff.resume_plan_id_or_none
        or descriptor.resume_plan_id != route.resume_plan_id_or_none
    ):
        raise ValueError("runtime request resume binding drifted")
    if (
        descriptor.environment_profile_id != handoff.environment_profile_id_or_none
        or descriptor.environment_profile_id != route.environment_profile_id_or_none
    ):
        raise ValueError("runtime request environment-profile binding drifted")
    if (
        descriptor.environment_health_evidence_id
        != route.environment_health_evidence_id_or_none
    ):
        raise ValueError("runtime request environment-health binding drifted")
    if descriptor.workflow_runtime_identity != route.workflow_runtime_identity_or_none:
        raise ValueError("runtime request workflow-runtime binding drifted")
    if tuple(handoff.allowed_paths) != tuple(packet.allowed_files):
        raise ValueError("runtime request allowed-path binding drifted")
    if tuple(handoff.forbidden_paths) != tuple(packet.forbidden_paths):
        raise ValueError("runtime request forbidden-path binding drifted")

    projection = value.compute_control_projection
    if projection is not None:
        if projection.repository.casefold() != descriptor.repository.casefold():
            raise ValueError("compute-control projection repository binding drifted")
        if projection.issue_number != descriptor.issue_number:
            raise ValueError("compute-control projection issue binding drifted")
        if projection.current_head_sha != descriptor.source_sha:
            raise ValueError("compute-control projection source-head binding drifted")


def build_runtime_execution_request(
    *,
    route_decision: ExecutorRouteDecision,
    handoff: ExecutorHandoff,
    invocation_descriptor: GovernedInvocationDescriptor,
    restart_capsule: GovernedResumeRestartCapsule,
    compute_control_projection: ComputeControlProjection,
) -> RuntimeExecutionRequest:
    """Build the current 1.1 request with one exact upstream #1419 projection."""
    return RuntimeExecutionRequest(
        schema_name=RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME,
        schema_version=RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSION,
        route_decision=route_decision,
        handoff=handoff,
        invocation_descriptor=invocation_descriptor,
        restart_capsule=restart_capsule,
        compute_control_projection=compute_control_projection,
    )


def _build_legacy_runtime_execution_request(
    *,
    route_decision: ExecutorRouteDecision,
    handoff: ExecutorHandoff,
    invocation_descriptor: GovernedInvocationDescriptor,
    restart_capsule: GovernedResumeRestartCapsule,
) -> RuntimeExecutionRequest:
    """Reconstruct a readable 1.0 request only from pre-#1487 legacy artifacts."""
    return RuntimeExecutionRequest(
        schema_name=RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME,
        schema_version=RUNTIME_EXECUTION_REQUEST_LEGACY_SCHEMA_VERSION,
        route_decision=route_decision,
        handoff=handoff,
        invocation_descriptor=invocation_descriptor,
        restart_capsule=restart_capsule,
        compute_control_projection=None,
    )


def serialize_runtime_execution_request(value: RuntimeExecutionRequest) -> bytes:
    if type(value) is not RuntimeExecutionRequest:
        raise TypeError("value must be an exact RuntimeExecutionRequest")
    payload = canonical_json_bytes(_payload(value, include_id=True))
    if len(payload) > MAX_RUNTIME_EXECUTION_REQUEST_BYTES:
        raise ValueError("runtime execution request exceeds the serialized size bound")
    return payload


def _deserialize_compute_control_projection(payload: object) -> ComputeControlProjection:
    if type(payload) is not dict:
        raise ValueError("compute-control projection payload must be an object")
    expected = {
        "schema_name",
        "schema_version",
        "repository",
        "issue_number",
        "pull_request_number",
        "current_head_sha",
        "base_handoff_projection_reference",
        "compute_disposition",
        "recommended_validation_or_execution_class",
        "primary_blocker",
        "duplicate_or_stale_risk",
        "active_execution_reference",
        "last_applicable_validation_reference",
        "measured_compute_metadata_reference",
        "reason_codes",
        "source_revision",
        "authority_created",
        "side_effects_performed",
        "notion_write_performed",
        "projection_id",
    }
    if set(payload) != expected:
        raise ValueError("compute-control projection contains unknown or missing fields")
    for name in (
        "authority_created",
        "side_effects_performed",
        "notion_write_performed",
    ):
        if payload[name] is not False:
            raise ValueError(f"compute-control projection {name} must remain false")
    reason_codes = payload["reason_codes"]
    if type(reason_codes) is not list:
        raise ValueError("compute-control projection reason_codes must be a list")
    try:
        disposition = ComputeDisposition(payload["compute_disposition"])
    except (TypeError, ValueError) as exc:
        raise ValueError("compute-control projection disposition is unsupported") from exc
    projection = ComputeControlProjection(
        schema_name=payload["schema_name"],
        schema_version=payload["schema_version"],
        repository=payload["repository"],
        issue_number=payload["issue_number"],
        pull_request_number=payload["pull_request_number"],
        current_head_sha=payload["current_head_sha"],
        base_handoff_projection_reference=payload["base_handoff_projection_reference"],
        compute_disposition=disposition,
        recommended_validation_or_execution_class=payload[
            "recommended_validation_or_execution_class"
        ],
        primary_blocker=payload["primary_blocker"],
        duplicate_or_stale_risk=payload["duplicate_or_stale_risk"],
        active_execution_reference=payload["active_execution_reference"],
        last_applicable_validation_reference=payload[
            "last_applicable_validation_reference"
        ],
        measured_compute_metadata_reference=payload[
            "measured_compute_metadata_reference"
        ],
        reason_codes=tuple(reason_codes),
        source_revision=payload["source_revision"],
        projection_id=payload["projection_id"],
    )
    if serialize_compute_control_projection(projection) != payload:
        raise ValueError("compute-control projection is not canonical")
    return projection


def deserialize_runtime_execution_request(
    payload: bytes | bytearray | memoryview | str,
) -> RuntimeExecutionRequest:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        raw = bytes(payload)
    else:
        raise TypeError("payload must be bytes-like or text")
    if len(raw) > MAX_RUNTIME_EXECUTION_REQUEST_BYTES:
        raise ValueError("runtime execution request exceeds the serialized size bound")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("runtime execution request is not valid JSON") from exc
    if type(decoded) is not dict:
        raise ValueError("runtime execution request must be an object")
    if decoded.get("schema_name") != RUNTIME_EXECUTION_REQUEST_SCHEMA_NAME:
        raise ValueError("unsupported runtime execution request schema name")
    schema_version = decoded.get("schema_version")
    if schema_version not in _SUPPORTED_RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSIONS:
        raise ValueError("unsupported runtime execution request schema version")
    expected = {
        "schema_name",
        "schema_version",
        "route_decision",
        "handoff",
        "invocation_descriptor",
        "restart_capsule",
        "request_id",
        "repository_implementation_authorized",
        "execution_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "issue_closure_authorized",
        "external_writes_authorized",
    }
    if schema_version == RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSION:
        expected.add("compute_control_projection")
    if set(decoded) != expected:
        raise ValueError("runtime execution request contains unknown or missing fields")
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
    if type(decoded["route_decision"]) is not dict or type(decoded["handoff"]) is not dict:
        raise ValueError("runtime execution request route/handoff payload is malformed")
    if (
        type(decoded["invocation_descriptor"]) is not dict
        or type(decoded["restart_capsule"]) is not dict
    ):
        raise ValueError("runtime execution request recovery payload is malformed")
    projection = None
    if schema_version == RUNTIME_EXECUTION_REQUEST_SCHEMA_VERSION:
        projection = _deserialize_compute_control_projection(
            decoded["compute_control_projection"]
        )
    value = RuntimeExecutionRequest(
        schema_name=decoded["schema_name"],
        schema_version=schema_version,
        route_decision=ExecutorRouteDecision.from_dict(decoded["route_decision"]),
        handoff=ExecutorHandoff.from_dict(decoded["handoff"]),
        invocation_descriptor=deserialize_invocation_descriptor(
            canonical_json_bytes(decoded["invocation_descriptor"])
        ),
        restart_capsule=deserialize_restart_capsule(
            canonical_json_bytes(decoded["restart_capsule"])
        ),
        compute_control_projection=projection,
        request_id=decoded["request_id"],
    )
    if serialize_runtime_execution_request(value) != raw:
        raise ValueError("runtime execution request is not canonical byte form")
    return value


def _directory(store_root: Path | str) -> Path:
    return Path(store_root) / "runtime-execution-requests"


def _handoff_id(value: object) -> str:
    if type(value) is not str or not _HANDOFF_ID_RE.fullmatch(value):
        raise TypeError("handoff_id must be executor-handoff:<64-lowercase-hex>")
    return value


def _filename(handoff_id: str) -> str:
    return f"{_handoff_id(handoff_id).rsplit(':', 1)[-1]}.json"


def append_runtime_execution_request(
    store_root: Path | str,
    request: RuntimeExecutionRequest,
) -> AppendRuntimeExecutionRequestOutcome:
    if type(request) is not RuntimeExecutionRequest:
        raise TypeError("request must be an exact RuntimeExecutionRequest")
    directory = _directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    payload = serialize_runtime_execution_request(request)
    destination = directory / _filename(request.handoff_id)
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if (
            count + 1 > MAX_RUNTIME_EXECUTION_REQUESTS
            or total_bytes + len(payload) > MAX_RUNTIME_EXECUTION_REQUEST_STORE_BYTES
        ):
            raise CheckpointStoreCapacityExceeded(
                "runtime execution request store is at capacity"
            )
    path, already_present = _atomic_write(directory, destination.name, payload)
    return AppendRuntimeExecutionRequestOutcome(
        request_id=request.request_id,
        handoff_id=request.handoff_id,
        path=path,
        already_present=already_present,
    )


def load_runtime_execution_request(
    store_root: Path | str,
    handoff_id: str,
) -> RuntimeExecutionRequest:
    canonical = _handoff_id(handoff_id)
    directory = _directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename(canonical)
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise RuntimeExecutionRequestNotFound(canonical) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    if len(payload) > MAX_RUNTIME_EXECUTION_REQUEST_BYTES:
        raise RuntimeExecutionRequestIntegrityError(
            "runtime execution request exceeds the bounded size"
        )
    try:
        request = deserialize_runtime_execution_request(payload)
    except (TypeError, ValueError) as exc:
        raise RuntimeExecutionRequestIntegrityError(str(exc)) from exc
    if request.handoff_id != canonical:
        raise RuntimeExecutionRequestIntegrityError(
            "persisted runtime request does not match requested handoff identity"
        )
    if path.name != _filename(request.handoff_id):
        raise CheckpointStoreIntegrityConflict(
            "runtime request filename does not match handoff identity"
        )
    return request


def load_runtime_execution_request_or_legacy(
    store_root: Path | str,
    handoff_id: str,
) -> RuntimeExecutionRequestLoadResult:
    """Prefer the canonical request; fall back only when it is genuinely absent."""
    try:
        request = load_runtime_execution_request(store_root, handoff_id)
    except RuntimeExecutionRequestNotFound:
        descriptor = load_invocation_descriptor(store_root, handoff_id)
        request = _build_legacy_runtime_execution_request(
            route_decision=load_route_decision(store_root, descriptor.route_decision_id),
            handoff=load_executor_handoff(store_root, handoff_id),
            invocation_descriptor=descriptor,
            restart_capsule=load_restart_capsule(store_root, handoff_id),
        )
        return RuntimeExecutionRequestLoadResult(
            request=request,
            source="legacy-artifacts",
        )
    return RuntimeExecutionRequestLoadResult(
        request=request,
        source="runtime-execution-request",
    )
