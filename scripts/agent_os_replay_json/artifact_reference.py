from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Iterable

SOURCE_KIND = "chrome-devtools-recorder"
CONTRACT_VERSION = "recorder-artifact-ref/v1"
_SHA256_HEX_LENGTH = 64
_MAX_REF_LENGTH = 1024
_MAX_DISPLAY_LENGTH = 256
_MAX_WARNING_LENGTH = 200
_MAX_WARNINGS = 8

_RJ1 = {"analyzed", "pending", "failed"}
_RJ2 = {"cleaned-candidate-available", "pending", "rejected"}
_RJ3 = {"conformant", "pending", "failed"}
_RJ4 = {"equivalent", "pending", "failed", "indeterminate"}
_PRIVACY = {"pending", "reviewed-safe-reference", "restricted"}


def fingerprint_artifact(data: bytes) -> str:
    if type(data) is not bytes:
        raise TypeError("artifact data must be bytes")
    return sha256(data).hexdigest()


def _bounded_text(value: str, *, field: str, limit: int) -> str:
    if type(value) is not str or not value or len(value) > limit:
        raise ValueError(f"{field} must be non-empty text within {limit} characters")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError(f"{field} contains control characters")
    return value


def _sha256(value: str, *, field: str) -> str:
    if type(value) is not str or len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(f"{field} must be a sha256 hex digest")
    if value.lower() != value or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{field} must be a lowercase sha256 hex digest")
    return value


@dataclass(frozen=True)
class RecorderArtifactRef:
    recording_id: str
    source_kind: str
    artifact_ref: str
    sha256: str
    byte_length: int
    recorded_at: str | None
    privacy_review_state: str
    parent_sha256: str | None
    derivation_kind: str | None
    producer_contract_version: str = CONTRACT_VERSION
    display_name: str | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.recording_id, field="recording_id", limit=128)
        if self.recording_id != f"recorder:{self.sha256}":
            raise ValueError("recording_id must be content-addressed from sha256")
        if self.source_kind != SOURCE_KIND:
            raise ValueError("unsupported source_kind")
        _bounded_text(self.artifact_ref, field="artifact_ref", limit=_MAX_REF_LENGTH)
        _sha256(self.sha256, field="sha256")
        if type(self.byte_length) is not int or self.byte_length < 0:
            raise ValueError("byte_length must be a non-negative integer")
        if self.recorded_at is not None:
            _bounded_text(self.recorded_at, field="recorded_at", limit=64)
        if self.privacy_review_state not in _PRIVACY:
            raise ValueError("unsupported privacy_review_state")
        if self.parent_sha256 is None:
            if self.derivation_kind is not None:
                raise ValueError("original artifact cannot declare derivation_kind")
        else:
            _sha256(self.parent_sha256, field="parent_sha256")
            if self.parent_sha256 == self.sha256:
                raise ValueError("derived artifact cannot reference itself")
            _bounded_text(self.derivation_kind or "", field="derivation_kind", limit=64)
        if self.producer_contract_version != CONTRACT_VERSION:
            raise ValueError("unsupported producer_contract_version")
        if self.display_name is not None:
            _bounded_text(self.display_name, field="display_name", limit=_MAX_DISPLAY_LENGTH)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecorderPipelineStatuses:
    rj1: str = "pending"
    rj2: str = "pending"
    rj3: str = "pending"
    rj4: str = "pending"

    def __post_init__(self) -> None:
        for field, value, allowed in (
            ("rj1", self.rj1, _RJ1),
            ("rj2", self.rj2, _RJ2),
            ("rj3", self.rj3, _RJ3),
            ("rj4", self.rj4, _RJ4),
        ):
            if value not in allowed:
                raise ValueError(f"unsupported {field} status")


def build_artifact_ref(
    data: bytes,
    *,
    artifact_ref: str,
    privacy_review_state: str = "pending",
    recorded_at: str | None = None,
    parent: RecorderArtifactRef | None = None,
    derivation_kind: str | None = None,
    display_name: str | None = None,
) -> RecorderArtifactRef:
    digest = fingerprint_artifact(data)
    if parent is None and derivation_kind is not None:
        raise ValueError("derivation_kind requires parent artifact")
    if parent is not None and derivation_kind is None:
        raise ValueError("derived artifact requires derivation_kind")
    return RecorderArtifactRef(
        recording_id=f"recorder:{digest}",
        source_kind=SOURCE_KIND,
        artifact_ref=artifact_ref,
        sha256=digest,
        byte_length=len(data),
        recorded_at=recorded_at,
        privacy_review_state=privacy_review_state,
        parent_sha256=None if parent is None else parent.sha256,
        derivation_kind=derivation_kind,
        display_name=display_name,
    )


def verify_artifact_bytes(ref: RecorderArtifactRef, data: bytes) -> bool:
    digest = fingerprint_artifact(data)
    if len(data) != ref.byte_length or digest != ref.sha256:
        raise ValueError("artifact content identity mismatch")
    return True


def validate_lineage(
    parent: RecorderArtifactRef,
    child: RecorderArtifactRef,
    *,
    ancestor_digests: Iterable[str] = (),
) -> bool:
    if child.parent_sha256 != parent.sha256:
        raise ValueError("derived artifact parent digest mismatch")
    ancestors = {_sha256(value, field="ancestor_digest") for value in ancestor_digests}
    if child.sha256 in ancestors or parent.sha256 == child.sha256:
        raise ValueError("artifact lineage cycle detected")
    return True


def build_notion_projection(
    ref: RecorderArtifactRef,
    statuses: RecorderPipelineStatuses,
    *,
    modeling_sequence_ref: str,
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    _bounded_text(modeling_sequence_ref, field="modeling_sequence_ref", limit=256)
    bounded_warnings: list[str] = []
    for warning in warnings:
        if len(bounded_warnings) >= _MAX_WARNINGS:
            break
        bounded_warnings.append(
            _bounded_text(warning, field="warning", limit=_MAX_WARNING_LENGTH)
        )
    return {
        "schema": "recorder-evidence-reference/v1",
        "recording_id": ref.recording_id,
        "recording": ref.display_name or ref.recording_id,
        "source": ref.artifact_ref,
        "fingerprint": ref.sha256[:12],
        "sha256": ref.sha256,
        "byte_length": ref.byte_length,
        "privacy_review_state": ref.privacy_review_state,
        "parent_sha256": ref.parent_sha256,
        "derivation_kind": ref.derivation_kind,
        "rj1": statuses.rj1,
        "rj2": statuses.rj2,
        "rj3": statuses.rj3,
        "rj4": statuses.rj4,
        "modeling_sequence": modeling_sequence_ref,
        "warnings": bounded_warnings,
    }
