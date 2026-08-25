"""Durable non-authorizing producer evidence for first handoff publication (#1412).

This module owns only the immutable producer-evidence capsule, its canonical
content identity, construction, and serialization. Persistence is deliberately
owned by ``pre_publication_evidence_store`` so #1412 exposes one store API.

The capsule preserves already-canonical evidence that cannot be recovered from
descriptor-keyed consumer reconstruction. It creates no approval, execution,
publication, Scheduler, lease, GitHub-write, merge, or external-write authority.
Current execution authorization, dependency readiness, route currentness, and
ResumePlan currentness must be reacquired independently by #1411.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from scripts.agent_os_candidate_packet.models import (
    CandidatePacket,
    CandidatePacketPhase,
    deserialize_candidate_packet,
    serialize_candidate_packet,
)
from scripts.agent_os_execution_capabilities.dependencies import (
    RequiredEnvironmentSpec,
    reconstruct_required_environment_spec,
    required_environment_spec_payload,
)
from scripts.agent_os_execution_checkpoint.identity import canonical_json_bytes
from scripts.agent_os_execution_checkpoint.models import ExecutionCheckpoint
from scripts.agent_os_issue_acceptance.approval_records import (
    ApprovalRecord,
    ApprovalState,
    reconstruct_approval_record,
    serialize_approval_record,
)
from scripts.agent_os_remote_validation.advisory_gate import advisory_evidence_result_id
from scripts.agent_os_remote_validation.advisory_render import advisory_render_result_id
from scripts.agent_os_remote_validation.evidence_bundle import (
    MAX_BUNDLE_SERIALIZED_BYTES,
    serialize_validation_evidence_bundle,
    validation_evidence_bundle_id,
)
from scripts.agent_os_remote_validation.selector import validation_plan_id
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput

CAPSULE_SCHEMA_NAME = "agent-os-pre-publication-producer-evidence"
CAPSULE_SCHEMA_VERSION = "1.0"
MAX_CAPSULE_BYTES = 2 * 1024 * 1024

_CAPSULE_ID_RE = re.compile(r"^pre-publication-evidence:[0-9a-f]{64}$", re.ASCII)
_CHECKPOINT_ID_RE = re.compile(r"^agent-os\.execution-checkpoint:[0-9a-f]{64}$", re.ASCII)


@dataclass(frozen=True, slots=True, kw_only=True)
class PrePublicationEvidenceCapsule:
    """One content-addressed producer-evidence record; never authority."""

    schema_name: Literal["agent-os-pre-publication-producer-evidence"]
    schema_version: Literal["1.0"]
    candidate_packet: CandidatePacket
    approval_record: ApprovalRecord
    required_environment_spec: RequiredEnvironmentSpec
    validation_bundle_json: str
    validation_plan_id: str
    validation_bundle_id: str
    advisory_result_id: str
    advisory_render_id: str
    candidate_branch: str
    workspace_request_id: str
    invalidation_events: tuple[str, ...]
    checkpoint_id: str
    created_at: str
    expires_at: str
    evaluated_at: str
    capsule_id: str = ""
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    publication_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self.schema_name != CAPSULE_SCHEMA_NAME
            or self.schema_version != CAPSULE_SCHEMA_VERSION
        ):
            raise ValueError("unsupported pre-publication evidence capsule schema")
        if type(self.candidate_packet) is not CandidatePacket:
            raise TypeError("candidate_packet must be an exact CandidatePacket")
        if self.candidate_packet.phase is not CandidatePacketPhase.EXECUTION_CANDIDATE:
            raise ValueError("candidate_packet must be an execution-candidate packet")
        if (
            self.candidate_packet.evidence_completeness != "complete"
            or self.candidate_packet.disposition != "verified"
        ):
            raise ValueError("candidate_packet must carry complete verified evidence")
        if self.candidate_packet.source_sha != self.candidate_packet.candidate_sha:
            raise ValueError("candidate source and candidate SHA must match for publication")
        if type(self.approval_record) is not ApprovalRecord:
            raise TypeError("approval_record must be an exact ApprovalRecord")
        if self.approval_record.state is not ApprovalState.APPROVED:
            raise ValueError("approval_record must be approved")
        if type(self.required_environment_spec) is not RequiredEnvironmentSpec:
            raise TypeError(
                "required_environment_spec must be an exact RequiredEnvironmentSpec"
            )
        if (
            type(self.checkpoint_id) is not str
            or not _CHECKPOINT_ID_RE.fullmatch(self.checkpoint_id)
        ):
            raise ValueError("checkpoint_id is malformed")
        for name in (
            "validation_plan_id",
            "validation_bundle_id",
            "advisory_result_id",
            "advisory_render_id",
            "candidate_branch",
            "workspace_request_id",
            "created_at",
            "expires_at",
            "evaluated_at",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise TypeError(f"{name} must be non-empty exact text")
        if type(self.validation_bundle_json) is not str or not self.validation_bundle_json:
            raise TypeError("validation_bundle_json must be non-empty exact text")
        if len(self.validation_bundle_json.encode("utf-8")) > MAX_BUNDLE_SERIALIZED_BYTES:
            raise ValueError("validation bundle exceeds its canonical size bound")
        if type(self.invalidation_events) is not tuple or any(
            type(item) is not str or not item for item in self.invalidation_events
        ):
            raise TypeError("invalidation_events must be a tuple of non-empty strings")
        if len(set(self.invalidation_events)) != len(self.invalidation_events):
            raise ValueError("invalidation_events must be unique")

        packet = self.candidate_packet
        approval = self.approval_record
        approval_identity = f"{approval.approval_id}@{approval.approval_revision}"
        packet_identities = dict(packet.stage_identities)
        if packet_identities.get("approval-decision") != approval_identity:
            raise ValueError("approval record does not match candidate approval identity")
        binding = approval.binding
        if (
            binding.repository.casefold() != packet.repository.casefold()
            or binding.base_branch != packet.base_branch
            or binding.evaluated_repository_sha != packet.candidate_sha
            or binding.tested_repository_sha != packet.tested_sha
            or tuple(binding.allowed_files) != tuple(packet.allowed_files)
            or tuple(binding.forbidden_paths) != tuple(packet.forbidden_paths)
            or tuple(binding.required_tests) != tuple(packet.required_tests)
        ):
            raise ValueError("approval record does not bind to candidate packet")
        if (
            self.required_environment_spec.required_validation_command_ids
            != tuple(sorted(packet.required_tests))
        ):
            raise ValueError("required environment does not bind to candidate packet tests")

        bundle = _validation_bundle_payload(
            self.validation_bundle_json, self.validation_bundle_id
        )
        bundle_expectations = {
            "base_sha": packet.base_sha,
            "source_head_sha": packet.candidate_sha,
            "tested_sha": packet.tested_sha,
            "invocation_id": packet.invocation_id,
            "approval_id": approval.approval_id,
            "plan_id": self.validation_plan_id,
        }
        if any(bundle.get(name) != expected for name, expected in bundle_expectations.items()):
            raise ValueError("validation bundle does not bind to producer evidence")

        computed = pre_publication_evidence_id(self)
        if self.capsule_id:
            if (
                not _CAPSULE_ID_RE.fullmatch(self.capsule_id)
                or self.capsule_id != computed
            ):
                raise ValueError("capsule_id does not match capsule content")
        object.__setattr__(self, "capsule_id", computed)
        if len(serialize_pre_publication_evidence(self)) > MAX_CAPSULE_BYTES:
            raise ValueError("pre-publication evidence capsule exceeds size bound")


def _approval_payload(value: ApprovalRecord) -> dict[str, object]:
    decoded = json.loads(serialize_approval_record(value))
    if type(decoded) is not dict:
        raise ValueError("approval record serializer did not return an object")
    return decoded


def _validation_bundle_payload(
    payload_json: str, expected_id: str
) -> dict[str, object]:
    try:
        decoded = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError("validation_bundle_json is not canonical JSON") from exc
    if type(decoded) is not dict or decoded.get("bundle_id") != expected_id:
        raise ValueError("validation bundle identity does not match capsule")
    for name in (
        "authoritative",
        "execution_authorized",
        "merge_authorized",
        "attestation_verified",
        "side_effects_performed",
    ):
        if decoded.get(name) is not False:
            raise ValueError(f"validation bundle {name} must remain false")
    return decoded


def _payload(
    value: PrePublicationEvidenceCapsule, *, include_id: bool
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": value.schema_name,
        "schema_version": value.schema_version,
        "candidate_packet": serialize_candidate_packet(value.candidate_packet),
        "approval_record": _approval_payload(value.approval_record),
        "required_environment_spec": required_environment_spec_payload(
            value.required_environment_spec
        ),
        "validation_bundle_json": value.validation_bundle_json,
        "validation_plan_id": value.validation_plan_id,
        "validation_bundle_id": value.validation_bundle_id,
        "advisory_result_id": value.advisory_result_id,
        "advisory_render_id": value.advisory_render_id,
        "candidate_branch": value.candidate_branch,
        "workspace_request_id": value.workspace_request_id,
        "invalidation_events": list(value.invalidation_events),
        "checkpoint_id": value.checkpoint_id,
        "created_at": value.created_at,
        "expires_at": value.expires_at,
        "evaluated_at": value.evaluated_at,
        "repository_implementation_authorized": False,
        "execution_authorized": False,
        "publication_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "external_writes_authorized": False,
    }
    if include_id:
        payload["capsule_id"] = value.capsule_id
    return payload


def pre_publication_evidence_id(value: PrePublicationEvidenceCapsule) -> str:
    if type(value) is not PrePublicationEvidenceCapsule:
        raise TypeError("value must be an exact PrePublicationEvidenceCapsule")
    digest = hashlib.sha256(
        b"agent-os-pre-publication-producer-evidence:v1\0"
        + canonical_json_bytes(_payload(value, include_id=False))
    ).hexdigest()
    return f"pre-publication-evidence:{digest}"


def build_pre_publication_evidence(
    *,
    candidate_packet: CandidatePacket,
    pilot_input: SingleIssuePilotInput,
    required_environment_spec: RequiredEnvironmentSpec,
    checkpoint: ExecutionCheckpoint,
    created_at: str,
    expires_at: str,
) -> PrePublicationEvidenceCapsule:
    """Build one capsule from already-canonical producer evidence only."""
    if type(candidate_packet) is not CandidatePacket:
        raise TypeError("candidate_packet must be an exact CandidatePacket")
    if not isinstance(pilot_input, SingleIssuePilotInput):
        raise TypeError("pilot_input must be SingleIssuePilotInput")
    if type(required_environment_spec) is not RequiredEnvironmentSpec:
        raise TypeError(
            "required_environment_spec must be an exact RequiredEnvironmentSpec"
        )
    if type(checkpoint) is not ExecutionCheckpoint:
        raise TypeError("checkpoint must be an exact ExecutionCheckpoint")
    approval = pilot_input.approval_record
    if type(approval) is not ApprovalRecord:
        raise ValueError("runnable pilot input requires an exact approval record")
    if approval.approval_id != pilot_input.expected_approval_id:
        raise ValueError("pilot approval identity does not match approval record")
    projection = pilot_input.projection
    if (
        getattr(projection, "approval_id", None) != approval.approval_id
        or getattr(projection, "approval_revision", None) != approval.approval_revision
    ):
        raise ValueError("pilot projection does not bind to approval revision")

    if (
        candidate_packet.repository.casefold() != pilot_input.repository.casefold()
        or candidate_packet.issue_number != pilot_input.issue_numbers[0]
        or candidate_packet.invocation_id != pilot_input.invocation_id
        or candidate_packet.base_branch != pilot_input.base_branch
        or candidate_packet.base_sha != pilot_input.base_sha
        or candidate_packet.candidate_ref != pilot_input.branch
        or candidate_packet.candidate_sha != pilot_input.source_head_sha
        or candidate_packet.source_sha != pilot_input.source_head_sha
        or candidate_packet.tested_sha != pilot_input.tested_sha
        or tuple(candidate_packet.allowed_files) != tuple(pilot_input.allowed_files)
        or tuple(candidate_packet.forbidden_paths) != tuple(pilot_input.forbidden_paths)
        or tuple(candidate_packet.required_tests) != tuple(pilot_input.required_tests)
    ):
        raise ValueError("candidate packet does not bind to pilot input")
    if (
        checkpoint.repository.casefold() != candidate_packet.repository.casefold()
        or checkpoint.issue_number != candidate_packet.issue_number
        or checkpoint.invocation_id != candidate_packet.invocation_id
        or checkpoint.branch != pilot_input.branch
        or checkpoint.source_sha != candidate_packet.candidate_sha
        or checkpoint.tested_sha != candidate_packet.tested_sha
    ):
        raise ValueError("checkpoint does not bind to candidate packet")
    if (
        required_environment_spec.required_validation_command_ids
        != tuple(sorted(candidate_packet.required_tests))
    ):
        raise ValueError("required environment does not bind to candidate packet tests")

    plan_id = validation_plan_id(pilot_input.validation_plan)
    bundle_id = validation_evidence_bundle_id(pilot_input.evidence_bundle)
    advisory_id = advisory_evidence_result_id(pilot_input.advisory_result)
    render_id = advisory_render_result_id(pilot_input.advisory_render)
    if (
        pilot_input.expected_plan_id != plan_id
        or pilot_input.expected_bundle_id != bundle_id
        or pilot_input.expected_advisory_result_id != advisory_id
        or pilot_input.expected_advisory_render_id != render_id
        or getattr(pilot_input.evidence_bundle, "plan_id", None) != plan_id
        or getattr(pilot_input.advisory_result, "plan_id", None) != plan_id
        or getattr(pilot_input.advisory_result, "bundle_id", None) != bundle_id
        or getattr(pilot_input.advisory_render, "advisory_result_id", None)
        != advisory_id
    ):
        raise ValueError("pilot validation identities are not internally consistent")

    bundle_payload = serialize_validation_evidence_bundle(pilot_input.evidence_bundle)
    bundle_json = json.dumps(
        bundle_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return PrePublicationEvidenceCapsule(
        schema_name=CAPSULE_SCHEMA_NAME,
        schema_version=CAPSULE_SCHEMA_VERSION,
        candidate_packet=candidate_packet,
        approval_record=approval,
        required_environment_spec=required_environment_spec,
        validation_bundle_json=bundle_json,
        validation_plan_id=plan_id,
        validation_bundle_id=bundle_id,
        advisory_result_id=advisory_id,
        advisory_render_id=render_id,
        candidate_branch=pilot_input.branch,
        workspace_request_id=pilot_input.workspace_request_id,
        invalidation_events=tuple(pilot_input.invalidation_events),
        checkpoint_id=checkpoint.checkpoint_id,
        created_at=created_at,
        expires_at=expires_at,
        evaluated_at=pilot_input.evaluated_at,
    )


def serialize_pre_publication_evidence(
    value: PrePublicationEvidenceCapsule,
) -> bytes:
    if type(value) is not PrePublicationEvidenceCapsule:
        raise TypeError("value must be an exact PrePublicationEvidenceCapsule")
    payload = canonical_json_bytes(_payload(value, include_id=True))
    if len(payload) > MAX_CAPSULE_BYTES:
        raise ValueError("pre-publication evidence capsule exceeds size bound")
    return payload


def deserialize_pre_publication_evidence(
    payload: bytes | bytearray | memoryview | str,
) -> PrePublicationEvidenceCapsule:
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if len(raw) > MAX_CAPSULE_BYTES:
        raise ValueError("pre-publication evidence capsule exceeds size bound")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("pre-publication evidence capsule is not valid JSON") from exc
    expected = {
        "schema_name",
        "schema_version",
        "candidate_packet",
        "approval_record",
        "required_environment_spec",
        "validation_bundle_json",
        "validation_plan_id",
        "validation_bundle_id",
        "advisory_result_id",
        "advisory_render_id",
        "candidate_branch",
        "workspace_request_id",
        "invalidation_events",
        "checkpoint_id",
        "created_at",
        "expires_at",
        "evaluated_at",
        "capsule_id",
        "repository_implementation_authorized",
        "execution_authorized",
        "publication_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "external_writes_authorized",
    }
    if type(decoded) is not dict or set(decoded) != expected:
        raise ValueError("pre-publication evidence capsule fields drifted")
    for name in (
        "repository_implementation_authorized",
        "execution_authorized",
        "publication_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "external_writes_authorized",
    ):
        if decoded[name] is not False:
            raise ValueError(f"{name} must remain false")
    events = decoded["invalidation_events"]
    if type(events) is not list or any(type(item) is not str for item in events):
        raise ValueError("invalidation_events must be a list of strings")
    return PrePublicationEvidenceCapsule(
        schema_name=decoded["schema_name"],
        schema_version=decoded["schema_version"],
        candidate_packet=deserialize_candidate_packet(decoded["candidate_packet"]),
        approval_record=reconstruct_approval_record(decoded["approval_record"]),
        required_environment_spec=reconstruct_required_environment_spec(
            decoded["required_environment_spec"]
        ),
        validation_bundle_json=decoded["validation_bundle_json"],
        validation_plan_id=decoded["validation_plan_id"],
        validation_bundle_id=decoded["validation_bundle_id"],
        advisory_result_id=decoded["advisory_result_id"],
        advisory_render_id=decoded["advisory_render_id"],
        candidate_branch=decoded["candidate_branch"],
        workspace_request_id=decoded["workspace_request_id"],
        invalidation_events=tuple(events),
        checkpoint_id=decoded["checkpoint_id"],
        created_at=decoded["created_at"],
        expires_at=decoded["expires_at"],
        evaluated_at=decoded["evaluated_at"],
        capsule_id=decoded["capsule_id"],
    )
