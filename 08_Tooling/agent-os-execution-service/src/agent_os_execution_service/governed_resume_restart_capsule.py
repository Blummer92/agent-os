"""Bounded immutable restart evidence for governed-resume reconstruction (#1303).

The capsule is a continuation artifact, never an authority record.  It keeps only
non-authorizing evidence that cannot be recovered from current source owners:
the exact CandidatePacket, the immutable approval decision record, canonical
validation observations, and the small pilot identities needed to rebuild the
runtime and validation evidence.  Current issue/repository/authorization/lease
truth is deliberately absent and must be reacquired by #1218/#1253.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from scripts.agent_os_candidate_packet.models import (
    CandidatePacket,
    deserialize_candidate_packet,
    serialize_candidate_packet,
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
from scripts.agent_os_issue_acceptance.approval_records import (
    ApprovalRecord,
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
from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotInput

CAPSULE_SCHEMA_NAME = "agent-os-governed-resume-restart-capsule"
CAPSULE_SCHEMA_VERSION = "1.0"
MAX_CAPSULE_BYTES = 2 * 1024 * 1024
MAX_CAPSULES = 4096
MAX_CAPSULE_STORE_BYTES = 256 * 1024 * 1024

_HANDOFF_ID_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)
_CAPSULE_ID_RE = re.compile(
    r"^governed-resume-restart-capsule:[0-9a-f]{64}$", re.ASCII
)


class RestartCapsuleNotFound(LookupError):
    """Raised when one exact handoff has no persisted restart capsule."""


@dataclass(frozen=True, slots=True)
class AppendRestartCapsuleOutcome:
    capsule_id: str
    handoff_id: str
    path: Path
    already_present: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class GovernedResumeRestartCapsule:
    """One content-addressed, non-authorizing restart continuation record."""

    schema_name: Literal["agent-os-governed-resume-restart-capsule"]
    schema_version: Literal["1.0"]
    handoff_id: str
    candidate_packet: CandidatePacket
    approval_record: ApprovalRecord
    validation_bundle_json: str
    validation_plan_id: str
    validation_bundle_id: str
    advisory_result_id: str
    advisory_render_id: str
    candidate_branch: str
    workspace_request_id: str
    invalidation_events: tuple[str, ...]
    created_at: str
    expires_at: str
    evaluated_at: str
    capsule_id: str = ""
    repository_implementation_authorized: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != CAPSULE_SCHEMA_NAME or self.schema_version != CAPSULE_SCHEMA_VERSION:
            raise ValueError("unsupported governed-resume restart capsule schema")
        _handoff_id(self.handoff_id)
        if type(self.candidate_packet) is not CandidatePacket:
            raise TypeError("candidate_packet must be an exact CandidatePacket")
        if type(self.approval_record) is not ApprovalRecord:
            raise TypeError("approval_record must be an exact ApprovalRecord")
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
        _validation_bundle_payload(self.validation_bundle_json, self.validation_bundle_id)
        if type(self.invalidation_events) is not tuple or any(
            type(item) is not str or not item for item in self.invalidation_events
        ):
            raise TypeError("invalidation_events must be a tuple of non-empty strings")
        if len(set(self.invalidation_events)) != len(self.invalidation_events):
            raise ValueError("invalidation_events must be unique")
        computed = restart_capsule_id(self)
        if self.capsule_id:
            if not _CAPSULE_ID_RE.fullmatch(self.capsule_id):
                raise ValueError("capsule_id is malformed")
            if self.capsule_id != computed:
                raise ValueError("capsule_id does not match capsule content")
        object.__setattr__(self, "capsule_id", computed)
        if len(serialize_restart_capsule(self)) > MAX_CAPSULE_BYTES:
            raise ValueError("governed-resume restart capsule exceeds size bound")

    def validation_bundle_payload(self) -> dict[str, object]:
        return _validation_bundle_payload(
            self.validation_bundle_json,
            self.validation_bundle_id,
        )


def _handoff_id(value: object) -> str:
    if type(value) is not str or not _HANDOFF_ID_RE.fullmatch(value):
        raise TypeError("handoff_id must be executor-handoff:<64-lowercase-hex>")
    return value


def _approval_payload(value: ApprovalRecord) -> dict[str, object]:
    decoded = json.loads(serialize_approval_record(value))
    if type(decoded) is not dict:
        raise ValueError("approval record serializer did not return an object")
    return decoded


def _validation_bundle_payload(payload_json: str, expected_id: str) -> dict[str, object]:
    try:
        decoded = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError("validation_bundle_json is not canonical JSON") from exc
    if type(decoded) is not dict:
        raise ValueError("validation_bundle_json must encode an object")
    if decoded.get("bundle_id") != expected_id:
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


def _payload(value: GovernedResumeRestartCapsule, *, include_id: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": value.schema_name,
        "schema_version": value.schema_version,
        "handoff_id": value.handoff_id,
        "candidate_packet": serialize_candidate_packet(value.candidate_packet),
        "approval_record": _approval_payload(value.approval_record),
        "validation_bundle_json": value.validation_bundle_json,
        "validation_plan_id": value.validation_plan_id,
        "validation_bundle_id": value.validation_bundle_id,
        "advisory_result_id": value.advisory_result_id,
        "advisory_render_id": value.advisory_render_id,
        "candidate_branch": value.candidate_branch,
        "workspace_request_id": value.workspace_request_id,
        "invalidation_events": list(value.invalidation_events),
        "created_at": value.created_at,
        "expires_at": value.expires_at,
        "evaluated_at": value.evaluated_at,
        "repository_implementation_authorized": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "external_writes_authorized": False,
    }
    if include_id:
        payload["capsule_id"] = value.capsule_id
    return payload


def restart_capsule_id(value: GovernedResumeRestartCapsule) -> str:
    digest = hashlib.sha256(
        b"agent-os-governed-resume-restart-capsule:v1\0"
        + canonical_json_bytes(_payload(value, include_id=False))
    ).hexdigest()
    return f"governed-resume-restart-capsule:{digest}"


def build_restart_capsule(
    *,
    handoff_id: str,
    candidate_packet: CandidatePacket,
    pilot_input: SingleIssuePilotInput,
    created_at: str,
    expires_at: str,
) -> GovernedResumeRestartCapsule:
    """Build the one bounded restart capsule from already-verified publication inputs."""
    _handoff_id(handoff_id)
    if type(candidate_packet) is not CandidatePacket:
        raise TypeError("candidate_packet must be an exact CandidatePacket")
    if not isinstance(pilot_input, SingleIssuePilotInput):
        raise TypeError("pilot_input must be SingleIssuePilotInput")
    approval = pilot_input.approval_record
    if type(approval) is not ApprovalRecord:
        raise ValueError("runnable pilot input requires an exact approval record")
    if (
        candidate_packet.repository.casefold() != pilot_input.repository.casefold()
        or candidate_packet.issue_number != pilot_input.issue_numbers[0]
        or candidate_packet.invocation_id != pilot_input.invocation_id
        or candidate_packet.candidate_sha != pilot_input.source_head_sha
        or tuple(candidate_packet.allowed_files) != tuple(pilot_input.allowed_files)
        or tuple(candidate_packet.forbidden_paths) != tuple(pilot_input.forbidden_paths)
        or tuple(candidate_packet.required_tests) != tuple(pilot_input.required_tests)
    ):
        raise ValueError("candidate packet does not bind to pilot input")

    bundle_id = validation_evidence_bundle_id(pilot_input.evidence_bundle)
    advisory_id = advisory_evidence_result_id(pilot_input.advisory_result)
    render_id = advisory_render_result_id(pilot_input.advisory_render)
    if (
        pilot_input.expected_plan_id != getattr(pilot_input.evidence_bundle, "plan_id", None)
        or pilot_input.expected_bundle_id != bundle_id
        or pilot_input.expected_advisory_result_id != advisory_id
        or pilot_input.expected_advisory_render_id != render_id
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
    return GovernedResumeRestartCapsule(
        schema_name=CAPSULE_SCHEMA_NAME,
        schema_version=CAPSULE_SCHEMA_VERSION,
        handoff_id=handoff_id,
        candidate_packet=candidate_packet,
        approval_record=approval,
        validation_bundle_json=bundle_json,
        validation_plan_id=pilot_input.expected_plan_id,
        validation_bundle_id=bundle_id,
        advisory_result_id=advisory_id,
        advisory_render_id=render_id,
        candidate_branch=pilot_input.branch,
        workspace_request_id=pilot_input.workspace_request_id,
        invalidation_events=tuple(pilot_input.invalidation_events),
        created_at=created_at,
        expires_at=expires_at,
        evaluated_at=pilot_input.evaluated_at,
    )


def serialize_restart_capsule(value: GovernedResumeRestartCapsule) -> bytes:
    if type(value) is not GovernedResumeRestartCapsule:
        raise TypeError("value must be an exact GovernedResumeRestartCapsule")
    payload = canonical_json_bytes(_payload(value, include_id=True))
    if len(payload) > MAX_CAPSULE_BYTES:
        raise ValueError("governed-resume restart capsule exceeds size bound")
    return payload


def deserialize_restart_capsule(payload: bytes | bytearray | memoryview | str) -> GovernedResumeRestartCapsule:
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if len(raw) > MAX_CAPSULE_BYTES:
        raise ValueError("governed-resume restart capsule exceeds size bound")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("governed-resume restart capsule is not valid JSON") from exc
    if type(decoded) is not dict:
        raise ValueError("governed-resume restart capsule must be an object")
    expected = {
        "schema_name", "schema_version", "handoff_id", "candidate_packet",
        "approval_record", "validation_bundle_json", "validation_plan_id",
        "validation_bundle_id", "advisory_result_id", "advisory_render_id",
        "candidate_branch", "workspace_request_id", "invalidation_events",
        "created_at", "expires_at", "evaluated_at", "capsule_id",
        "repository_implementation_authorized", "execution_authorized",
        "github_writes_authorized", "merge_authorized", "issue_closure_authorized",
        "external_writes_authorized",
    }
    if set(decoded) != expected:
        raise ValueError("governed-resume restart capsule fields drifted")
    for name in (
        "repository_implementation_authorized", "execution_authorized",
        "github_writes_authorized", "merge_authorized", "issue_closure_authorized",
        "external_writes_authorized",
    ):
        if decoded[name] is not False:
            raise ValueError(f"{name} must remain false")
    invalidation_events = decoded["invalidation_events"]
    if type(invalidation_events) is not list or any(type(item) is not str for item in invalidation_events):
        raise ValueError("invalidation_events must be a list of strings")
    return GovernedResumeRestartCapsule(
        schema_name=decoded["schema_name"],
        schema_version=decoded["schema_version"],
        handoff_id=decoded["handoff_id"],
        candidate_packet=deserialize_candidate_packet(decoded["candidate_packet"]),
        approval_record=reconstruct_approval_record(decoded["approval_record"]),
        validation_bundle_json=decoded["validation_bundle_json"],
        validation_plan_id=decoded["validation_plan_id"],
        validation_bundle_id=decoded["validation_bundle_id"],
        advisory_result_id=decoded["advisory_result_id"],
        advisory_render_id=decoded["advisory_render_id"],
        candidate_branch=decoded["candidate_branch"],
        workspace_request_id=decoded["workspace_request_id"],
        invalidation_events=tuple(invalidation_events),
        created_at=decoded["created_at"],
        expires_at=decoded["expires_at"],
        evaluated_at=decoded["evaluated_at"],
        capsule_id=decoded["capsule_id"],
    )


def _directory(store_root: Path | str) -> Path:
    return Path(store_root) / "governed-resume-restart-capsules"


def _filename(handoff_id: str) -> str:
    return f"{_handoff_id(handoff_id).rsplit(':', 1)[-1]}.json"


def append_restart_capsule(
    store_root: Path | str,
    capsule: GovernedResumeRestartCapsule,
) -> AppendRestartCapsuleOutcome:
    if type(capsule) is not GovernedResumeRestartCapsule:
        raise TypeError("capsule must be an exact GovernedResumeRestartCapsule")
    directory = _directory(store_root)
    _reject_symlink(directory)
    _ensure_dir(directory)
    payload = serialize_restart_capsule(capsule)
    destination = directory / _filename(capsule.handoff_id)
    if not destination.exists():
        count, total_bytes = _existing_records_footprint(directory)
        if count + 1 > MAX_CAPSULES or total_bytes + len(payload) > MAX_CAPSULE_STORE_BYTES:
            raise CheckpointStoreCapacityExceeded("governed-resume restart capsule store is at capacity")
    path, already_present = _atomic_write(directory, destination.name, payload)
    return AppendRestartCapsuleOutcome(
        capsule_id=capsule.capsule_id,
        handoff_id=capsule.handoff_id,
        path=path,
        already_present=already_present,
    )


def load_restart_capsule(
    store_root: Path | str,
    handoff_id: str,
) -> GovernedResumeRestartCapsule:
    canonical = _handoff_id(handoff_id)
    directory = _directory(store_root)
    _reject_symlink(directory)
    path = directory / _filename(canonical)
    _reject_symlink(path)
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise RestartCapsuleNotFound(canonical) from exc
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {path}") from exc
    try:
        capsule = deserialize_restart_capsule(payload)
    except (TypeError, ValueError) as exc:
        raise CheckpointStoreIntegrityConflict(str(exc)) from exc
    if capsule.handoff_id != canonical or path.name != _filename(capsule.handoff_id):
        raise CheckpointStoreIntegrityConflict(
            "persisted restart capsule does not match requested handoff identity"
        )
    return capsule
