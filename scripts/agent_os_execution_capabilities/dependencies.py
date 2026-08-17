from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .reason_codes import normalize_reason_codes

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_MAX_ITEMS = 64
_MAX_TEXT = 4096


class DependencyEcosystem(str, Enum):
    PYTHON_PIP = "python-pip"
    NODE_NPM = "node-npm"


class DependencyInstallMode(str, Enum):
    NORMAL = "normal"
    QUALIFICATION_ONLY = "qualification-only"
    ABSENT_AUTHORIZED_LOCK_GENERATION = "absent-authorized-lock-generation"


class DependencyCacheState(str, Enum):
    NOT_APPLICABLE = "not-applicable"
    CURRENT_COMPLETE = "current-complete"
    STALE = "stale"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class DependencyPreparationStatus(str, Enum):
    READY = "ready"
    PREPARATION_REQUIRED = "preparation-required"
    SOURCE_UPDATE_REQUIRED = "source-update-required"
    BLOCKED = "blocked"
    FAILED = "failed"


class ReproducibilityLevel(str, Enum):
    DECLARED = "declared"
    RESOLVED = "resolved"
    LOCKED = "locked"
    HASH_VERIFIED = "hash-verified"


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise TypeError(f"{name} must be non-empty NUL-free exact text")
    if len(value.encode("utf-8")) > _MAX_TEXT:
        raise ValueError(f"{name} exceeds the bounded byte length")
    return value


def _relative_path(value: object, name: str, *, allow_root: bool = False) -> str:
    text = _bounded_text(value, name)
    if allow_root and text == ".":
        return text
    if "\\" in text or text.startswith("/") or posixpath.normpath(text) != text:
        raise ValueError(f"{name} must be a canonical repository-relative POSIX path")
    if any(part in ("", ".", "..") for part in text.split("/")):
        raise ValueError(f"{name} must not contain empty, dot, or parent segments")
    return text


def _sha256(value: object, name: str) -> str:
    text = _bounded_text(value, name)
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _sha40(value: object, name: str) -> str:
    text = _bounded_text(value, name)
    if not _SHA40_RE.fullmatch(text):
        raise ValueError(f"{name} must be a full lowercase commit SHA")
    return text


def _identifier(value: object, name: str) -> str:
    text = _bounded_text(value, name)
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{name} contains unsupported characters")
    return text


def _sorted_unique(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a tuple or list of strings")
    items = tuple(values)
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"{name} exceeds the bounded item count")
    for item in items:
        _identifier(item, name)
    canonical = tuple(sorted(set(items)))
    if tuple(items) != canonical:
        raise ValueError(f"{name} must be sorted and unique")
    return canonical


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _content_id(prefix: str, payload: object) -> str:
    digest = hashlib.sha256(
        prefix.encode("utf-8") + b"\0" + _canonical_bytes(payload)
    ).hexdigest()
    return f"{prefix}:{digest}"


def _utc_datetime(value: object, name: str) -> datetime:
    text = _bounded_text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyArtifactIdentity:
    relative_path: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relative_path", _relative_path(self.relative_path, "relative_path")
        )
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalProjectRequirement:
    relative_path: str
    sha256: str
    editable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relative_path", _relative_path(self.relative_path, "relative_path")
        )
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        if type(self.editable) is not bool:
            raise TypeError("editable must be an exact boolean")


@dataclass(frozen=True, slots=True, kw_only=True)
class QualificationOnlyDependencyPin:
    package: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "package", _identifier(self.package, "package"))
        object.__setattr__(self, "version", _identifier(self.version, "version"))
        if any(token in self.version for token in (">", "<", "~", "*", ",", " ")):
            raise ValueError("qualification-only version must be an exact pin")

    @property
    def requirement(self) -> str:
        return f"{self.package}=={self.version}"


@dataclass(frozen=True, slots=True, kw_only=True)
class RequiredEnvironmentSpec:
    ecosystem: DependencyEcosystem
    package_root: str
    runtime_requirement: str
    dependency_manifest_identity: DependencyArtifactIdentity
    lock_or_constraints_identity: DependencyArtifactIdentity | None
    install_mode: DependencyInstallMode
    approved_source_identity: str
    required_validation_command_ids: tuple[str, ...]
    local_project_requirements: tuple[LocalProjectRequirement, ...] = ()
    qualification_only_pins: tuple[QualificationOnlyDependencyPin, ...] = ()
    required_environment_id: str = ""

    def __post_init__(self) -> None:
        if type(self.ecosystem) is not DependencyEcosystem:
            raise TypeError("ecosystem must be exact DependencyEcosystem")
        if type(self.install_mode) is not DependencyInstallMode:
            raise TypeError("install_mode must be exact DependencyInstallMode")
        object.__setattr__(
            self,
            "package_root",
            _relative_path(self.package_root, "package_root", allow_root=True),
        )
        object.__setattr__(
            self,
            "runtime_requirement",
            _bounded_text(self.runtime_requirement, "runtime_requirement"),
        )
        if type(self.dependency_manifest_identity) is not DependencyArtifactIdentity:
            raise TypeError(
                "dependency_manifest_identity must be exact DependencyArtifactIdentity"
            )
        if (
            self.lock_or_constraints_identity is not None
            and type(self.lock_or_constraints_identity) is not DependencyArtifactIdentity
        ):
            raise TypeError(
                "lock_or_constraints_identity must be exact DependencyArtifactIdentity or None"
            )
        projects = tuple(self.local_project_requirements)
        if len(projects) > _MAX_ITEMS or any(
            type(item) is not LocalProjectRequirement for item in projects
        ):
            raise TypeError("local_project_requirements is malformed")
        if tuple(sorted(projects, key=lambda item: item.relative_path)) != projects:
            raise ValueError("local_project_requirements must be sorted")
        pins = tuple(self.qualification_only_pins)
        if len(pins) > _MAX_ITEMS or any(
            type(item) is not QualificationOnlyDependencyPin for item in pins
        ):
            raise TypeError("qualification_only_pins is malformed")
        if tuple(sorted(pins, key=lambda item: (item.package, item.version))) != pins:
            raise ValueError("qualification_only_pins must be sorted")
        if pins and self.install_mode is not DependencyInstallMode.QUALIFICATION_ONLY:
            raise ValueError(
                "qualification-only pins require qualification-only install mode"
            )
        if self.install_mode is DependencyInstallMode.QUALIFICATION_ONLY and not pins:
            raise ValueError(
                "qualification-only install mode requires at least one exact pin"
            )
        if self.install_mode is DependencyInstallMode.ABSENT_AUTHORIZED_LOCK_GENERATION:
            if (
                self.ecosystem is not DependencyEcosystem.NODE_NPM
                or self.lock_or_constraints_identity is not None
            ):
                raise ValueError(
                    "authorized lock generation is only valid for Node/npm without a lock"
                )
        object.__setattr__(
            self,
            "approved_source_identity",
            _identifier(self.approved_source_identity, "approved_source_identity"),
        )
        object.__setattr__(
            self,
            "required_validation_command_ids",
            _sorted_unique(
                self.required_validation_command_ids,
                "required_validation_command_ids",
            ),
        )
        payload = required_environment_spec_payload(self, include_id=False)
        expected = _content_id("required-environment", payload)
        if self.required_environment_id and self.required_environment_id != expected:
            raise ValueError("required_environment_id does not match spec content")
        object.__setattr__(self, "required_environment_id", expected)


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyReadinessEvidence:
    execution_surface_id: str
    workspace_identity: str
    source_sha: str
    required_environment_id: str
    package_root: str
    ecosystem: DependencyEcosystem
    runtime_version: str
    package_manager_version: str
    declared_dependency_identity: str
    lock_or_constraints_identity: str | None
    install_mode: DependencyInstallMode
    source_or_registry_identity: str
    cache_state: DependencyCacheState
    preparation_status: DependencyPreparationStatus
    resolved_dependency_identity: str | None
    environment_health_evidence_id: str
    observed_at: str
    expires_at: str
    reproducibility_level: ReproducibilityLevel
    reason_codes: tuple[str, ...] = ()
    dependency_readiness_evidence_id: str = ""
    execution_authorized: bool = field(default=False, init=False)
    side_effects_authorized: bool = field(default=False, init=False)
    retry_attempted: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in (
            "execution_surface_id",
            "workspace_identity",
            "required_environment_id",
            "runtime_version",
            "package_manager_version",
            "declared_dependency_identity",
            "source_or_registry_identity",
            "environment_health_evidence_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "source_sha", _sha40(self.source_sha, "source_sha"))
        object.__setattr__(
            self,
            "package_root",
            _relative_path(self.package_root, "package_root", allow_root=True),
        )
        if self.lock_or_constraints_identity is not None:
            object.__setattr__(
                self,
                "lock_or_constraints_identity",
                _identifier(
                    self.lock_or_constraints_identity,
                    "lock_or_constraints_identity",
                ),
            )
        if self.resolved_dependency_identity is not None:
            object.__setattr__(
                self,
                "resolved_dependency_identity",
                _identifier(
                    self.resolved_dependency_identity,
                    "resolved_dependency_identity",
                ),
            )
        for name, enum_type in (
            ("ecosystem", DependencyEcosystem),
            ("install_mode", DependencyInstallMode),
            ("cache_state", DependencyCacheState),
            ("preparation_status", DependencyPreparationStatus),
            ("reproducibility_level", ReproducibilityLevel),
        ):
            if type(getattr(self, name)) is not enum_type:
                raise TypeError(f"{name} must be exact {enum_type.__name__}")
        object.__setattr__(
            self, "reason_codes", normalize_reason_codes(self.reason_codes)
        )
        observed = _utc_datetime(self.observed_at, "observed_at")
        expires = _utc_datetime(self.expires_at, "expires_at")
        if expires <= observed:
            raise ValueError("expires_at must be later than observed_at")
        if (
            self.preparation_status is DependencyPreparationStatus.READY
            and not self.resolved_dependency_identity
        ):
            raise ValueError("READY evidence requires resolved_dependency_identity")
        if (
            self.preparation_status is DependencyPreparationStatus.READY
            and self.reason_codes
        ):
            raise ValueError("READY evidence cannot carry blocker reason codes")
        payload = dependency_readiness_evidence_payload(self, include_id=False)
        expected = _content_id("dependency-readiness", payload)
        if (
            self.dependency_readiness_evidence_id
            and self.dependency_readiness_evidence_id != expected
        ):
            raise ValueError(
                "dependency_readiness_evidence_id does not match evidence content"
            )
        object.__setattr__(
            self, "dependency_readiness_evidence_id", expected
        )

    def is_current(self, at: str) -> bool:
        moment = _utc_datetime(at, "at")
        return _utc_datetime(self.observed_at, "observed_at") <= moment < _utc_datetime(
            self.expires_at, "expires_at"
        )


def required_environment_spec_payload(
    spec: RequiredEnvironmentSpec, *, include_id: bool = True
) -> dict[str, Any]:
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    payload: dict[str, Any] = {
        "ecosystem": spec.ecosystem.value,
        "package_root": spec.package_root,
        "runtime_requirement": spec.runtime_requirement,
        "dependency_manifest_identity": asdict(spec.dependency_manifest_identity),
        "lock_or_constraints_identity": (
            None
            if spec.lock_or_constraints_identity is None
            else asdict(spec.lock_or_constraints_identity)
        ),
        "install_mode": spec.install_mode.value,
        "local_project_requirements": [
            asdict(item) for item in spec.local_project_requirements
        ],
        "qualification_only_pins": [
            asdict(item) for item in spec.qualification_only_pins
        ],
        "approved_source_identity": spec.approved_source_identity,
        "required_validation_command_ids": list(spec.required_validation_command_ids),
    }
    if include_id:
        payload["required_environment_id"] = spec.required_environment_id
    return payload


def dependency_readiness_evidence_payload(
    evidence: DependencyReadinessEvidence, *, include_id: bool = True
) -> dict[str, Any]:
    if type(evidence) is not DependencyReadinessEvidence:
        raise TypeError("evidence must be exact DependencyReadinessEvidence")
    payload: dict[str, Any] = {
        "execution_surface_id": evidence.execution_surface_id,
        "workspace_identity": evidence.workspace_identity,
        "source_sha": evidence.source_sha,
        "required_environment_id": evidence.required_environment_id,
        "package_root": evidence.package_root,
        "ecosystem": evidence.ecosystem.value,
        "runtime_version": evidence.runtime_version,
        "package_manager_version": evidence.package_manager_version,
        "declared_dependency_identity": evidence.declared_dependency_identity,
        "lock_or_constraints_identity": evidence.lock_or_constraints_identity,
        "install_mode": evidence.install_mode.value,
        "source_or_registry_identity": evidence.source_or_registry_identity,
        "cache_state": evidence.cache_state.value,
        "preparation_status": evidence.preparation_status.value,
        "resolved_dependency_identity": evidence.resolved_dependency_identity,
        "environment_health_evidence_id": evidence.environment_health_evidence_id,
        "observed_at": evidence.observed_at,
        "expires_at": evidence.expires_at,
        "reproducibility_level": evidence.reproducibility_level.value,
        "reason_codes": list(evidence.reason_codes),
        "execution_authorized": False,
        "side_effects_authorized": False,
        "retry_attempted": False,
    }
    if include_id:
        payload["dependency_readiness_evidence_id"] = (
            evidence.dependency_readiness_evidence_id
        )
    return payload
