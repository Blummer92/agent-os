"""Pure authorized-validation admission contracts for Issue #757.

The module verifies already-constructed canonical candidate, approval, execution-
packet, and human execution-authorization evidence before any runtime-capable
lifecycle stage is permitted to act.  It performs no I/O and creates no
execution authority.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalProjectionStageResult,
    ApprovalProjectionStageStatus,
    approval_projection_stage_result_from_dict,
    approval_projection_stage_result_to_dict,
)
from scripts.agent_os_candidate_packet.execution_packet_stage import (
    ExecutionPacketDisposition,
    ExecutionPacketStageResult,
    execution_packet_stage_result_from_dict,
    execution_packet_stage_result_to_dict,
)
from scripts.agent_os_candidate_packet.models import (
    CandidatePacket,
    CandidatePacketPhase,
    candidate_packet_id,
    deserialize_candidate_packet,
    serialize_candidate_packet,
)
from scripts.agent_os_issue_acceptance.approval_records import ApprovalState

from .authorization import ExecutionAuthorizationEvidence
from .models import parse_canonical_utc

AUTHORIZED_VALIDATION_SCHEMA_VERSION = "1.0"
AUTHORIZED_VALIDATION_POLICY_SCHEMA_VERSION = "1.0"
AUTHORIZED_VALIDATION_PERMITTED_OPERATION = "validation-only"

_POLICY_VALUES = {
    "process_containment_policy": "bounded-process-tree-proof-required",
    "lease_policy": "exact-host-local-concurrency-1",
    "workspace_policy": "isolated-worktree-exact-sha",
    "cleanup_policy": "non-force-cleanup-proof-required",
    "release_policy": "exact-lease-release-proof-required",
    "quarantine_policy": "quarantine-on-uncertainty",
    "timeout_output_policy": "candidate-packet-runtime-bounds",
}
_MAX_PATHS = 256
_MAX_PATH_LENGTH = 512
_MAX_SERIALIZED_BYTES = 262_144


class AuthorizedValidationAdmissionStatus(str, Enum):
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    STALE = "stale"
    NEEDS_DECISION = "needs-decision"
    INVALID = "invalid"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _identity(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(
        f"agent-os-{prefix}:v1\0".encode("ascii") + _canonical_bytes(payload)
    ).hexdigest()
    return f"{prefix}:{digest}"


def _exact_text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty canonical text")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{name} contains control characters")
    return value


def _paths(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    if len(value) > _MAX_PATHS:
        raise ValueError(f"{name} exceeds the bounded count")
    result: list[str] = []
    for item in value:
        text = _exact_text(item, name)
        if len(text) > _MAX_PATH_LENGTH:
            raise ValueError(f"{name} contains an oversized path")
        if text.startswith("/") or "\\" in text or ".." in text.split("/"):
            raise ValueError(f"{name} contains a non-canonical path")
        result.append(text)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} contains duplicate paths")
    return tuple(result)


def _stage_digest(stage_name: str, payload: object) -> str:
    digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return f"candidate-packet-stage:{stage_name}:{digest}"


def _pairs(items: tuple[tuple[str, str], ...], label: str) -> dict[str, str]:
    if type(items) is not tuple:
        raise ValueError(f"{label} must be an exact tuple")
    result: dict[str, str] = {}
    for item in items:
        if type(item) is not tuple or len(item) != 2:
            raise ValueError(f"{label} contains a malformed pair")
        name, value = item
        _exact_text(name, label)
        _exact_text(value, label)
        if name in result:
            raise ValueError(f"{label} contains duplicate identities")
        result[name] = value
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizedValidationLifecyclePolicy:
    """Versioned lifecycle policy bound by #757, without runtime behavior."""

    schema_version: str = AUTHORIZED_VALIDATION_POLICY_SCHEMA_VERSION
    policy_id: str = ""
    expected_changed_paths: tuple[str, ...] = ()
    requested_concurrency: int = 1
    process_containment_policy: str = _POLICY_VALUES["process_containment_policy"]
    lease_policy: str = _POLICY_VALUES["lease_policy"]
    workspace_policy: str = _POLICY_VALUES["workspace_policy"]
    cleanup_policy: str = _POLICY_VALUES["cleanup_policy"]
    release_policy: str = _POLICY_VALUES["release_policy"]
    quarantine_policy: str = _POLICY_VALUES["quarantine_policy"]
    timeout_output_policy: str = _POLICY_VALUES["timeout_output_policy"]
    automatic_retry: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != AUTHORIZED_VALIDATION_POLICY_SCHEMA_VERSION:
            raise ValueError("unsupported authorized-validation policy schema")
        object.__setattr__(
            self,
            "expected_changed_paths",
            _paths(self.expected_changed_paths, "expected_changed_paths"),
        )
        if type(self.requested_concurrency) is not int or isinstance(
            self.requested_concurrency, bool
        ):
            raise TypeError("requested_concurrency must be an exact integer")
        if self.requested_concurrency != 1:
            raise ValueError("requested_concurrency must be exactly 1")
        for name, expected in _POLICY_VALUES.items():
            if getattr(self, name) != expected:
                raise ValueError(f"unsupported {name}")
        expected_id = _identity("authorized-validation-policy", _policy_payload(self))
        if self.policy_id and self.policy_id != expected_id:
            raise ValueError("policy_id does not match policy content")
        object.__setattr__(self, "policy_id", expected_id)


def _policy_payload(policy: AuthorizedValidationLifecyclePolicy) -> dict[str, object]:
    return {
        "schema_version": policy.schema_version,
        "expected_changed_paths": list(policy.expected_changed_paths),
        "requested_concurrency": policy.requested_concurrency,
        "process_containment_policy": policy.process_containment_policy,
        "lease_policy": policy.lease_policy,
        "workspace_policy": policy.workspace_policy,
        "cleanup_policy": policy.cleanup_policy,
        "release_policy": policy.release_policy,
        "quarantine_policy": policy.quarantine_policy,
        "timeout_output_policy": policy.timeout_output_policy,
        "automatic_retry": False,
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizedValidationLifecycleRequest:
    """Content-addressed roots required for one admission decision.

    Nested semantics stay owned by their canonical modules; #757 binds their
    canonical identities and independently re-verifies them at admission time.
    """

    schema_version: str
    request_id: str
    candidate_packet: CandidatePacket
    approval_stage: ApprovalProjectionStageResult
    execution_packet_stage: ExecutionPacketStageResult
    execution_authorization: ExecutionAuthorizationEvidence
    authorizer_id: str
    authorized_candidate_packet_id: str
    authorized_invocation_id: str
    authorized_operation: str
    lifecycle_policy: AuthorizedValidationLifecyclePolicy
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != AUTHORIZED_VALIDATION_SCHEMA_VERSION:
            raise ValueError("unsupported authorized-validation request schema")
        if type(self.candidate_packet) is not CandidatePacket:
            raise TypeError("candidate_packet must be an exact CandidatePacket")
        if type(self.approval_stage) is not ApprovalProjectionStageResult:
            raise TypeError("approval_stage must be an exact ApprovalProjectionStageResult")
        if type(self.execution_packet_stage) is not ExecutionPacketStageResult:
            raise TypeError("execution_packet_stage must be an exact ExecutionPacketStageResult")
        if type(self.execution_authorization) is not ExecutionAuthorizationEvidence:
            raise TypeError("execution_authorization must be exact ExecutionAuthorizationEvidence")
        if type(self.lifecycle_policy) is not AuthorizedValidationLifecyclePolicy:
            raise TypeError("lifecycle_policy must be exact AuthorizedValidationLifecyclePolicy")
        object.__setattr__(self, "authorizer_id", _exact_text(self.authorizer_id, "authorizer_id"))
        object.__setattr__(self, "authorized_candidate_packet_id", _exact_text(self.authorized_candidate_packet_id, "authorized_candidate_packet_id"))
        object.__setattr__(self, "authorized_invocation_id", _exact_text(self.authorized_invocation_id, "authorized_invocation_id"))
        object.__setattr__(self, "authorized_operation", _exact_text(self.authorized_operation, "authorized_operation"))
        expected_id = _request_id(self)
        if self.request_id and self.request_id != expected_id:
            raise ValueError("request_id does not match request content")
        object.__setattr__(self, "request_id", expected_id)


def _request_identity_payload(request: AuthorizedValidationLifecycleRequest) -> dict[str, object]:
    approval_digests = _pairs(request.candidate_packet.stage_payload_digests, "stage_payload_digests")
    return {
        "schema_version": request.schema_version,
        "candidate_packet_id": request.candidate_packet.packet_id,
        "invocation_id": request.candidate_packet.invocation_id,
        "approval_stage_digest": approval_digests.get("approval"),
        "execution_packet_stage_digest": approval_digests.get("execution-packet"),
        "execution_authorization": _authorization_payload(request.execution_authorization),
        "authorizer_id": request.authorizer_id,
        "authorized_candidate_packet_id": request.authorized_candidate_packet_id,
        "authorized_invocation_id": request.authorized_invocation_id,
        "authorized_operation": request.authorized_operation,
        "lifecycle_policy_id": request.lifecycle_policy.policy_id,
        "execution_authorized": False,
        "merge_authorized": False,
        "automatic_retry": False,
        "side_effects_performed": False,
    }


def _request_id(request: AuthorizedValidationLifecycleRequest) -> str:
    return _identity("authorized-validation-request", _request_identity_payload(request))


def _authorization_payload(evidence: ExecutionAuthorizationEvidence) -> dict[str, object]:
    return {
        "authorization_id": evidence.authorization_id,
        "request_fingerprint": evidence.request_fingerprint,
        "command_plan_id": evidence.command_plan_id,
        "repository": evidence.repository,
        "expected_sha": evidence.expected_sha,
        "authorized_at": evidence.authorized_at,
        "expires_at": evidence.expires_at,
        "execution_authorized": evidence.execution_authorized,
        "side_effects_performed": False,
    }


def build_authorized_validation_lifecycle_request(
    *,
    candidate_packet: CandidatePacket,
    approval_stage: ApprovalProjectionStageResult,
    execution_packet_stage: ExecutionPacketStageResult,
    execution_authorization: ExecutionAuthorizationEvidence,
    authorizer_id: str,
    authorized_candidate_packet_id: str,
    authorized_invocation_id: str,
    authorized_operation: str = AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
    lifecycle_policy: AuthorizedValidationLifecyclePolicy,
) -> AuthorizedValidationLifecycleRequest:
    """Build one immutable request without performing admission or any I/O."""
    return AuthorizedValidationLifecycleRequest(
        schema_version=AUTHORIZED_VALIDATION_SCHEMA_VERSION,
        request_id="",
        candidate_packet=candidate_packet,
        approval_stage=approval_stage,
        execution_packet_stage=execution_packet_stage,
        execution_authorization=execution_authorization,
        authorizer_id=authorizer_id,
        authorized_candidate_packet_id=authorized_candidate_packet_id,
        authorized_invocation_id=authorized_invocation_id,
        authorized_operation=authorized_operation,
        lifecycle_policy=lifecycle_policy,
    )


_REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "request_id",
        "candidate_packet",
        "approval_stage",
        "execution_packet_stage",
        "execution_authorization",
        "authorizer_id",
        "authorized_candidate_packet_id",
        "authorized_invocation_id",
        "authorized_operation",
        "lifecycle_policy",
        "execution_authorized",
        "merge_authorized",
        "automatic_retry",
        "side_effects_performed",
    }
)
_POLICY_KEYS = frozenset({"policy_id", *_POLICY_VALUES.keys(), "schema_version", "expected_changed_paths", "requested_concurrency", "automatic_retry"})
_AUTHORIZATION_KEYS = frozenset(
    {
        "authorization_id",
        "request_fingerprint",
        "command_plan_id",
        "repository",
        "expected_sha",
        "authorized_at",
        "expires_at",
        "execution_authorized",
        "side_effects_performed",
    }
)


def _closed_mapping(value: object, keys: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    if set(value) != keys:
        raise ValueError(f"{name} fields drifted")
    return value


def _serialize_policy(policy: AuthorizedValidationLifecyclePolicy) -> dict[str, object]:
    payload = _policy_payload(policy)
    payload["policy_id"] = policy.policy_id
    return payload


def _reconstruct_policy(payload: object) -> AuthorizedValidationLifecyclePolicy:
    value = _closed_mapping(payload, _POLICY_KEYS, "lifecycle_policy")
    if value["automatic_retry"] is not False:
        raise ValueError("automatic_retry must be false")
    return AuthorizedValidationLifecyclePolicy(
        schema_version=value["schema_version"],
        policy_id=value["policy_id"],
        expected_changed_paths=tuple(value["expected_changed_paths"])
        if type(value["expected_changed_paths"]) is list
        else value["expected_changed_paths"],
        requested_concurrency=value["requested_concurrency"],
        process_containment_policy=value["process_containment_policy"],
        lease_policy=value["lease_policy"],
        workspace_policy=value["workspace_policy"],
        cleanup_policy=value["cleanup_policy"],
        release_policy=value["release_policy"],
        quarantine_policy=value["quarantine_policy"],
        timeout_output_policy=value["timeout_output_policy"],
    )


def _reconstruct_authorization(payload: object) -> ExecutionAuthorizationEvidence:
    value = _closed_mapping(payload, _AUTHORIZATION_KEYS, "execution_authorization")
    if value["side_effects_performed"] is not False:
        raise ValueError("authorization side_effects_performed must be false")
    return ExecutionAuthorizationEvidence(
        authorization_id=value["authorization_id"],
        request_fingerprint=value["request_fingerprint"],
        command_plan_id=value["command_plan_id"],
        repository=value["repository"],
        expected_sha=value["expected_sha"],
        authorized_at=value["authorized_at"],
        expires_at=value["expires_at"],
        execution_authorized=value["execution_authorized"],
    )


def serialize_authorized_validation_lifecycle_request(
    request: AuthorizedValidationLifecycleRequest,
) -> dict[str, object]:
    if type(request) is not AuthorizedValidationLifecycleRequest:
        raise TypeError("request must be exact AuthorizedValidationLifecycleRequest")
    payload = {
        "schema_version": request.schema_version,
        "request_id": request.request_id,
        "candidate_packet": serialize_candidate_packet(request.candidate_packet),
        "approval_stage": approval_projection_stage_result_to_dict(request.approval_stage),
        "execution_packet_stage": execution_packet_stage_result_to_dict(request.execution_packet_stage),
        "execution_authorization": _authorization_payload(request.execution_authorization),
        "authorizer_id": request.authorizer_id,
        "authorized_candidate_packet_id": request.authorized_candidate_packet_id,
        "authorized_invocation_id": request.authorized_invocation_id,
        "authorized_operation": request.authorized_operation,
        "lifecycle_policy": _serialize_policy(request.lifecycle_policy),
        "execution_authorized": False,
        "merge_authorized": False,
        "automatic_retry": False,
        "side_effects_performed": False,
    }
    if len(_canonical_bytes(payload)) > _MAX_SERIALIZED_BYTES:
        raise ValueError("authorized validation request exceeds serialized size bound")
    if reconstruct_authorized_validation_lifecycle_request(payload) != request:
        raise ValueError("authorized validation request is noncanonical")
    return payload


def reconstruct_authorized_validation_lifecycle_request(
    payload: object,
) -> AuthorizedValidationLifecycleRequest:
    value = _closed_mapping(payload, _REQUEST_KEYS, "authorized validation request")
    for name in ("execution_authorized", "merge_authorized", "automatic_retry", "side_effects_performed"):
        if value[name] is not False:
            raise ValueError(f"{name} must be false")
    if value["schema_version"] != AUTHORIZED_VALIDATION_SCHEMA_VERSION:
        raise ValueError("unsupported authorized-validation request schema")
    return AuthorizedValidationLifecycleRequest(
        schema_version=value["schema_version"],
        request_id=value["request_id"],
        candidate_packet=deserialize_candidate_packet(value["candidate_packet"]),
        approval_stage=approval_projection_stage_result_from_dict(value["approval_stage"]),
        execution_packet_stage=execution_packet_stage_result_from_dict(value["execution_packet_stage"]),
        execution_authorization=_reconstruct_authorization(value["execution_authorization"]),
        authorizer_id=value["authorizer_id"],
        authorized_candidate_packet_id=value["authorized_candidate_packet_id"],
        authorized_invocation_id=value["authorized_invocation_id"],
        authorized_operation=value["authorized_operation"],
        lifecycle_policy=_reconstruct_policy(value["lifecycle_policy"]),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorizedValidationAdmissionResult:
    schema_version: str
    request_id: str
    evaluated_at: str
    status: AuthorizedValidationAdmissionStatus
    reason_codes: tuple[str, ...]
    accepted: bool
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != AUTHORIZED_VALIDATION_SCHEMA_VERSION:
            raise ValueError("unsupported admission result schema")
        _exact_text(self.request_id, "request_id")
        parse_canonical_utc(self.evaluated_at)
        if type(self.status) is not AuthorizedValidationAdmissionStatus:
            raise TypeError("status must be AuthorizedValidationAdmissionStatus")
        if type(self.accepted) is not bool or self.accepted != (
            self.status is AuthorizedValidationAdmissionStatus.ACCEPTED
        ):
            raise ValueError("accepted must match accepted status")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        reasons = tuple(sorted(set(_exact_text(item, "reason_code") for item in self.reason_codes)))
        if reasons != self.reason_codes:
            raise ValueError("reason_codes must be sorted and unique")


def _result(
    request: AuthorizedValidationLifecycleRequest,
    evaluated_at: str,
    status: AuthorizedValidationAdmissionStatus,
    *reason_codes: str,
) -> AuthorizedValidationAdmissionResult:
    reasons = tuple(sorted(set(reason_codes or (status.value,))))
    return AuthorizedValidationAdmissionResult(
        schema_version=AUTHORIZED_VALIDATION_SCHEMA_VERSION,
        request_id=request.request_id,
        evaluated_at=evaluated_at,
        status=status,
        reason_codes=reasons,
        accepted=status is AuthorizedValidationAdmissionStatus.ACCEPTED,
    )


def _timestamp(value: str) -> datetime:
    return parse_canonical_utc(value).astimezone(timezone.utc)


def verify_authorized_validation_admission(
    request: object,
    *,
    evaluated_at: str,
) -> AuthorizedValidationAdmissionResult:
    """Fail-closed admission verification with zero runtime adapter invocation."""
    if type(request) is not AuthorizedValidationLifecycleRequest:
        raise TypeError("request must be exact AuthorizedValidationLifecycleRequest")
    evaluated = _timestamp(evaluated_at)

    try:
        if request.request_id != _request_id(request):
            return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "request.identity-mismatch")
        if request.candidate_packet.packet_id != candidate_packet_id(request.candidate_packet):
            return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "candidate.identity-mismatch")
        if deserialize_candidate_packet(serialize_candidate_packet(request.candidate_packet)) != request.candidate_packet:
            return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "candidate.noncanonical")
        if approval_projection_stage_result_from_dict(
            approval_projection_stage_result_to_dict(request.approval_stage)
        ) != request.approval_stage:
            return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "approval.noncanonical")
        if execution_packet_stage_result_from_dict(
            execution_packet_stage_result_to_dict(request.execution_packet_stage)
        ) != request.execution_packet_stage:
            return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "execution-packet.noncanonical")
    except (TypeError, ValueError):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "canonical-root.invalid")

    packet = request.candidate_packet
    approval = request.approval_stage
    execution = request.execution_packet_stage
    authorization = request.execution_authorization
    policy = request.lifecycle_policy

    if packet.phase is not CandidatePacketPhase.EXECUTION_CANDIDATE:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "candidate.not-execution-candidate")
    if packet.evidence_completeness != "complete" or packet.disposition != "verified":
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "candidate.incomplete")
    if any((packet.execution_authorized, packet.merge_authorized, packet.automatic_retry, packet.side_effects_performed)):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "candidate.authority-drift")

    if approval.status is ApprovalProjectionStageStatus.NEEDS_DECISION:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.NEEDS_DECISION, "approval.needs-decision")
    if approval.status in {ApprovalProjectionStageStatus.STALE, ApprovalProjectionStageStatus.EXPIRED}:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "approval.stale")
    if approval.status is not ApprovalProjectionStageStatus.COMPLETE:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "approval.not-complete")
    if approval.decision_revision is None or approval.applicability is None or approval.projection is None:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "approval.complete-evidence-missing")
    if approval.decision_revision.state is not ApprovalState.APPROVED:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "approval.not-approved")
    if approval.applicability.status != "applicable" or not approval.applicability.approval_applicable:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "approval.not-applicable")

    if execution.disposition is ExecutionPacketDisposition.NEEDS_DECISION:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.NEEDS_DECISION, "execution-packet.needs-decision")
    if execution.disposition is not ExecutionPacketDisposition.GO or not execution.packet_complete:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "execution-packet.not-go")
    if execution.request is None or execution.command_plan is None or execution.runtime_configuration is None:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "execution-packet.complete-evidence-missing")
    if any((execution.execution_authorized, execution.merge_authorized, execution.automatic_retry, execution.side_effects_performed)):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "execution-packet.authority-drift")

    try:
        digests = _pairs(packet.stage_payload_digests, "stage_payload_digests")
        identities = _pairs(packet.stage_identities, "stage_identities")
    except ValueError:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "candidate.identity-map-invalid")
    if digests.get("approval") != _stage_digest("approval", approval_projection_stage_result_to_dict(approval)):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "candidate.approval-stage-drift")
    if digests.get("execution-packet") != _stage_digest("execution-packet", execution_packet_stage_result_to_dict(execution)):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "candidate.execution-stage-drift")

    decision_identity = f"{approval.decision_revision.approval_id}@{approval.decision_revision.approval_revision}"
    identity_expectations = {
        "approval-decision": decision_identity,
        "projection": approval.projection.projection_id,
        "validation-plan": execution.validation_stage.validation_plan_id,
        "execution-request": execution.request_fingerprint,
        "command-plan": execution.command_plan_id,
        "runtime-configuration": execution.runtime_configuration_fingerprint,
    }
    if any(identities.get(name) != value for name, value in identity_expectations.items()):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "candidate.stage-identity-drift")

    runtime = execution.runtime_configuration
    if packet.repository.casefold() != runtime.repository.casefold() or packet.issue_number != runtime.issue_number:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "runtime.subject-drift")
    if packet.invocation_id != runtime.invocation_id:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "runtime.invocation-drift")
    if packet.base_branch != runtime.base_branch or packet.base_sha != runtime.base_sha:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "runtime.base-drift")
    if packet.candidate_sha != runtime.source_head_sha or packet.tested_sha != runtime.tested_sha:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "runtime.sha-drift")
    if runtime.projection_id != approval.projection.projection_id or runtime.approval_id != approval.decision_revision.approval_id:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "runtime.approval-drift")
    if runtime.validation_plan_id != execution.validation_stage.validation_plan_id:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "runtime.validation-plan-drift")
    if packet.allowed_files != tuple(runtime.allowed_files) or packet.forbidden_paths != tuple(runtime.forbidden_paths):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "scope.drift")
    runtime_test_ids = tuple(item.test_id for item in runtime.required_test_commands)
    if packet.required_tests != runtime_test_ids:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "tests.drift")
    plan_argvs = tuple(entry.argv for entry in execution.command_plan.entries)
    packet_argvs = tuple(argv for _, argv in packet.argv_bindings)
    if packet.command_identities != packet.required_tests or plan_argvs != packet_argvs:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "commands.drift")
    if (
        packet.per_command_timeout_seconds != runtime.validation_per_command_timeout_seconds
        or packet.total_timeout_seconds != runtime.validation_total_timeout_seconds
        or packet.max_output_bytes != runtime.validation_max_output_bytes
    ):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "runtime.bounds-drift")

    if request.authorized_candidate_packet_id != packet.packet_id:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "authorization.candidate-packet-drift")
    if request.authorized_invocation_id != packet.invocation_id:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "authorization.invocation-drift")
    if request.authorized_operation != AUTHORIZED_VALIDATION_PERMITTED_OPERATION or runtime.execution_mode != request.authorized_operation:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "authorization.operation-not-permitted")
    if runtime.executor_argv is not None:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "authorization.executor-not-permitted")
    if authorization.execution_authorized is not True:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "authorization.not-authorized")
    if authorization.side_effects_performed is not False:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "authorization.side-effect-drift")
    if authorization.repository.casefold() != packet.repository.casefold():
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "authorization.repository-drift")
    if authorization.request_fingerprint != execution.request_fingerprint or authorization.command_plan_id != execution.command_plan_id:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "authorization.plan-drift")
    if authorization.expected_sha != packet.candidate_sha or authorization.expected_sha != execution.request.expected_sha:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "authorization.sha-drift")
    _exact_text(request.authorizer_id, "authorizer_id")

    authorized_at = _timestamp(authorization.authorized_at)
    expires_at = _timestamp(authorization.expires_at)
    if authorized_at >= expires_at:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "authorization.window-invalid")
    if evaluated < authorized_at:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "authorization.not-yet-active")
    if evaluated >= expires_at:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "authorization.expired")

    if policy.policy_id != _identity("authorized-validation-policy", _policy_payload(policy)):
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.INVALID, "policy.identity-mismatch")
    if policy.requested_concurrency != 1 or policy.automatic_retry is not False:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.BLOCKED, "policy.authority-drift")
    if policy.expected_changed_paths != packet.expected_changed_paths:
        return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.STALE, "policy.expected-paths-drift")

    return _result(request, evaluated_at, AuthorizedValidationAdmissionStatus.ACCEPTED, "accepted")
