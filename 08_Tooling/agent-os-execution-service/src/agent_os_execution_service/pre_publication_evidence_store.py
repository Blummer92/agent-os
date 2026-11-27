"""Checkpoint-root persistence adapter for #1412/#1799/#1978 producer evidence.

Legacy v1.0 and v1.1 source/checkpoint-bound evidence keep their existing
semantics. The additive v1.2 approval-custody record reuses the same
``pre-publication-producer-evidence`` namespace and content-addressed filenames,
with one dedicated loader so custody can never be mistaken for source or
publication evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.agent_os_execution_checkpoint.store import (
    CheckpointStoreIntegrityConflict,
    _atomic_write,
    _read_immutable_record,
    load_checkpoint_by_id,
)

from .pre_publication_evidence_capsule import (
    APPROVAL_CUSTODY_PHASE,
    CHECKPOINT_BOUND_PHASE,
    SOURCE_PHASE,
    MAX_CAPSULE_BYTES,
    _CAPSULE_ID_RE,
    _checkpoint_binds,
    ApprovalCustodyEvidenceCapsule,
    PrePublicationEvidenceCapsule,
    deserialize_pre_publication_evidence_record,
    serialize_approval_custody_evidence,
    serialize_pre_publication_evidence,
)

MAX_CAPSULES = 4096
MAX_CAPSULE_STORE_BYTES = 256 * 1024 * 1024
STORE_NAMESPACE = "pre-publication-producer-evidence"

ProducerEvidenceCapsule = PrePublicationEvidenceCapsule | ApprovalCustodyEvidenceCapsule


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
    if type(capsule_id) is not str or not _CAPSULE_ID_RE.fullmatch(capsule_id):
        raise ValueError("capsule_id is malformed")
    return f"{capsule_id.rsplit(':', 1)[1]}.json"


def _verify_durable_checkpoint(
    store_root: Path | str,
    capsule: PrePublicationEvidenceCapsule,
) -> None:
    if capsule.phase != CHECKPOINT_BOUND_PHASE or capsule.checkpoint_id is None:
        raise CheckpointStoreIntegrityConflict("checkpoint-bound producer evidence is required")
    durable = load_checkpoint_by_id(
        store_root,
        capsule.candidate_packet.issue_number,
        capsule.checkpoint_id,
    )
    if (
        durable.checkpoint_id != capsule.checkpoint_id
        or not _checkpoint_binds(durable, capsule.candidate_packet, capsule.candidate_branch)
        or (capsule.execution_id is not None and durable.execution_id != capsule.execution_id)
    ):
        raise CheckpointStoreIntegrityConflict("durable checkpoint does not bind to producer evidence")


def append_pre_publication_evidence(
    store_root: Path | str,
    capsule: ProducerEvidenceCapsule,
) -> AppendPrePublicationEvidenceOutcome:
    """Persist one approved custody, source, or checkpoint-bound capsule."""
    payload = (
        serialize_approval_custody_evidence(capsule)
        if type(capsule) is ApprovalCustodyEvidenceCapsule else serialize_pre_publication_evidence(capsule)
    )
    # Frozen records can still be corrupted in-memory. Reconstruct before
    # publishing so the embedded approval is independently revalidated.
    try:
        checked = deserialize_pre_publication_evidence_record(payload)
    except (TypeError, ValueError) as exc:
        raise CheckpointStoreIntegrityConflict(str(exc)) from exc
    if checked.capsule_id != capsule.capsule_id:
        raise CheckpointStoreIntegrityConflict("producer evidence identity changed")
    if checked.phase == CHECKPOINT_BOUND_PHASE:
        _verify_durable_checkpoint(store_root, checked)
    path, already_present = _atomic_write(
        _directory(store_root), _filename(capsule.capsule_id), payload,
        capacity=(MAX_CAPSULES, MAX_CAPSULE_STORE_BYTES),
    )
    return AppendPrePublicationEvidenceOutcome(capsule.capsule_id, path, already_present)


_PHASE_FAILURE = {
    APPROVAL_CUSTODY_PHASE: "approval-custody producer evidence is required",
    SOURCE_PHASE: "source-phase producer evidence is required",
    CHECKPOINT_BOUND_PHASE: "source-phase evidence is not publishable",
}


def _load_record(store_root: Path | str, capsule_id: str, phase: str) -> ProducerEvidenceCapsule:
    try:
        payload = _read_immutable_record(_directory(store_root), _filename(capsule_id), MAX_CAPSULE_BYTES)
    except FileNotFoundError as exc:
        raise PrePublicationEvidenceNotFound(capsule_id) from exc
    try:
        capsule = deserialize_pre_publication_evidence_record(payload)
    except (TypeError, ValueError) as exc:
        raise CheckpointStoreIntegrityConflict(str(exc)) from exc
    if capsule.capsule_id != capsule_id:
        raise CheckpointStoreIntegrityConflict("persisted producer evidence does not match requested identity")
    if capsule.phase != phase:
        raise CheckpointStoreIntegrityConflict(_PHASE_FAILURE[phase])
    return capsule


def load_approval_custody_pre_publication_evidence(
    store_root: Path | str, capsule_id: str,
) -> ApprovalCustodyEvidenceCapsule:
    """Load one exact v1.2 approval-custody record and no later phase."""
    return _load_record(store_root, capsule_id, APPROVAL_CUSTODY_PHASE)


def load_source_pre_publication_evidence(
    store_root: Path | str, capsule_id: str,
) -> PrePublicationEvidenceCapsule:
    """Load one exact source-phase capsule for the #1428 host activation."""
    return _load_record(store_root, capsule_id, SOURCE_PHASE)


def load_pre_publication_evidence(
    store_root: Path | str, capsule_id: str,
) -> PrePublicationEvidenceCapsule:
    """Load publication-facing evidence only while its checkpoint still binds."""
    capsule = _load_record(store_root, capsule_id, CHECKPOINT_BOUND_PHASE)
    _verify_durable_checkpoint(store_root, capsule)
    return capsule
