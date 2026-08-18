"""Append-only recovery store for canonical #1197 dependency-readiness evidence.

The store persists only the bounded, non-authorizing
``DependencyReadinessEvidence`` object.  It never persists a complete
``SingleIssuePilotInput`` or grants execution authority.  Records are keyed by
the existing content-addressed ``dependency-readiness:<sha256>`` identity and
reuse the checkpoint store's atomic/path-safety primitives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    ReproducibilityLevel,
    dependency_readiness_evidence_payload,
)

from .identity import canonical_json_bytes
from .store import (
    CheckpointStoreCapacityExceeded,
    CheckpointStoreIntegrityConflict,
    CheckpointStoreUnavailable,
    _atomic_write,
    _ensure_dir,
    _existing_records_footprint,
    _reject_symlink,
)

MAX_DEPENDENCY_READINESS_BYTES = 32 * 1024
MAX_DEPENDENCY_READINESS_RECORDS = 4096
MAX_DEPENDENCY_READINESS_STORE_BYTES = 64 * 1024 * 1024


class DependencyReadinessNotFound(LookupError):
    """No exact persisted readiness record exists for the requested identity."""


class DependencyReadinessIntegrityError(ValueError):
    """Persisted readiness bytes failed canonical reconstruction."""


@dataclass(frozen=True, slots=True)
class AppendDependencyReadinessOutcome:
    evidence_id: str
    path: Path
    already_present: bool


def serialize_dependency_readiness(evidence: DependencyReadinessEvidence) -> bytes:
    if type(evidence) is not DependencyReadinessEvidence:
        raise TypeError("evidence must be an exact DependencyReadinessEvidence")
    payload = canonical_json_bytes(dependency_readiness_evidence_payload(evidence))
    if len(payload) > MAX_DEPENDENCY_READINESS_BYTES:
        raise ValueError("dependency-readiness evidence exceeds serialized bound")
    return payload


def deserialize_dependency_readiness(payload: bytes | bytearray | memoryview | str) -> DependencyReadinessEvidence:
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if len(raw) > MAX_DEPENDENCY_READINESS_BYTES:
        raise ValueError("dependency-readiness evidence exceeds serialized bound")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dependency-readiness evidence is not canonical JSON") from exc
    if type(decoded) is not dict:
        raise ValueError("dependency-readiness evidence must be an exact object")
    expected = {
        "execution_surface_id", "workspace_identity", "source_sha",
        "required_environment_id", "package_root", "ecosystem",
        "runtime_version", "package_manager_version", "declared_dependency_identity",
        "lock_or_constraints_identity", "install_mode", "source_or_registry_identity",
        "cache_state", "preparation_status", "resolved_dependency_identity",
        "environment_health_evidence_id", "observed_at", "expires_at",
        "reproducibility_level", "reason_codes", "dependency_readiness_evidence_id",
        "execution_authorized", "side_effects_authorized", "retry_attempted",
    }
    if set(decoded) != expected:
        raise ValueError("dependency-readiness evidence contains unknown or missing fields")
    for flag in ("execution_authorized", "side_effects_authorized", "retry_attempted"):
        if decoded[flag] is not False:
            raise ValueError(f"persisted readiness evidence cannot claim {flag}=true")
    if type(decoded["reason_codes"]) is not list:
        raise TypeError("reason_codes must be an exact JSON array")
    evidence = DependencyReadinessEvidence(
        execution_surface_id=decoded["execution_surface_id"],
        workspace_identity=decoded["workspace_identity"],
        source_sha=decoded["source_sha"],
        required_environment_id=decoded["required_environment_id"],
        package_root=decoded["package_root"],
        ecosystem=DependencyEcosystem(decoded["ecosystem"]),
        runtime_version=decoded["runtime_version"],
        package_manager_version=decoded["package_manager_version"],
        declared_dependency_identity=decoded["declared_dependency_identity"],
        lock_or_constraints_identity=decoded["lock_or_constraints_identity"],
        install_mode=DependencyInstallMode(decoded["install_mode"]),
        source_or_registry_identity=decoded["source_or_registry_identity"],
        cache_state=DependencyCacheState(decoded["cache_state"]),
        preparation_status=DependencyPreparationStatus(decoded["preparation_status"]),
        resolved_dependency_identity=decoded["resolved_dependency_identity"],
        environment_health_evidence_id=decoded["environment_health_evidence_id"],
        observed_at=decoded["observed_at"],
        expires_at=decoded["expires_at"],
        reproducibility_level=ReproducibilityLevel(decoded["reproducibility_level"]),
        reason_codes=tuple(decoded["reason_codes"]),
        dependency_readiness_evidence_id=decoded["dependency_readiness_evidence_id"],
    )
    if serialize_dependency_readiness(evidence) != raw:
        raise ValueError("dependency-readiness evidence is not canonical byte form")
    return evidence


def _directory(store_root: Path | str) -> Path:
    return Path(store_root) / "dependency-readiness"


def _filename(evidence_id: str) -> str:
    prefix = "dependency-readiness:"
    if type(evidence_id) is not str or not evidence_id.startswith(prefix):
        raise ValueError("evidence_id must be a canonical dependency-readiness identity")
    digest = evidence_id[len(prefix):]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("evidence_id must be a canonical dependency-readiness identity")
    return f"{digest}.json"


def append_dependency_readiness(store_root: Path | str, evidence: DependencyReadinessEvidence) -> AppendDependencyReadinessOutcome:
    if type(evidence) is not DependencyReadinessEvidence:
        raise TypeError("evidence must be an exact DependencyReadinessEvidence")
    directory = _directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    payload = serialize_dependency_readiness(evidence)
    filename = _filename(evidence.dependency_readiness_evidence_id)
    destination = directory / filename
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if count + 1 > MAX_DEPENDENCY_READINESS_RECORDS or total_bytes + len(payload) > MAX_DEPENDENCY_READINESS_STORE_BYTES:
            raise CheckpointStoreCapacityExceeded("dependency-readiness store is at capacity")
    path, already_present = _atomic_write(directory, filename, payload)
    return AppendDependencyReadinessOutcome(
        evidence_id=evidence.dependency_readiness_evidence_id,
        path=path,
        already_present=already_present,
    )


def load_dependency_readiness(store_root: Path | str, evidence_id: str) -> DependencyReadinessEvidence:
    directory = _directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename(evidence_id)
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise DependencyReadinessNotFound(evidence_id) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    try:
        evidence = deserialize_dependency_readiness(payload)
    except (TypeError, ValueError) as exc:
        raise DependencyReadinessIntegrityError(str(exc)) from exc
    if evidence.dependency_readiness_evidence_id != evidence_id:
        raise CheckpointStoreIntegrityConflict("readiness filename/content identity mismatch")
    return evidence
