"""Checkpoint-root persistence adapter for #1412 producer evidence.

This module intentionally reuses the same private atomic/content-addressed store
primitives already consumed by ``governed_resume_restart_capsule``.  It adds no
store root, database, mutable head, retry path, or authority semantics.
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
    MAX_CAPSULES,
    MAX_CAPSULE_STORE_BYTES,
    PrePublicationEvidenceCapsule,
    PrePublicationEvidenceNotFound,
    deserialize_pre_publication_evidence,
    serialize_pre_publication_evidence,
)


@dataclass(frozen=True, slots=True)
class AppendPrePublicationEvidenceOutcome:
    capsule_id: str
    path: Path
    already_present: bool


def _directory(store_root: Path | str) -> Path:
    return Path(store_root) / "pre-publication-producer-evidence"


def _filename(capsule_id: str) -> str:
    prefix = "pre-publication-evidence:"
    if type(capsule_id) is not str or not capsule_id.startswith(prefix):
        raise ValueError("capsule_id is malformed")
    digest = capsule_id.removeprefix(prefix)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("capsule_id is malformed")
    return f"{digest}.json"


def append_pre_publication_evidence(
    store_root: Path | str,
    capsule: PrePublicationEvidenceCapsule,
) -> AppendPrePublicationEvidenceOutcome:
    if type(capsule) is not PrePublicationEvidenceCapsule:
        raise TypeError("capsule must be an exact PrePublicationEvidenceCapsule")

    # Publication evidence is never allowed to outrun its independently durable
    # #895 checkpoint.  The exact lookup reuses full checkpoint chain and
    # quarantine verification before any capsule write occurs.
    durable_checkpoint = load_checkpoint_by_id(
        store_root,
        capsule.candidate_packet.issue_number,
        capsule.checkpoint_id,
    )
    if (
        durable_checkpoint.checkpoint_id != capsule.checkpoint_id
        or durable_checkpoint.repository.casefold()
        != capsule.candidate_packet.repository.casefold()
        or durable_checkpoint.issue_number != capsule.candidate_packet.issue_number
        or durable_checkpoint.invocation_id != capsule.candidate_packet.invocation_id
        or durable_checkpoint.source_sha != capsule.candidate_packet.candidate_sha
        or durable_checkpoint.tested_sha != capsule.candidate_packet.tested_sha
    ):
        raise CheckpointStoreIntegrityConflict(
            "durable checkpoint does not bind to producer evidence"
        )

    directory = _directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    payload = serialize_pre_publication_evidence(capsule)
    destination = directory / _filename(capsule.capsule_id)
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if count + 1 > MAX_CAPSULES or total_bytes + len(payload) > MAX_CAPSULE_STORE_BYTES:
            raise CheckpointStoreCapacityExceeded(
                "pre-publication evidence store is at capacity"
            )
    path, already_present = _atomic_write(directory, destination.name, payload)
    return AppendPrePublicationEvidenceOutcome(
        capsule_id=capsule.capsule_id,
        path=path,
        already_present=already_present,
    )


def load_pre_publication_evidence(
    store_root: Path | str,
    capsule_id: str,
) -> PrePublicationEvidenceCapsule:
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
        raise CheckpointStoreIntegrityConflict(
            "persisted producer evidence does not match requested identity"
        )
    return capsule
