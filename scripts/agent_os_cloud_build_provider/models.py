from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from scripts.agent_os_cloud_build_reporting import CloudBuildResultEvidence

PROVIDER_SCHEMA_VERSION = "1.0"
MAX_PROVIDER_STRING_LENGTH = 512
MAX_PROVIDER_COMMANDS = 64
MAX_PROVIDER_ARGV_ITEMS = 64
MAX_PROVIDER_REASON_CODES = 32
MAX_PROVIDER_SERIALIZED_BYTES = 262_144
MAX_BUILD_TIMEOUT_SECONDS = 3_600
MAX_OUTPUT_BYTES = 10_000_000
MAX_DIAGNOSTIC_BYTES = 65_536

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$", re.ASCII)
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_RE = re.compile(
    r"(?i)(authorization\s*:|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"(?:token|password|secret|api[_-]?key|private[_-]?key)\s*[:=])"
)
_DIGEST_IDENTITY_RE = re.compile(r"^[A-Za-z0-9._:/@+-]+@sha256:[0-9a-f]{64}$", re.ASCII)


class ProviderStatus(str, Enum):
    ACCEPTED = "accepted"
    SKIPPED = "skipped"
    MANUAL_REVIEW = "manual-review"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    TERMINAL = "terminal"


class ProviderObservationStatus(str, Enum):
    WORKING = "working"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal-error"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ProviderSideEffectState(str, Enum):
    NONE = "none"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class ProviderReason(str, Enum):
    ACCEPTED = "accepted"
    INPUT_INVALID_TYPE = "input.invalid-type"
    INPUT_UNSUPPORTED_SCHEMA = "input.unsupported-schema"
    INPUT_MALFORMED = "input.malformed"
    INPUT_LIMIT_EXCEEDED = "input.limit-exceeded"
    INPUT_CONTROL_CHARACTER = "input.control-character"
    INPUT_SECRET_LIKE_VALUE = "input.secret-like-value"
    REQUEST_INVALID = "request.invalid"
    REQUEST_EXPIRED = "request.expired"
    REQUEST_FINGERPRINT_MISMATCH = "request.fingerprint-mismatch"
    COMMAND_PLAN_INVALID = "command-plan.invalid"
    COMMAND_PLAN_ID_MISMATCH = "command-plan.id-mismatch"
    COMMAND_PLAN_REQUEST_MISMATCH = "command-plan.request-mismatch"
    COMMAND_PLAN_VALIDATION_PLAN_MISMATCH = "command-plan.validation-plan-mismatch"
    COMMAND_PLAN_ARGV_MISMATCH = "command-plan.argv-mismatch"
    COMMAND_PLAN_OPERATION_MISMATCH = "command-plan.operation-mismatch"
    DISPATCH_INVALID = "dispatch.invalid"
    DISPATCH_NON_LAUNCH = "dispatch.non-launch"
    DISPATCH_ID_MISMATCH = "dispatch.id-mismatch"
    DISPATCH_IDENTITY_MISMATCH = "dispatch.identity-mismatch"
    AUTHORIZATION_INVALID = "authorization.invalid"
    AUTHORIZATION_NOT_GRANTED = "authorization.not-granted"
    AUTHORIZATION_INACTIVE = "authorization.inactive"
    AUTHORIZATION_MISMATCH = "authorization.mismatch"
    REPOSITORY_MISMATCH = "identity.repository-mismatch"
    REQUESTED_REF_MISMATCH = "identity.requested-ref-mismatch"
    EXPECTED_SHA_MISMATCH = "identity.expected-sha-mismatch"
    RESOLVED_SHA_MISMATCH = "identity.resolved-sha-mismatch"
    PROFILE_MISMATCH = "identity.profile-mismatch"
    DIGEST_MISMATCH = "identity.digest-mismatch"
    PROVIDER_CONFIGURATION_INVALID = "provider.configuration-invalid"
    PROVIDER_CONFIGURATION_FINGERPRINT_MISMATCH = "provider.configuration-fingerprint-mismatch"
    OBSERVATION_INVOCATION_MISMATCH = "observation.invocation-mismatch"
    OBSERVATION_REPOSITORY_MISMATCH = "observation.repository-mismatch"
    OBSERVATION_TESTED_SHA_MISMATCH = "observation.tested-sha-mismatch"
    OBSERVATION_NONTERMINAL = "observation.nonterminal"
    OBSERVATION_UNAVAILABLE = "observation.unavailable"
    OBSERVATION_UNKNOWN = "observation.unknown"
    OBSERVATION_INCOMPLETE = "observation.incomplete"
    PROVIDER_PERMISSION_DENIED = "provider.permission-denied"
    PROVIDER_TIMEOUT = "provider.timeout"
    PROVIDER_CANCELLED = "provider.cancelled"
    PROVIDER_INTERNAL_ERROR = "provider.internal-error"
    PROVIDER_FAILURE = "provider.failure"
    RESULT_AMBIGUOUS = "result.ambiguous"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderCommandEntry:
    operation: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        _bounded_text("operation", self.operation)
        _exact_tuple("argv", self.argv)
        if not self.argv or len(self.argv) > MAX_PROVIDER_ARGV_ITEMS:
            raise ValueError("argv must be non-empty and bounded")
        for item in self.argv:
            _bounded_text("argv item", item)


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildProviderConfiguration:
    schema_version: str = PROVIDER_SCHEMA_VERSION
    project_id: str
    location: str
    runtime_service_account_identity: str
    build_service_account_identity: str
    build_definition_identity: str
    builder_image_identity: str
    validator_dependency_identity: str
    evidence_destination_identity: str
    max_build_timeout_seconds: int
    max_output_bytes: int
    max_diagnostic_bytes: int
    configuration_fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_SCHEMA_VERSION:
            raise ValueError("unsupported provider schema version")
        for name in (
            "project_id",
            "location",
            "runtime_service_account_identity",
            "build_service_account_identity",
            "build_definition_identity",
            "validator_dependency_identity",
            "evidence_destination_identity",
        ):
            _bounded_identity(name, getattr(self, name))
        _bounded_identity("builder_image_identity", self.builder_image_identity)
        if not _DIGEST_IDENTITY_RE.fullmatch(self.builder_image_identity):
            raise ValueError("builder_image_identity must use an immutable sha256 digest")
        _positive_int("max_build_timeout_seconds", self.max_build_timeout_seconds)
        _positive_int("max_output_bytes", self.max_output_bytes)
        _positive_int("max_diagnostic_bytes", self.max_diagnostic_bytes)
        if self.max_build_timeout_seconds > MAX_BUILD_TIMEOUT_SECONDS:
            raise ValueError("build timeout exceeds provider ceiling")
        if self.max_output_bytes > MAX_OUTPUT_BYTES:
            raise ValueError("output bytes exceed provider ceiling")
        if self.max_diagnostic_bytes > MAX_DIAGNOSTIC_BYTES:
            raise ValueError("diagnostic bytes exceed provider ceiling")
        computed = cloud_build_provider_configuration_fingerprint(self)
        if self.configuration_fingerprint:
            _sha256("configuration_fingerprint", self.configuration_fingerprint)
            if self.configuration_fingerprint != computed:
                raise ValueError("configuration fingerprint mismatch")
        object.__setattr__(self, "configuration_fingerprint", computed)


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildProviderInvocation:
    schema_version: str
    request_id: str
    request_revision: int
    request_fingerprint: str
    issue_or_handoff_identity: str
    command_plan_id: str
    validation_plan_id: str
    dispatch_decision_id: str
    dispatch_identity: str
    authorization_id: str
    repository: str
    requested_ref: str
    expected_sha: str
    resolved_sha: str
    profile: str
    selector_version: str
    command_set_digest: str
    fixed_command_entries: tuple[ProviderCommandEntry, ...]
    fixed_argv_identities: tuple[str, ...]
    provider_configuration_fingerprint: str
    invocation_id: str = ""
    execution_authorized: Literal[True] = field(default=True, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_SCHEMA_VERSION:
            raise ValueError("unsupported provider schema version")
        _bounded_identity("request_id", self.request_id)
        _positive_int("request_revision", self.request_revision)
        _sha256("request_fingerprint", self.request_fingerprint)
        for name in (
            "issue_or_handoff_identity",
            "command_plan_id",
            "validation_plan_id",
            "dispatch_decision_id",
            "dispatch_identity",
            "authorization_id",
            "requested_ref",
            "profile",
            "selector_version",
        ):
            _bounded_identity(name, getattr(self, name))
        _repository(self.repository)
        _sha40("expected_sha", self.expected_sha)
        _sha40("resolved_sha", self.resolved_sha)
        _sha256("command_set_digest", self.command_set_digest)
        _sha256("provider_configuration_fingerprint", self.provider_configuration_fingerprint)
        _exact_tuple("fixed_command_entries", self.fixed_command_entries)
        if len(self.fixed_command_entries) > MAX_PROVIDER_COMMANDS:
            raise ValueError("command entries exceed provider ceiling")
        if not all(type(item) is ProviderCommandEntry for item in self.fixed_command_entries):
            raise TypeError("fixed_command_entries must contain exact ProviderCommandEntry values")
        _exact_tuple("fixed_argv_identities", self.fixed_argv_identities)
        if len(self.fixed_argv_identities) != len(self.fixed_command_entries):
            raise ValueError("argv identities must align with command entries")
        for identity in self.fixed_argv_identities:
            _sha256("fixed argv identity", identity)
        computed = cloud_build_provider_invocation_id(self)
        if self.invocation_id:
            _bounded_identity("invocation_id", self.invocation_id)
            if self.invocation_id != computed:
                raise ValueError("invocation ID mismatch")
        object.__setattr__(self, "invocation_id", computed)


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildProviderObservation:
    schema_version: str = PROVIDER_SCHEMA_VERSION
    invocation_id: str
    build_id: str | None
    repository: str
    tested_sha: str | None
    terminal_status: ProviderObservationStatus
    failed_step: str | None
    exit_code: int | None
    observed_at: str
    source_complete: bool
    side_effect_state: ProviderSideEffectState

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_SCHEMA_VERSION:
            raise ValueError("unsupported provider schema version")
        _bounded_identity("invocation_id", self.invocation_id)
        if self.build_id is not None:
            _bounded_identity("build_id", self.build_id)
        _repository(self.repository)
        if self.tested_sha is not None:
            _sha40("tested_sha", self.tested_sha)
        if type(self.terminal_status) is not ProviderObservationStatus:
            raise TypeError("terminal_status must be ProviderObservationStatus")
        if self.failed_step is not None:
            _bounded_text("failed_step", self.failed_step)
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise TypeError("exit_code must be an exact integer or None")
        _canonical_utc("observed_at", self.observed_at)
        if type(self.source_complete) is not bool:
            raise TypeError("source_complete must be an exact boolean")
        if type(self.side_effect_state) is not ProviderSideEffectState:
            raise TypeError("side_effect_state must be ProviderSideEffectState")


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildProviderResult:
    schema_version: str
    status: ProviderStatus
    invocation: CloudBuildProviderInvocation | None
    invocation_id: str | None
    build_id: str | None
    tested_sha: str | None
    reason_codes: tuple[ProviderReason, ...]
    normalized_cloud_build_evidence: CloudBuildResultEvidence | None
    execution_authorized: bool
    side_effect_state: ProviderSideEffectState
    result_id: str = ""
    merge_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_SCHEMA_VERSION:
            raise ValueError("unsupported provider schema version")
        if type(self.status) is not ProviderStatus:
            raise TypeError("status must be ProviderStatus")
        if self.invocation is not None and type(self.invocation) is not CloudBuildProviderInvocation:
            raise TypeError("invocation must be CloudBuildProviderInvocation or None")
        if self.invocation_id is not None:
            _bounded_identity("invocation_id", self.invocation_id)
        if self.build_id is not None:
            _bounded_identity("build_id", self.build_id)
        if self.tested_sha is not None:
            _sha40("tested_sha", self.tested_sha)
        _exact_tuple("reason_codes", self.reason_codes)
        if not self.reason_codes or len(self.reason_codes) > MAX_PROVIDER_REASON_CODES:
            raise ValueError("reason codes must be finite and non-empty")
        if not all(type(item) is ProviderReason for item in self.reason_codes):
            raise TypeError("reason codes must contain exact ProviderReason values")
        ordered = tuple(sorted(set(self.reason_codes), key=lambda item: item.value))
        if self.reason_codes != ordered:
            raise ValueError("reason codes must be sorted and unique")
        if self.normalized_cloud_build_evidence is not None and type(self.normalized_cloud_build_evidence) is not CloudBuildResultEvidence:
            raise TypeError("normalized evidence must be canonical CloudBuildResultEvidence or None")
        if type(self.execution_authorized) is not bool:
            raise TypeError("execution_authorized must be an exact boolean")
        if type(self.side_effect_state) is not ProviderSideEffectState:
            raise TypeError("side_effect_state must be ProviderSideEffectState")
        computed = cloud_build_provider_result_id(self)
        if self.result_id:
            _bounded_identity("result_id", self.result_id)
            if self.result_id != computed:
                raise ValueError("result ID mismatch")
        object.__setattr__(self, "result_id", computed)


def serialize_cloud_build_provider_configuration(value: CloudBuildProviderConfiguration) -> dict[str, object]:
    if type(value) is not CloudBuildProviderConfiguration:
        raise TypeError("configuration must be an exact CloudBuildProviderConfiguration")
    payload = _configuration_payload(value)
    payload["configuration_fingerprint"] = value.configuration_fingerprint
    _bounded_serialized(payload)
    return payload


def cloud_build_provider_configuration_fingerprint(value: CloudBuildProviderConfiguration) -> str:
    return _digest("agent-os-cloud-build-provider-configuration:v1", _configuration_payload(value))


def serialize_cloud_build_provider_invocation(value: CloudBuildProviderInvocation) -> dict[str, object]:
    if type(value) is not CloudBuildProviderInvocation:
        raise TypeError("invocation must be an exact CloudBuildProviderInvocation")
    payload = _invocation_payload(value)
    payload["invocation_id"] = value.invocation_id
    _bounded_serialized(payload)
    return payload


def cloud_build_provider_invocation_id(value: CloudBuildProviderInvocation) -> str:
    return "cloud-build-provider-invocation:" + _digest(
        "agent-os-cloud-build-provider-invocation:v1", _invocation_payload(value)
    )


def serialize_cloud_build_provider_result(value: CloudBuildProviderResult) -> dict[str, object]:
    if type(value) is not CloudBuildProviderResult:
        raise TypeError("result must be an exact CloudBuildProviderResult")
    payload = _result_payload(value)
    payload["result_id"] = value.result_id
    _bounded_serialized(payload)
    return payload


def cloud_build_provider_result_id(value: CloudBuildProviderResult) -> str:
    return "cloud-build-provider-result:" + _digest(
        "agent-os-cloud-build-provider-result:v1", _result_payload(value)
    )


def argv_identity(entry: ProviderCommandEntry) -> str:
    if type(entry) is not ProviderCommandEntry:
        raise TypeError("entry must be an exact ProviderCommandEntry")
    return _digest(
        "agent-os-cloud-build-provider-argv:v1",
        {"operation": entry.operation, "argv": list(entry.argv)},
    )


def _configuration_payload(value: CloudBuildProviderConfiguration) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "project_id": value.project_id,
        "location": value.location,
        "runtime_service_account_identity": value.runtime_service_account_identity,
        "build_service_account_identity": value.build_service_account_identity,
        "build_definition_identity": value.build_definition_identity,
        "builder_image_identity": value.builder_image_identity,
        "validator_dependency_identity": value.validator_dependency_identity,
        "evidence_destination_identity": value.evidence_destination_identity,
        "max_build_timeout_seconds": value.max_build_timeout_seconds,
        "max_output_bytes": value.max_output_bytes,
        "max_diagnostic_bytes": value.max_diagnostic_bytes,
    }


def _invocation_payload(value: CloudBuildProviderInvocation) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "request_id": value.request_id,
        "request_revision": value.request_revision,
        "request_fingerprint": value.request_fingerprint,
        "issue_or_handoff_identity": value.issue_or_handoff_identity,
        "command_plan_id": value.command_plan_id,
        "validation_plan_id": value.validation_plan_id,
        "dispatch_decision_id": value.dispatch_decision_id,
        "dispatch_identity": value.dispatch_identity,
        "authorization_id": value.authorization_id,
        "repository": value.repository,
        "requested_ref": value.requested_ref,
        "expected_sha": value.expected_sha,
        "resolved_sha": value.resolved_sha,
        "profile": value.profile,
        "selector_version": value.selector_version,
        "command_set_digest": value.command_set_digest,
        "fixed_command_entries": [
            {"operation": item.operation, "argv": list(item.argv)}
            for item in value.fixed_command_entries
        ],
        "fixed_argv_identities": list(value.fixed_argv_identities),
        "provider_configuration_fingerprint": value.provider_configuration_fingerprint,
        "execution_authorized": True,
        "merge_authorized": False,
        "side_effects_performed": False,
    }


def _result_payload(value: CloudBuildProviderResult) -> dict[str, object]:
    evidence = value.normalized_cloud_build_evidence
    normalized = None
    if evidence is not None:
        normalized = {
            "build_id": evidence.build_id,
            "tested_sha": evidence.tested_sha,
            "repository": evidence.repository,
            "trigger_id": evidence.trigger_id,
            "invocation_id": evidence.invocation_id,
            "overall_result": evidence.overall_result.value,
            "failed_step": evidence.failed_step,
            "exit_code": evidence.exit_code,
            "observed_at": evidence.observed_at,
            "terminal": evidence.terminal,
            "source_complete": evidence.source_complete,
            "execution_authorized": False,
            "side_effects_performed": False,
        }
    return {
        "schema_version": value.schema_version,
        "status": value.status.value,
        "invocation": serialize_cloud_build_provider_invocation(value.invocation) if value.invocation else None,
        "invocation_id": value.invocation_id,
        "build_id": value.build_id,
        "tested_sha": value.tested_sha,
        "reason_codes": [item.value for item in value.reason_codes],
        "normalized_cloud_build_evidence": normalized,
        "execution_authorized": value.execution_authorized,
        "merge_authorized": False,
        "side_effect_state": value.side_effect_state.value,
    }


def _digest(domain: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\0" + encoded).hexdigest()


def _bounded_serialized(payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_PROVIDER_SERIALIZED_BYTES:
        raise ValueError("provider value exceeds serialized byte ceiling")


def _exact_tuple(name: str, value: object) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")


def _positive_int(name: str, value: object) -> None:
    if type(value) is not int or value <= 0:
        raise TypeError(f"{name} must be a positive exact integer")


def _bounded_text(name: str, value: object) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not value or len(value) > MAX_PROVIDER_STRING_LENGTH:
        raise ValueError(f"{name} must be non-empty and bounded")
    if _CONTROL_RE.search(value):
        raise ValueError(f"{name} contains a control character")
    if _SECRET_RE.search(value):
        raise ValueError(f"{name} contains a secret-like value")


def _bounded_identity(name: str, value: object) -> None:
    _bounded_text(name, value)
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must use bounded identity syntax")


def _repository(value: object) -> None:
    _bounded_text("repository", value)
    if not _REPOSITORY_RE.fullmatch(value):
        raise ValueError("repository must use owner/name syntax")


def _sha40(name: str, value: object) -> None:
    if type(value) is not str or not _SHA40_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase 40-character SHA")


def _sha256(name: str, value: object) -> None:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _canonical_utc(name: str, value: object) -> None:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        raise ValueError(f"{name} must be canonical UTC seconds")
