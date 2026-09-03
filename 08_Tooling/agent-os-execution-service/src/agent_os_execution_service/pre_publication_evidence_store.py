"""Checkpoint-root persistence adapter for #1412/#1799 producer evidence.

Both v1.1 phases reuse the existing ``pre-publication-producer-evidence``
namespace. Source evidence may be persisted before a checkpoint exists;
checkpoint-bound evidence (including legacy v1.0) still requires the exact
matching durable #895 checkpoint. The historical public loader remains the
publication-facing loader and explicitly rejects source-phase evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.agent_os_execution_checkpoint.store import (
    CheckpointStoreCapacityExceeded,
    CheckpointStoreIntegrityConflict,
    CheckpointStoreUnavailable,
    _atomic_write,
    _ensure_dir,
    _existing_records_footprint,
    _reject_symlink,
    load_checkpoint_by_id,
)

from .pre_publication_evidence_capsule import (
    CHECKPOINT_BOUND_PHASE,
    SOURCE_PHASE,
    PrePublicationEvidenceCapsule,
    deserialize_pre_publication_evidence,
    serialize_pre_publication_evidence,
)

MAX_CAPSULES = 4096
MAX_CAPSULE_STORE_BYTES = 256 * 1024 * 1024
STORE_NAMESPACE = "pre-publication-producer-evidence"


class PrePublicationEvidenceNotFound(LookupError):
    """Raised when one exact capsule identity is not present in the store."""


@dataclass(frozen=True, slots=True)
class AppendPrePublicationEvidenceOutcome:
    capsule_id: str
    path: Path
    already_present: bool


def _directory(store_root: Path | str) -> Path:
    return Path(store_root) / STORE_NAMESPACE


def _filename(capsule_id: str) -> str:
    prefix = "pre-publication-evidence:"
    if type(capsule_id) is not str or not capsule_id.startswith(prefix):
        raise ValueError("capsule_id is malformed")
    digest = capsule_id.removeprefix(prefix)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("capsule_id is malformed")
    return f"{digest}.json"


def _verify_durable_checkpoint(store_root: Path | str, capsule: PrePublicationEvidenceCapsule) -> None:
    if capsule.phase != CHECKPOINT_BOUND_PHASE or capsule.checkpoint_id is None:
        raise CheckpointStoreIntegrityConflict("checkpoint-bound producer evidence is required")
    durable = load_checkpoint_by_id(store_root, capsule.candidate_packet.issue_number, capsule.checkpoint_id)
    packet = capsule.candidate_packet
    if (
        durable.checkpoint_id != capsule.checkpoint_id
        or durable.repository.casefold() != packet.repository.casefold()
        or durable.issue_number != packet.issue_number
        or durable.invocation_id != packet.invocation_id
        or durable.branch != capsule.candidate_branch
        or durable.source_sha != packet.candidate_sha
        or durable.tested_sha != packet.tested_sha
        or (capsule.execution_id is not None and durable.execution_id != capsule.execution_id)
    ):
        raise CheckpointStoreIntegrityConflict("durable checkpoint does not bind to producer evidence")


def append_pre_publication_evidence(store_root: Path | str, capsule: PrePublicationEvidenceCapsule) -> AppendPrePublicationEvidenceOutcome:
    """Persist one source or checkpoint-bound capsule in the existing namespace."""
    if type(capsule) is not PrePublicationEvidenceCapsule:
        raise TypeError("capsule must be an exact PrePublicationEvidenceCapsule")
    if capsule.phase == CHECKPOINT_BOUND_PHASE:
        _verify_durable_checkpoint(store_root, capsule)
    elif capsule.phase != SOURCE_PHASE:
        raise CheckpointStoreIntegrityConflict("unsupported producer evidence phase")

    directory = _directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    payload = serialize_pre_publication_evidence(capsule)
    destination = directory / _filename(capsule.capsule_id)
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if count + 1 > MAX_CAPSULES or total_bytes + len(payload) > MAX_CAPSULE_STORE_BYTES:
            raise CheckpointStoreCapacityExceeded("pre-publication evidence store is at capacity")
    path, already_present = _atomic_write(directory, destination.name, payload)
    return AppendPrePublicationEvidenceOutcome(capsule_id=capsule.capsule_id, path=path, already_present=already_present)


def _load_any_pre_publication_evidence(store_root: Path | str, capsule_id: str) -> PrePublicationEvidenceCapsule:
    directory = _directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename(capsule_id)
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise PrePublicationEvidenceNotFound(capsule_id) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    try:
        capsule = deserialize_pre_publication_evidence(payload)
    except (TypeError, ValueError) as exc:
        raise CheckpointStoreIntegrityConflict(str(exc)) from exc
    if capsule.capsule_id != capsule_id or path.name != _filename(capsule.capsule_id):
        raise CheckpointStoreIntegrityConflict("persisted producer evidence does not match requested identity")
    return capsule


def load_source_pre_publication_evidence(store_root: Path | str, capsule_id: str) -> PrePublicationEvidenceCapsule:
    """Load one exact source-phase capsule for the future #1428 host activation."""
    capsule = _load_any_pre_publication_evidence(store_root, capsule_id)
    if capsule.phase != SOURCE_PHASE or capsule.checkpoint_id is not None:
        raise CheckpointStoreIntegrityConflict("source-phase producer evidence is required")
    return capsule


def load_pre_publication_evidence(store_root: Path | str, capsule_id: str) -> PrePublicationEvidenceCapsule:
    """Load publication-facing evidence; source-phase records fail closed explicitly."""
    capsule = _load_any_pre_publication_evidence(store_root, capsule_id)
    if capsule.phase != CHECKPOINT_BOUND_PHASE or capsule.checkpoint_id is None:
        raise CheckpointStoreIntegrityConflict("source-phase evidence is not publishable")
    return capsule
