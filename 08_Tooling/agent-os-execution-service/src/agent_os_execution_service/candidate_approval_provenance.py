"""Durable candidate-preparer provenance for #1982 Option C / #1985 vNext.

This is an additive evidence variant under the existing #1412
``pre-publication-producer-evidence`` namespace and trusted checkpoint-store
root. Version 1 carries one exact APPROVAL_READY packet plus its distinct
ApprovalCandidateContext. Version 2 additionally retains the exact canonical
RepositoryProposalStageResult needed for a later fresh process to delegate
approval/currentness/projection reconstruction back to #753. Neither version
creates approval or execution authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from scripts.agent_os_candidate_packet.approval_stage import ApprovalCandidateContext
from scripts.agent_os_candidate_packet.models import (
    CandidatePacket,
    CandidatePacketPhase,
    deserialize_candidate_packet,
    serialize_candidate_packet,
)
from scripts.agent_os_candidate_packet.proposal_stage import (
    RepositoryProposalStageResult,
    repository_proposal_stage_result_from_dict,
    repository_proposal_stage_result_to_dict,
)
from scripts.agent_os_execution_checkpoint.identity import canonical_json_bytes
from scripts.agent_os_execution_checkpoint.store import (
    CheckpointStoreCapacityExceeded,
    CheckpointStoreIntegrityConflict,
    CheckpointStoreUnavailable,
    _atomic_write,
    _ensure_dir,
    _existing_records_footprint,
    _reject_symlink,
)
from scripts.agent_os_issue_acceptance.approval_records import ApprovalKind

from .pre_publication_evidence_store import (
    MAX_CAPSULES,
    MAX_CAPSULE_STORE_BYTES,
    STORE_NAMESPACE,
)

SCHEMA_NAME = "agent-os-candidate-approval-provenance"
SCHEMA_VERSION = "2.0"
LEGACY_SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({LEGACY_SCHEMA_VERSION, SCHEMA_VERSION})
MAX_BYTES = 1024 * 1024
_PREFIX = "pre-publication-evidence:"


def _context_payload(value: ApprovalCandidateContext) -> dict[str, object]:
    if value.supersedes is not None:
        raise ValueError("candidate provenance does not carry supersedes records")
    return {
        "approval_kind": value.approval_kind.value,
        "authorizer_id": value.authorizer_id,
        "decision_id": value.decision_id,
        "decision_at": value.decision_at,
        "expires_at": value.expires_at,
    }


def _payload(value: "CandidateApprovalProvenanceEvidence", *, include_id: bool) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_name": value.schema_name,
        "schema_version": value.schema_version,
        "approval_ready_packet": serialize_candidate_packet(value.approval_ready_packet),
        "candidate_context": _context_payload(value.candidate_context),
        "repository_implementation_authorized": False,
        "execution_authorized": False,
        "publication_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "external_writes_authorized": False,
    }
    if value.schema_version == SCHEMA_VERSION:
        assert value.repository_proposal_stage_result is not None
        result["repository_proposal_stage_result"] = repository_proposal_stage_result_to_dict(
            value.repository_proposal_stage_result
        )
    if include_id:
        result["evidence_id"] = value.evidence_id
    return result


def candidate_approval_provenance_id(value: "CandidateApprovalProvenanceEvidence") -> str:
    domain = (
        b"agent-os-candidate-approval-provenance:v1\0"
        if value.schema_version == LEGACY_SCHEMA_VERSION
        else b"agent-os-candidate-approval-provenance:v2\0"
    )
    digest = hashlib.sha256(
        domain + canonical_json_bytes(_payload(value, include_id=False))
    ).hexdigest()
    return _PREFIX + digest


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateApprovalProvenanceEvidence:
    schema_name: str
    schema_version: str
    approval_ready_packet: CandidatePacket
    candidate_context: ApprovalCandidateContext
    repository_proposal_stage_result: RepositoryProposalStageResult | None = None
    evidence_id: str = ""
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    publication_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != SCHEMA_NAME or self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("unsupported candidate-approval provenance schema")
        if type(self.approval_ready_packet) is not CandidatePacket:
            raise TypeError("approval_ready_packet must be exact CandidatePacket")
        if self.approval_ready_packet.phase is not CandidatePacketPhase.APPROVAL_READY:
            raise ValueError("candidate provenance requires APPROVAL_READY packet")
        if (
            self.approval_ready_packet.evidence_completeness != "complete"
            or self.approval_ready_packet.disposition != "verified"
        ):
            raise ValueError("candidate provenance requires complete verified packet")
        if type(self.candidate_context) is not ApprovalCandidateContext:
            raise TypeError("candidate_context must be exact ApprovalCandidateContext")
        _context_payload(self.candidate_context)
        if self.schema_version == LEGACY_SCHEMA_VERSION:
            if self.repository_proposal_stage_result is not None:
                raise ValueError("candidate provenance v1 cannot carry proposal stage material")
        elif type(self.repository_proposal_stage_result) is not RepositoryProposalStageResult:
            raise TypeError("candidate provenance v2 requires exact RepositoryProposalStageResult")
        computed = candidate_approval_provenance_id(self)
        if self.evidence_id and self.evidence_id != computed:
            raise ValueError("candidate provenance evidence_id mismatch")
        object.__setattr__(self, "evidence_id", computed)


def build_candidate_approval_provenance(
    *,
    approval_ready_packet: CandidatePacket,
    candidate_context: ApprovalCandidateContext,
    repository_proposal_stage_result: RepositoryProposalStageResult | None = None,
) -> CandidateApprovalProvenanceEvidence:
    """Build v1 for legacy callers or v2 when exact proposal-stage material is supplied."""
    return CandidateApprovalProvenanceEvidence(
        schema_name=SCHEMA_NAME,
        schema_version=(
            LEGACY_SCHEMA_VERSION
            if repository_proposal_stage_result is None
            else SCHEMA_VERSION
        ),
        approval_ready_packet=approval_ready_packet,
        candidate_context=candidate_context,
        repository_proposal_stage_result=repository_proposal_stage_result,
    )


def serialize_candidate_approval_provenance(value: CandidateApprovalProvenanceEvidence) -> bytes:
    raw = canonical_json_bytes(_payload(value, include_id=True))
    if len(raw) > MAX_BYTES:
        raise ValueError("candidate provenance evidence exceeds size bound")
    return raw


def deserialize_candidate_approval_provenance(payload: bytes | str) -> CandidateApprovalProvenanceEvidence:
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if len(raw) > MAX_BYTES:
        raise ValueError("candidate provenance evidence exceeds size bound")
    decoded = json.loads(raw.decode("utf-8"))
    if type(decoded) is not dict:
        raise ValueError("candidate provenance fields drifted")
    version = decoded.get("schema_version")
    base = {
        "schema_name", "schema_version", "approval_ready_packet", "candidate_context",
        "evidence_id", "repository_implementation_authorized", "execution_authorized",
        "publication_authorized", "github_writes_authorized", "merge_authorized",
        "external_writes_authorized",
    }
    expected = base if version == LEGACY_SCHEMA_VERSION else base | {"repository_proposal_stage_result"}
    if version not in SUPPORTED_SCHEMA_VERSIONS or set(decoded) != expected:
        raise ValueError("candidate provenance fields drifted")
    for name in {
        "repository_implementation_authorized", "execution_authorized",
        "publication_authorized", "github_writes_authorized", "merge_authorized",
        "external_writes_authorized",
    }:
        if decoded[name] is not False:
            raise ValueError(f"{name} must remain false")
    context = decoded["candidate_context"]
    if type(context) is not dict or set(context) != {
        "approval_kind", "authorizer_id", "decision_id", "decision_at", "expires_at"
    }:
        raise ValueError("candidate context fields drifted")
    proposal_stage = (
        None
        if version == LEGACY_SCHEMA_VERSION
        else repository_proposal_stage_result_from_dict(decoded["repository_proposal_stage_result"])
    )
    return CandidateApprovalProvenanceEvidence(
        schema_name=decoded["schema_name"],
        schema_version=version,
        approval_ready_packet=deserialize_candidate_packet(decoded["approval_ready_packet"]),
        candidate_context=ApprovalCandidateContext(
            approval_kind=ApprovalKind(context["approval_kind"]),
            authorizer_id=context["authorizer_id"],
            decision_id=context["decision_id"],
            decision_at=context["decision_at"],
            expires_at=context["expires_at"],
        ),
        repository_proposal_stage_result=proposal_stage,
        evidence_id=decoded["evidence_id"],
    )


def _directory(store_root: Path | str) -> Path:
    return Path(store_root) / STORE_NAMESPACE


def _filename(evidence_id: str) -> str:
    if type(evidence_id) is not str or not evidence_id.startswith(_PREFIX):
        raise ValueError("candidate provenance evidence_id malformed")
    digest = evidence_id.removeprefix(_PREFIX)
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("candidate provenance evidence_id malformed")
    return f"{digest}.json"


def append_candidate_approval_provenance(
    store_root: Path | str, value: CandidateApprovalProvenanceEvidence
) -> str:
    directory = _directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    payload = serialize_candidate_approval_provenance(value)
    destination = directory / _filename(value.evidence_id)
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if count + 1 > MAX_CAPSULES or total_bytes + len(payload) > MAX_CAPSULE_STORE_BYTES:
            raise CheckpointStoreCapacityExceeded("pre-publication evidence store is at capacity")
    _atomic_write(directory, destination.name, payload)
    return value.evidence_id


def load_candidate_approval_provenance(
    store_root: Path | str, evidence_id: str
) -> CandidateApprovalProvenanceEvidence:
    directory = _directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename(evidence_id)
    _reject_symlink(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise LookupError(evidence_id) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    try:
        value = deserialize_candidate_approval_provenance(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CheckpointStoreIntegrityConflict(str(exc)) from exc
    if value.evidence_id != evidence_id:
        raise CheckpointStoreIntegrityConflict("candidate provenance identity mismatch")
    return value


__all__ = [
    "CandidateApprovalProvenanceEvidence",
    "LEGACY_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "append_candidate_approval_provenance",
    "build_candidate_approval_provenance",
    "candidate_approval_provenance_id",
    "deserialize_candidate_approval_provenance",
    "load_candidate_approval_provenance",
    "serialize_candidate_approval_provenance",
]
