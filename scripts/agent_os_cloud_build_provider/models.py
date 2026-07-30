"""Immutable, pure-local Cloud Build provider contracts."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal

PROVIDER_SCHEMA_VERSION = "1.0"
MAX_STRING_LENGTH = 512
MAX_COMMANDS = 32
MAX_ARGV_ITEMS = 32
MAX_REASON_CODES = 32
MAX_SERIALIZED_BYTES = 131_072
MAX_BUILD_TIMEOUT_SECONDS = 7_200
MAX_OUTPUT_BYTES = 10_000_000
MAX_DIAGNOSTIC_BYTES = 65_536

_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET = re.compile(r"(?i)(authorization\s*:|bearer\s+|token\s*[:=]|password\s*[:=]|secret\s*[:=]|api[_-]?key\s*[:=])")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$", re.ASCII)
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_IMAGE_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$", re.ASCII)


class ProviderStatus(str, Enum):
    WORKING = "working"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal-error"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ProviderResultStatus(str, Enum):
    ACCEPTED = "accepted"
    SKIPPED = "skipped"
    MANUAL_REVIEW = "manual-review"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    TERMINAL = "terminal"


class SideEffectState(str, Enum):
    NONE = "none"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class ProviderReason(str, Enum):
    ACCEPTED = "accepted"
    INPUT_INVALID_TYPE = "input.invalid-type"
    INPUT_UNSUPPORTED_SCHEMA = "input.unsupported-schema"
    INPUT_MALFORMED = "input.malformed"
    INPUT_LIMIT_EXCEEDED = "input.limit-exceeded"
    REQUEST_INVALID = "request.invalid"
    REQUEST_FINGERPRINT_MISMATCH = "request.fingerprint-mismatch"
    COMMAND_PLAN_INVALID = "command-plan.invalid"
    COMMAND_PLAN_ID_MISMATCH = "command-plan.id-mismatch"
    DISPATCH_INVALID = "dispatch.invalid"
    DISPATCH_NOT_LAUNCH_ELIGIBLE = "dispatch.not-launch-eligible"
    DISPATCH_IDENTITY_MISMATCH = "dispatch.identity-mismatch"
    AUTHORIZATION_INVALID = "authorization.invalid"
    AUTHORIZATION_NOT_GRANTED = "authorization.not-granted"
    AUTHORIZATION_EXPIRED = "authorization.expired"
    IDENTITY_REPOSITORY_MISMATCH = "identity.repository-mismatch"
    IDENTITY_REF_MISMATCH = "identity.ref-mismatch"
    IDENTITY_EXPECTED_SHA_MISMATCH = "identity.expected-sha-mismatch"
    IDENTITY_RESOLVED_SHA_MISMATCH = "identity.resolved-sha-mismatch"
    IDENTITY_PROFILE_MISMATCH = "identity.profile-mismatch"
    IDENTITY_COMMAND_DIGEST_MISMATCH = "identity.command-digest-mismatch"
    PROVIDER_CONFIG_INVALID = "provider-config.invalid"
    PROVIDER_CONFIG_FINGERPRINT_MISMATCH = "provider-config.fingerprint-mismatch"
    OBSERVATION_INVALID = "observation.invalid"
    OBSERVATION_INVOCATION_MISMATCH = "observation.invocation-mismatch"
    OBSERVATION_REPOSITORY_MISMATCH = "observation.repository-mismatch"
    OBSERVATION_TESTED_SHA_MISMATCH = "observation.tested-sha-mismatch"
    PROVIDER_NONTERMINAL = "provider.nonterminal"
    PROVIDER_PERMISSION_DENIED = "provider.permission-denied"
    PROVIDER_FAILURE = "provider.failure"
    PROVIDER_TIMEOUT = "provider.timeout"
    PROVIDER_CANCELLED = "provider.cancelled"
    PROVIDER_INTERNAL_ERROR = "provider.internal-error"
    PROVIDER_UNAVAILABLE = "provider.unavailable"
    PROVIDER_UNKNOWN_OUTCOME = "provider.unknown-outcome"


def _text(name: str, value: object, *, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value or len(value) > MAX_STRING_LENGTH:
        raise ValueError(f"{name} must be a bounded exact string")
    if _CONTROL.search(value) or _SECRET.search(value):
        raise ValueError(f"{name} contains forbidden content")
    if pattern is not None and not pattern.fullmatch(value):
        raise ValueError(f"{name} has invalid syntax")
    return value


def _positive_int(name: str, value: object, ceiling: int) -> int:
    if type(value) is not int or value <= 0 or value > ceiling:
        raise ValueError(f"{name} must be a positive exact integer within bounds")
    return value


def _canonical_bytes(payload: object) -> bytes:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_SERIALIZED_BYTES:
        raise ValueError("serialized provider contract exceeds limit")
    return encoded


def _semantic_id(domain: bytes, payload: object, prefix: str) -> str:
    return prefix + hashlib.sha256(domain + b"\0" + _canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderCommandEntry:
    operation: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        _text("operation", self.operation, pattern=_IDENTIFIER)
        if type(self.argv) is not tuple or not self.argv or len(self.argv) > MAX_ARGV_ITEMS:
            raise ValueError("argv must be a bounded non-empty exact tuple")
        for item in self.argv:
            _text("argv item", item)


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildProviderConfiguration:
    schema_version: str
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
            raise ValueError("unsupported provider schema")
        for name in (
            "project_id", "location", "runtime_service_account_identity",
            "build_service_account_identity", "build_definition_identity",
            "validator_dependency_identity", "evidence_destination_identity",
        ):
            _text(name, getattr(self, name), pattern=_IDENTIFIER)
        _text("builder_image_identity", self.builder_image_identity, pattern=_IMAGE_DIGEST)
        _positive_int("max_build_timeout_seconds", self.max_build_timeout_seconds, MAX_BUILD_TIMEOUT_SECONDS)
        _positive_int("max_output_bytes", self.max_output_bytes, MAX_OUTPUT_BYTES)
        _positive_int("max_diagnostic_bytes", self.max_diagnostic_bytes, MAX_DIAGNOSTIC_BYTES)
        computed = cloud_build_provider_configuration_fingerprint(self, verify=False)
        if self.configuration_fingerprint and self.configuration_fingerprint != computed:
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
            raise ValueError("unsupported provider schema")
        for name in (
            "request_id", "issue_or_handoff_identity", "command_plan_id", "validation_plan_id",
            "dispatch_decision_id", "dispatch_identity", "authorization_id", "requested_ref",
            "profile", "selector_version",
        ):
            _text(name, getattr(self, name))
        _positive_int("request_revision", self.request_revision, 2_147_483_647)
        _text("repository", self.repository, pattern=_REPOSITORY)
        for name in ("expected_sha", "resolved_sha"):
            _text(name, getattr(self, name), pattern=_SHA40)
        for name in ("request_fingerprint", "command_set_digest", "provider_configuration_fingerprint"):
            _text(name, getattr(self, name), pattern=_SHA256)
        if type(self.fixed_command_entries) is not tuple or not self.fixed_command_entries or len(self.fixed_command_entries) > MAX_COMMANDS:
            raise ValueError("fixed command entries must be bounded and non-empty")
        if not all(type(item) is ProviderCommandEntry for item in self.fixed_command_entries):
            raise TypeError("fixed command entries must use exact ProviderCommandEntry values")
        if type(self.fixed_argv_identities) is not tuple or len(self.fixed_argv_identities) != len(self.fixed_command_entries):
            raise ValueError("argv identities must align with command entries")
        if not all(type(item) is str and _SHA256.fullmatch(item) for item in self.fixed_argv_identities):
            raise ValueError("argv identities must be SHA-256 digests")
        computed = cloud_build_provider_invocation_id(self, verify=False)
        if self.invocation_id and self.invocation_id != computed:
            raise ValueError("invocation ID mismatch")
        object.__setattr__(self, "invocation_id", computed)


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildProviderObservation:
    schema_version: str
    invocation_id: str
    build_id: str | None
    repository: str
    tested_sha: str | None
    provider_status: ProviderStatus
    failed_step: str | None
    exit_code: int | None
    observed_at: str
    source_complete: bool
    side_effect_state: SideEffectState

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_SCHEMA_VERSION:
            raise ValueError("unsupported provider schema")
        _text("invocation_id", self.invocation_id)
        _text("repository", self.repository, pattern=_REPOSITORY)
        _text("observed_at", self.observed_at)
        if self.build_id is not None:
            _text("build_id", self.build_id)
        if self.tested_sha is not None:
            _text("tested_sha", self.tested_sha, pattern=_SHA40)
        if type(self.provider_status) is not ProviderStatus:
            raise TypeError("provider_status must be ProviderStatus")
        if type(self.side_effect_state) is not SideEffectState:
            raise TypeError("side_effect_state must be SideEffectState")
        if type(self.source_complete) is not bool:
            raise TypeError("source_complete must be an exact boolean")
        if self.failed_step is not None:
            _text("failed_step", self.failed_step)
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise TypeError("exit_code must be an exact integer or None")


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildProviderResult:
    schema_version: str
    status: ProviderResultStatus
    invocation: CloudBuildProviderInvocation | None
    invocation_id: str | None
    build_id: str | None
    tested_sha: str | None
    reason_codes: tuple[ProviderReason, ...]
    normalized_cloud_build_evidence: Any | None
    execution_authorized: bool
    side_effect_state: SideEffectState
    result_id: str = ""
    merge_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_SCHEMA_VERSION:
            raise ValueError("unsupported provider schema")
        if type(self.status) is not ProviderResultStatus:
            raise TypeError("status must be ProviderResultStatus")
        if self.invocation is not None and type(self.invocation) is not CloudBuildProviderInvocation:
            raise TypeError("invocation must be exact CloudBuildProviderInvocation or None")
        if type(self.reason_codes) is not tuple or not self.reason_codes or len(self.reason_codes) > MAX_REASON_CODES:
            raise ValueError("reason codes must be a bounded non-empty tuple")
        if not all(type(item) is ProviderReason for item in self.reason_codes):
            raise TypeError("reason codes must contain exact ProviderReason values")
        if tuple(sorted(set(self.reason_codes), key=lambda item: item.value)) != self.reason_codes:
            raise ValueError("reason codes must be sorted and unique")
        if type(self.execution_authorized) is not bool:
            raise TypeError("execution_authorized must be exact bool")
        if type(self.side_effect_state) is not SideEffectState:
            raise TypeError("side_effect_state must be SideEffectState")
        computed = cloud_build_provider_result_id(self, verify=False)
        if self.result_id and self.result_id != computed:
            raise ValueError("result ID mismatch")
        object.__setattr__(self, "result_id", computed)


def serialize_cloud_build_provider_configuration(value: CloudBuildProviderConfiguration) -> dict[str, object]:
    if type(value) is not CloudBuildProviderConfiguration:
        raise TypeError("configuration must be exact CloudBuildProviderConfiguration")
    payload = asdict(value)
    _canonical_bytes(payload)
    return payload


def cloud_build_provider_configuration_fingerprint(value: CloudBuildProviderConfiguration, *, verify: bool = True) -> str:
    payload = {k: v for k, v in asdict(value).items() if k != "configuration_fingerprint"}
    fingerprint = hashlib.sha256(b"agent-os-cloud-build-provider-config:v1\0" + _canonical_bytes(payload)).hexdigest()
    if verify and value.configuration_fingerprint != fingerprint:
        raise ValueError("configuration fingerprint mismatch")
    return fingerprint


def _invocation_payload(value: CloudBuildProviderInvocation) -> dict[str, object]:
    payload = asdict(value)
    payload.pop("invocation_id", None)
    return payload


def serialize_cloud_build_provider_invocation(value: CloudBuildProviderInvocation) -> dict[str, object]:
    if type(value) is not CloudBuildProviderInvocation:
        raise TypeError("invocation must be exact CloudBuildProviderInvocation")
    cloud_build_provider_invocation_id(value)
    payload = asdict(value)
    _canonical_bytes(payload)
    return payload


def cloud_build_provider_invocation_id(value: CloudBuildProviderInvocation, *, verify: bool = True) -> str:
    result = _semantic_id(b"agent-os-cloud-build-provider-invocation:v1", _invocation_payload(value), "cloud-build-invocation:")
    if verify and value.invocation_id != result:
        raise ValueError("invocation ID mismatch")
    return result


def _result_payload(value: CloudBuildProviderResult) -> dict[str, object]:
    evidence = value.normalized_cloud_build_evidence
    evidence_payload = None
    if evidence is not None:
        evidence_payload = {
            "build_id": getattr(evidence, "build_id", None),
            "tested_sha": getattr(evidence, "tested_sha", None),
            "repository": getattr(evidence, "repository", None),
            "trigger_id": getattr(evidence, "trigger_id", None),
            "invocation_id": getattr(evidence, "invocation_id", None),
            "overall_result": getattr(getattr(evidence, "overall_result", None), "value", None),
            "failed_step": getattr(evidence, "failed_step", None),
            "exit_code": getattr(evidence, "exit_code", None),
            "observed_at": getattr(evidence, "observed_at", None),
            "terminal": getattr(evidence, "terminal", None),
            "source_complete": getattr(evidence, "source_complete", None),
        }
    return {
        "schema_version": value.schema_version,
        "status": value.status.value,
        "invocation_id": value.invocation_id,
        "build_id": value.build_id,
        "tested_sha": value.tested_sha,
        "reason_codes": [item.value for item in value.reason_codes],
        "normalized_cloud_build_evidence": evidence_payload,
        "execution_authorized": value.execution_authorized,
        "merge_authorized": False,
        "side_effect_state": value.side_effect_state.value,
    }


def serialize_cloud_build_provider_result(value: CloudBuildProviderResult) -> dict[str, object]:
    if type(value) is not CloudBuildProviderResult:
        raise TypeError("result must be exact CloudBuildProviderResult")
    cloud_build_provider_result_id(value)
    payload = _result_payload(value)
    payload["result_id"] = value.result_id
    _canonical_bytes(payload)
    return payload


def cloud_build_provider_result_id(value: CloudBuildProviderResult, *, verify: bool = True) -> str:
    result = _semantic_id(b"agent-os-cloud-build-provider-result:v1", _result_payload(value), "cloud-build-provider-result:")
    if verify and value.result_id != result:
        raise ValueError("result ID mismatch")
    return result


def command_argv_identity(entry: ProviderCommandEntry) -> str:
    return hashlib.sha256(b"agent-os-provider-argv:v1\0" + _canonical_bytes(asdict(entry))).hexdigest()
