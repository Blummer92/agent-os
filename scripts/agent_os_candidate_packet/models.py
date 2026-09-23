"""Frozen data models for the #755 pure-local candidate-packet compiler.

This module defines only data shapes -- the compiler input, the two
non-authorizing output shapes, and their canonical serialize/reconstruct
helpers -- plus the domain-separated content identity for a compiled packet.
It performs no aggregation, freshness classification, or compilation
decision: those live in ``provenance.py``, ``freshness.py``, ``blockers.py``,
and ``compiler.py``. It reuses, and never re-derives, the canonical stage
result types produced by #750-#754.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from .approval_stage import ApprovalProjectionStageResult
from .planning_stage import PlanningHandoffStageResult
from .proposal_stage import RepositoryProposalStageResult
from .stage_models import IssueReadinessStageResult, canonical_bytes, require_exact_keys

COMPILER_SCHEMA_NAME = "agent-os-candidate-packet-compiler"
COMPILER_SCHEMA_VERSION = "1.0"
PACKET_SCHEMA_NAME = "agent-os-candidate-packet"
PACKET_SCHEMA_VERSION = "1.0"

_HEX_DIGITS = frozenset("0123456789abcdef")
_SHA40_LENGTH = 40
_SHA256_LENGTH = 64


class CandidatePacketPhase(str, Enum):
    """The two non-authorizing packet phases #755 defines. Never a third."""

    APPROVAL_READY = "approval-ready"
    EXECUTION_CANDIDATE = "execution-candidate"


class FailureClass(str, Enum):
    """The repository-wide gap/blocker classification vocabulary.

    Most members describe a missing *capability* elsewhere in Agent OS and
    are never produced by this compiler at runtime; ``blockers.py`` maps the
    compiler's own small, closed ``reason_code`` vocabulary onto the handful
    that do apply. See ``README.md`` for the full mapping.
    """

    MISSING_MODEL = "missing-model"
    MISSING_CONSTRUCTOR = "missing-constructor"
    MISSING_VALIDATOR = "missing-validator"
    MISSING_SERIALIZER = "missing-serializer"
    MISSING_DESERIALIZER = "missing-deserializer"
    MISSING_IDENTITY = "missing-identity"
    MISSING_FRESHNESS_CHECK = "missing-freshness-check"
    MISSING_INVALIDATION_RULE = "missing-invalidation-rule"
    MISSING_COMPILER = "missing-compiler"
    MISSING_ORCHESTRATOR = "missing-orchestrator"
    MISSING_CLI = "missing-CLI"
    MISSING_SERVICE_ENTRYPOINT = "missing-service-entrypoint"
    MISSING_OBSERVABILITY = "missing-observability"
    MISSING_TEST = "missing-test"
    MISSING_DOCUMENTATION = "missing-documentation"
    AUTHORIZATION_REQUIRED = "authorization-required"
    MANUAL_JUDGMENT_REQUIRED = "manual-judgment-required"
    EXTERNAL_CAPABILITY_REQUIRED = "external-capability-required"
    DUPLICATE_CAPABILITY = "duplicate-capability"
    CONTRACT_CONFLICT = "contract-conflict"
    OWNERSHIP_AMBIGUITY = "ownership-ambiguity"
    NO_GAP = "no-gap"


# ---------------------------------------------------------------------------
# Field validators. Small and local, mirroring every other stage module's
# own ``_text``/``_hex_digest`` helpers rather than importing their private
# equivalents across module boundaries.
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty canonical string")
    if any(character < " " or character == "\x7f" for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _repository_name(value: object) -> str:
    repository = _text(value, "repository")
    if repository.count("/") != 1:
        raise ValueError("repository must use owner/repository form")
    owner, name = repository.split("/", 1)
    if not owner or not name:
        raise ValueError("repository must use owner/repository form")
    return repository


def _hex_digest(value: object, field_name: str, length: int) -> str:
    digest = _text(value, field_name)
    if len(digest) != length or digest != digest.lower() or not _HEX_DIGITS.issuperset(digest):
        raise ValueError(f"{field_name} must be a lowercase {length}-character hex digest")
    return digest


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        raise TypeError(f"{field_name} must be an iterable of strings")
    return tuple(_text(item, field_name) for item in value)


def _payload_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


# ---------------------------------------------------------------------------
# CandidatePacketCompilerInput
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidatePacketCompilerInput:
    """Exact canonical upstream objects plus the identity the compiler binds.

    Every ``expected_*`` field is an assertion the caller wants reverified,
    never a fact the compiler invents: ``compiler.py`` recomputes each one
    from the embedded canonical stage object and fails closed on drift
    rather than trusting the copy carried here. ``approval_stage_result`` is
    required for both phases (an ``approval-ready`` compile still needs the
    pending candidate); ``execution_packet_stage_result`` is accepted only
    so ``execution-candidate`` compiles have it to reverify -- an
    ``approval-ready`` compile must not carry one.
    """

    compiler_schema_name: str
    compiler_schema_version: str
    requested_phase: CandidatePacketPhase
    repository: str
    issue_number: int
    invocation_id: str
    candidate_ref: str
    base_branch: str
    base_sha: str
    candidate_sha: str
    source_sha: str
    tested_sha: str
    evaluator_sha: str
    external_build_sha: str | None
    expected_source_revision: str
    expected_source_snapshot_fingerprint: str
    expected_scanner_result_fingerprint: str
    expected_candidate_set_fingerprint: str
    expected_implementation_contract_fingerprint: str
    freshness_boundary: str
    readiness_stage_result: IssueReadinessStageResult
    planning_stage_result: PlanningHandoffStageResult
    proposal_stage_result: RepositoryProposalStageResult
    approval_stage_result: ApprovalProjectionStageResult | None = None
    execution_packet_stage_result: object | None = None
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "compiler_schema_name", _text(self.compiler_schema_name, "compiler_schema_name")
        )
        object.__setattr__(
            self,
            "compiler_schema_version",
            _text(self.compiler_schema_version, "compiler_schema_version"),
        )
        if not isinstance(self.requested_phase, CandidatePacketPhase):
            raise TypeError("requested_phase must be a CandidatePacketPhase")
        object.__setattr__(self, "repository", _repository_name(self.repository))
        if isinstance(self.issue_number, bool) or not isinstance(self.issue_number, int):
            raise TypeError("issue_number must be an int")
        if self.issue_number <= 0:
            raise ValueError("issue_number must be positive")
        object.__setattr__(self, "invocation_id", _text(self.invocation_id, "invocation_id"))
        object.__setattr__(self, "candidate_ref", _text(self.candidate_ref, "candidate_ref"))
        object.__setattr__(self, "base_branch", _text(self.base_branch, "base_branch"))
        for name in ("base_sha", "candidate_sha", "source_sha", "tested_sha", "evaluator_sha"):
            object.__setattr__(self, name, _hex_digest(getattr(self, name), name, _SHA40_LENGTH))
        object.__setattr__(
            self,
            "external_build_sha",
            None
            if self.external_build_sha is None
            else _hex_digest(self.external_build_sha, "external_build_sha", _SHA40_LENGTH),
        )
        object.__setattr__(
            self,
            "expected_source_revision",
            _text(self.expected_source_revision, "expected_source_revision"),
        )
        for name in (
            "expected_source_snapshot_fingerprint",
            "expected_scanner_result_fingerprint",
            "expected_candidate_set_fingerprint",
            "expected_implementation_contract_fingerprint",
        ):
            object.__setattr__(self, name, _hex_digest(getattr(self, name), name, _SHA256_LENGTH))
        object.__setattr__(self, "freshness_boundary", _text(self.freshness_boundary, "freshness_boundary"))

        if type(self.readiness_stage_result) is not IssueReadinessStageResult:
            raise TypeError("readiness_stage_result must be an exact IssueReadinessStageResult")
        if type(self.planning_stage_result) is not PlanningHandoffStageResult:
            raise TypeError("planning_stage_result must be an exact PlanningHandoffStageResult")
        if type(self.proposal_stage_result) is not RepositoryProposalStageResult:
            raise TypeError("proposal_stage_result must be an exact RepositoryProposalStageResult")
        if (
            self.approval_stage_result is not None
            and type(self.approval_stage_result) is not ApprovalProjectionStageResult
        ):
            raise TypeError(
                "approval_stage_result must be an exact ApprovalProjectionStageResult or None"
            )
        if self.execution_packet_stage_result is not None:
            # Imported lazily so an approval-ready-only caller never pulls in
            # the execution-service / Workflow Scheduler runtime-config
            # dependency graph -- the same laziness the package __init__
            # already applies to this stage's exports.
            from .execution_packet_stage import ExecutionPacketStageResult

            if type(self.execution_packet_stage_result) is not ExecutionPacketStageResult:
                raise TypeError(
                    "execution_packet_stage_result must be an exact "
                    "ExecutionPacketStageResult or None"
                )


# ---------------------------------------------------------------------------
# CandidatePacket
# ---------------------------------------------------------------------------

_PACKET_SEMANTIC_FIELD_NAMES = (
    "schema_name",
    "schema_version",
    "phase",
    "repository",
    "issue_number",
    "invocation_id",
    "candidate_ref",
    "base_branch",
    "base_sha",
    "candidate_sha",
    "source_sha",
    "tested_sha",
    "evaluator_sha",
    "external_build_sha",
    "freshness_boundary",
    "stage_identities",
    "stage_payload_digests",
    "provenance_manifest",
    "invalidation_manifest",
    "allowed_files",
    "forbidden_paths",
    "expected_changed_paths",
    "required_tests",
    "command_identities",
    "argv_bindings",
    "per_command_timeout_seconds",
    "total_timeout_seconds",
    "max_output_bytes",
    "approval_boundary_summary",
    "execution_authorization_boundary_summary",
    "evidence_completeness",
    "disposition",
)


def _packet_semantic_payload(fields_by_name: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical identity payload for a packet's field mapping.

    ``evaluated_at`` and ``packet_id`` are the only fields excluded: the
    first is observation provenance, not semantic content, and the second is
    the identity being computed. Every other field -- including
    ``freshness_boundary``, which *does* determine current applicability -- is
    covered.
    """
    phase = fields_by_name["phase"]
    return {
        "schema_name": fields_by_name["schema_name"],
        "schema_version": fields_by_name["schema_version"],
        "phase": phase.value if isinstance(phase, CandidatePacketPhase) else phase,
        "repository": fields_by_name["repository"],
        "issue_number": fields_by_name["issue_number"],
        "invocation_id": fields_by_name["invocation_id"],
        "candidate_ref": fields_by_name["candidate_ref"],
        "base_branch": fields_by_name["base_branch"],
        "base_sha": fields_by_name["base_sha"],
        "candidate_sha": fields_by_name["candidate_sha"],
        "source_sha": fields_by_name["source_sha"],
        "tested_sha": fields_by_name["tested_sha"],
        "evaluator_sha": fields_by_name["evaluator_sha"],
        "external_build_sha": fields_by_name["external_build_sha"],
        "freshness_boundary": fields_by_name["freshness_boundary"],
        "stage_identities": [list(item) for item in fields_by_name["stage_identities"]],
        "stage_payload_digests": [
            list(item) for item in fields_by_name["stage_payload_digests"]
        ],
        "provenance_manifest": list(fields_by_name["provenance_manifest"]),
        "invalidation_manifest": list(fields_by_name["invalidation_manifest"]),
        "allowed_files": list(fields_by_name["allowed_files"]),
        "forbidden_paths": list(fields_by_name["forbidden_paths"]),
        "expected_changed_paths": list(fields_by_name["expected_changed_paths"]),
        "required_tests": list(fields_by_name["required_tests"]),
        "command_identities": list(fields_by_name["command_identities"]),
        "argv_bindings": [
            [name, list(argv)] for name, argv in fields_by_name["argv_bindings"]
        ],
        "per_command_timeout_seconds": fields_by_name["per_command_timeout_seconds"],
        "total_timeout_seconds": fields_by_name["total_timeout_seconds"],
        "max_output_bytes": fields_by_name["max_output_bytes"],
        "approval_boundary_summary": fields_by_name["approval_boundary_summary"],
        "execution_authorization_boundary_summary": fields_by_name[
            "execution_authorization_boundary_summary"
        ],
        "evidence_completeness": fields_by_name["evidence_completeness"],
        "disposition": fields_by_name["disposition"],
        "execution_authorized": False,
        "merge_authorized": False,
        "automatic_retry": False,
        "side_effects_performed": False,
    }


def compute_candidate_packet_fingerprint(fields_by_name: Mapping[str, Any]) -> str:
    """Domain-free SHA-256 over one packet's canonical semantic payload."""
    return hashlib.sha256(canonical_bytes(_packet_semantic_payload(fields_by_name))).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidatePacket:
    """One complete, immutable, content-addressed, non-authorizing packet."""

    schema_name: str
    schema_version: str
    phase: CandidatePacketPhase
    packet_id: str
    repository: str
    issue_number: int
    invocation_id: str
    candidate_ref: str
    base_branch: str
    base_sha: str
    candidate_sha: str
    source_sha: str
    tested_sha: str
    evaluator_sha: str
    external_build_sha: str | None
    freshness_boundary: str
    evaluated_at: str
    stage_identities: tuple[tuple[str, str], ...]
    stage_payload_digests: tuple[tuple[str, str], ...]
    provenance_manifest: tuple[str, ...]
    invalidation_manifest: tuple[str, ...]
    allowed_files: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    expected_changed_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    command_identities: tuple[str, ...]
    argv_bindings: tuple[tuple[str, tuple[str, ...]], ...]
    per_command_timeout_seconds: int | None
    total_timeout_seconds: int | None
    max_output_bytes: int | None
    approval_boundary_summary: str
    execution_authorization_boundary_summary: str
    evidence_completeness: str
    disposition: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.phase, CandidatePacketPhase):
            raise TypeError("phase must be a CandidatePacketPhase")
        object.__setattr__(self, "packet_id", _text(self.packet_id, "packet_id"))
        if self.phase is CandidatePacketPhase.APPROVAL_READY:
            if self.command_identities or self.argv_bindings:
                raise ValueError(
                    "approval-ready packets cannot carry command/argv evidence"
                )
            if (
                self.per_command_timeout_seconds is not None
                or self.total_timeout_seconds is not None
                or self.max_output_bytes is not None
            ):
                raise ValueError("approval-ready packets cannot carry runtime bounds")
        expected_id = candidate_packet_id(self)
        if self.packet_id != expected_id:
            raise ValueError("packet_id does not match the packet's own canonical identity")


def candidate_packet_id(packet: CandidatePacket) -> str:
    """Recompute one packet's content-addressed identity from its own fields."""
    if type(packet) is not CandidatePacket:
        raise TypeError("packet must be an exact CandidatePacket")
    fields_by_name = {name: getattr(packet, name) for name in _PACKET_SEMANTIC_FIELD_NAMES}
    digest = compute_candidate_packet_fingerprint(fields_by_name)
    return f"candidate-packet:{digest}"


_CANDIDATE_PACKET_PAYLOAD_KEYS = frozenset(_PACKET_SEMANTIC_FIELD_NAMES) | {
    "packet_id",
    "evaluated_at",
    "execution_authorized",
    "merge_authorized",
    "automatic_retry",
    "side_effects_performed",
}


def serialize_candidate_packet(packet: CandidatePacket) -> dict[str, object]:
    """Serialize one canonical CandidatePacket to canonical JSON-safe form."""
    if type(packet) is not CandidatePacket:
        raise TypeError("packet must be an exact CandidatePacket")
    fields_by_name = {name: getattr(packet, name) for name in _PACKET_SEMANTIC_FIELD_NAMES}
    payload = _packet_semantic_payload(fields_by_name)
    payload["packet_id"] = packet.packet_id
    payload["evaluated_at"] = packet.evaluated_at
    if deserialize_candidate_packet(payload) != packet:
        raise ValueError("packet has noncanonical candidate packet fields")
    return payload


def deserialize_candidate_packet(payload: Mapping[str, object]) -> CandidatePacket:
    """Reconstruct one canonical CandidatePacket, failing closed on any drift."""
    require_exact_keys(payload, _CANDIDATE_PACKET_PAYLOAD_KEYS, "candidate packet")
    for name in (
        "execution_authorized",
        "merge_authorized",
        "automatic_retry",
        "side_effects_performed",
    ):
        if payload[name] is not False:
            raise ValueError(f"{name} must be false")

    stage_identities = tuple(
        tuple(item) for item in _payload_list(payload["stage_identities"], "stage_identities")
    )
    stage_payload_digests = tuple(
        tuple(item)
        for item in _payload_list(payload["stage_payload_digests"], "stage_payload_digests")
    )
    argv_bindings = tuple(
        (item[0], tuple(item[1]))
        for item in _payload_list(payload["argv_bindings"], "argv_bindings")
    )

    packet = CandidatePacket(
        schema_name=payload["schema_name"],
        schema_version=payload["schema_version"],
        phase=CandidatePacketPhase(payload["phase"]),
        packet_id=payload["packet_id"],
        repository=payload["repository"],
        issue_number=payload["issue_number"],
        invocation_id=payload["invocation_id"],
        candidate_ref=payload["candidate_ref"],
        base_branch=payload["base_branch"],
        base_sha=payload["base_sha"],
        candidate_sha=payload["candidate_sha"],
        source_sha=payload["source_sha"],
        tested_sha=payload["tested_sha"],
        evaluator_sha=payload["evaluator_sha"],
        external_build_sha=payload["external_build_sha"],
        freshness_boundary=payload["freshness_boundary"],
        evaluated_at=payload["evaluated_at"],
        stage_identities=stage_identities,
        stage_payload_digests=stage_payload_digests,
        provenance_manifest=tuple(
            _payload_list(payload["provenance_manifest"], "provenance_manifest")
        ),
        invalidation_manifest=tuple(
            _payload_list(payload["invalidation_manifest"], "invalidation_manifest")
        ),
        allowed_files=tuple(_payload_list(payload["allowed_files"], "allowed_files")),
        forbidden_paths=tuple(_payload_list(payload["forbidden_paths"], "forbidden_paths")),
        expected_changed_paths=tuple(
            _payload_list(payload["expected_changed_paths"], "expected_changed_paths")
        ),
        required_tests=tuple(_payload_list(payload["required_tests"], "required_tests")),
        command_identities=tuple(
            _payload_list(payload["command_identities"], "command_identities")
        ),
        argv_bindings=argv_bindings,
        per_command_timeout_seconds=payload["per_command_timeout_seconds"],
        total_timeout_seconds=payload["total_timeout_seconds"],
        max_output_bytes=payload["max_output_bytes"],
        approval_boundary_summary=payload["approval_boundary_summary"],
        execution_authorization_boundary_summary=payload[
            "execution_authorization_boundary_summary"
        ],
        evidence_completeness=payload["evidence_completeness"],
        disposition=payload["disposition"],
    )
    if packet.packet_id != payload["packet_id"]:
        raise ValueError("packet_id does not match the reconstructed packet's own identity")
    return packet


# ---------------------------------------------------------------------------
# CandidatePacketCompilationFailure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidatePacketCompilationFailure:
    """One deterministic, bounded, non-authorizing compilation failure."""

    schema_name: str
    schema_version: str
    requested_phase: CandidatePacketPhase
    failure_class: FailureClass
    reason_code: str
    failed_stage: str
    failed_field: str | None = None
    expected_identity: str | None = None
    observed_identity: str | None = None
    source_identity: str | None = None
    remediation_owner: str
    human_judgment_required: bool
    external_authorization_required: bool
    connected_capability_required: bool
    packet_constructed: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.requested_phase, CandidatePacketPhase):
            raise TypeError("requested_phase must be a CandidatePacketPhase")
        if not isinstance(self.failure_class, FailureClass):
            raise TypeError("failure_class must be a FailureClass")
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        object.__setattr__(self, "failed_stage", _text(self.failed_stage, "failed_stage"))
        object.__setattr__(
            self, "remediation_owner", _text(self.remediation_owner, "remediation_owner")
        )
        for name in ("failed_field", "expected_identity", "observed_identity", "source_identity"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, name))
        for name in (
            "human_judgment_required",
            "external_authorization_required",
            "connected_capability_required",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")


CandidatePacketCompilationResult = CandidatePacket | CandidatePacketCompilationFailure
