"""Unified validation-lifecycle evidence bundle and terminal-result projection.

Issue #761 defines exactly one immutable, content-addressed evidence bundle
(``ValidationLifecycleEvidenceBundle``) and exactly one deterministic
top-level terminal-result projection (``ValidationLifecycleResult``) over the
already-canonical lower-level evidence produced by #757 (authorized-admission
request/verifier), #758/#759 (lease and process-tree containment, surfaced
through ``SingleIssuePilotResult``), #760 (workspace-state and changed-path
evidence), and the existing Execution Service composition boundary
(``ExecutionCompositionResult``).

This module owns none of that lower-level semantics. It never re-parses Git
status, never re-implements lease acquisition/release, never re-implements
process-tree termination proof, and never rewrites a lower-level status or
identity. It only verifies the supplied canonical objects belong together
(matching repository, SHA roles, request/plan/runtime fingerprints, and
result identities), preserves them by reference/identity, and projects one
additive, deterministic top-level terminal status over the verified whole.

Three dimensions stay separate everywhere in this module:

* authorization/admission truth -- from the #757 admission result;
* observed runtime/lifecycle truth -- from the embedded lower-level results;
* evidence completeness/integrity -- from the bundle's own verification and
  the ``evidence_availability`` ledger.

Constructing or serializing a bundle performs no I/O, no subprocess, no
network or provider call, no filesystem write, no GitHub publication, no
cleanup, no lease release, no retry, and no execution. ``side_effects_performed``
records what the embedded lower-level evidence already proves happened; it is
never inferred from the projected terminal status, and building this bundle
itself never performs a side effect.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .authorized_validation import (
    AuthorizedValidationAdmissionResult,
    AuthorizedValidationAdmissionStatus,
    AuthorizedValidationLifecycleRequest,
    verify_authorized_validation_admission,
)
from .execution_composition import ExecutionCompositionResult, ExecutionCompositionStatus
from .models import parse_canonical_utc

VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION = "1.0"

MAX_BUNDLE_SERIALIZED_BYTES = 1_048_576
MAX_REASON_CODES = 64
MAX_REASON_CODE_LENGTH = 256
MAX_EVIDENCE_AVAILABILITY_ITEMS = 32
MAX_FIELD_NAME_LENGTH = 128
MAX_DIAGNOSTIC_TEXT_LENGTH = 2_048

_TERMINATION_UNCERTAIN_REASON_CODES = frozenset(
    {"executor.termination-unconfirmed", "cancellation.unconfirmed"}
)
_CLEANUP_FAILURE_REASON_CODES = frozenset(
    {"workspace.filesystem-cleanup-failed", "workspace.metadata-cleanup-failed"}
)
_RELEASE_FAILURE_REASON_CODES = frozenset(
    {"lease.release-failed", "lease.release-ambiguous", "lease.release-forced"}
)

_KNOWN_PILOT_STATUSES = frozenset(
    {"completed", "blocked", "stale", "cancelled", "timed-out", "failed", "quarantined", "needs-decision"}
)


class ValidationLifecycleEvidenceError(ValueError):
    """Raised for malformed, tampered, substituted, or unverifiable evidence."""


class ValidationLifecycleTerminalStatus(str, Enum):
    """Exactly the eleven public terminal statuses #761 is authorized to add.

    No existing lower-level ``SingleIssuePilotResult``/``PilotStatus``,
    ``ExecutionCompositionStatus``, quarantine, or validation status is
    renamed, removed, or reinterpreted by this enum; it is an additive
    top-level projection over verified lower-level evidence only.
    """

    SUCCEEDED = "succeeded"
    VALIDATION_FAILED = "validation-failed"
    BLOCKED = "blocked"
    STALE = "stale"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"
    QUARANTINED = "quarantined"
    CLEANUP_FAILED = "cleanup-failed"
    RELEASE_FAILED = "release-failed"
    TERMINATION_UNCERTAIN = "termination-uncertain"
    EVIDENCE_INCOMPLETE = "evidence-incomplete"


# The one explicit, frozen precedence table for lifecycles that validly
# entered post-admission execution. Highest-dominance first. ``BLOCKED`` and
# ``STALE`` are pre-execution/admission statuses and are never selected from
# this table -- they are decided before this table is ever consulted (see
# ``project_validation_lifecycle_result``).
POST_ADMISSION_TERMINAL_STATUS_PRECEDENCE: tuple[ValidationLifecycleTerminalStatus, ...] = (
    ValidationLifecycleTerminalStatus.QUARANTINED,
    ValidationLifecycleTerminalStatus.TERMINATION_UNCERTAIN,
    ValidationLifecycleTerminalStatus.CLEANUP_FAILED,
    ValidationLifecycleTerminalStatus.RELEASE_FAILED,
    ValidationLifecycleTerminalStatus.TIMED_OUT,
    ValidationLifecycleTerminalStatus.CANCELLED,
    ValidationLifecycleTerminalStatus.EVIDENCE_INCOMPLETE,
    ValidationLifecycleTerminalStatus.VALIDATION_FAILED,
    ValidationLifecycleTerminalStatus.SUCCEEDED,
)


class EvidenceAvailability(str, Enum):
    """Explicit typed distinction for why an optional bundle field is absent.

    Reused across every optional nested evidence slot instead of scattering
    ambiguous ``None`` as the sole semantic signal. Derived automatically
    from bundle content in ``__post_init__``; never caller-asserted.
    """

    PRESENT = "present"
    NOT_APPLICABLE = "not-applicable"
    UNAVAILABLE = "unavailable"
    MISSING_REQUIRED = "missing-required"


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceAvailabilityRecord:
    field_name: str
    availability: EvidenceAvailability
    reason: str = ""

    def __post_init__(self) -> None:
        _bounded_text(self.field_name, "field_name", maximum=MAX_FIELD_NAME_LENGTH)
        if type(self.availability) is not EvidenceAvailability:
            raise TypeError("availability must be an exact EvidenceAvailability")
        _bounded_text(self.reason, "reason", maximum=MAX_DIAGNOSTIC_TEXT_LENGTH, allow_empty=True)

    def as_dict(self) -> dict[str, object]:
        return {
            "field_name": self.field_name,
            "availability": self.availability.value,
            "reason": self.reason,
        }


def _bounded_text(value: object, name: str, *, maximum: int, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not allow_empty and not value:
        raise ValidationLifecycleEvidenceError(f"{name} must be non-empty")
    if len(value) > maximum:
        raise ValidationLifecycleEvidenceError(f"{name} exceeds the bounded length")
    if any(ord(ch) < 0x20 and ch not in ("\n", "\t") or ord(ch) == 0x7F for ch in value):
        raise ValidationLifecycleEvidenceError(f"{name} contains control characters")
    return value


def _bounded_reason_codes(values: object) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError("reason_codes must be an exact tuple")
    if len(values) > MAX_REASON_CODES:
        raise ValidationLifecycleEvidenceError("reason_codes exceeds the bounded count")
    for item in values:
        _bounded_text(item, "reason_code", maximum=MAX_REASON_CODE_LENGTH)
    if len(set(values)) != len(values):
        raise ValidationLifecycleEvidenceError("reason_codes must be unique")
    if tuple(sorted(values)) != values:
        raise ValidationLifecycleEvidenceError("reason_codes must be sorted")
    return values


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def _digest(domain: str, payload: object) -> str:
    return hashlib.sha256(
        f"agent-os-validation-lifecycle-evidence:{domain}:v1\0".encode("ascii") + _canonical_bytes(payload)
    ).hexdigest()


# ---------------------------------------------------------------------------
# Lower-level canonical types are imported lazily inside functions/properties
# that need them so importing this pure evidence module never makes the
# Workflow Scheduler runtime reachable as an import-time side effect, mirroring
# the existing lazy-composition pattern in ``execution_composition``/``__init__``.
# ---------------------------------------------------------------------------


def _pilot_result_type():
    from workflow_scheduler.execution.single_issue_pilot import SingleIssuePilotResult

    return SingleIssuePilotResult


def _pilot_result_id_fn():
    from workflow_scheduler.execution.single_issue_pilot import single_issue_pilot_result_id

    return single_issue_pilot_result_id


def _pilot_result_serializer():
    from workflow_scheduler.execution.single_issue_pilot import serialize_single_issue_pilot_result

    return serialize_single_issue_pilot_result


def _workspace_lifecycle_evidence_type():
    from workflow_scheduler.execution.workspace_state_evidence import WorkspaceLifecycleEvidence

    return WorkspaceLifecycleEvidence


def _workspace_state_observation_type():
    from workflow_scheduler.execution.workspace_state_evidence import WorkspaceStateObservation

    return WorkspaceStateObservation


def _changed_path_observation_type():
    from workflow_scheduler.execution.workspace_state_evidence import ChangedPathObservation

    return ChangedPathObservation


def _worktree_list_record_type():
    from workflow_scheduler.execution.workspace_state_evidence import WorktreeListRecord

    return WorktreeListRecord


def _quarantine_packet_type():
    from workflow_scheduler.execution.quarantine_review import QuarantineEvidencePacket

    return QuarantineEvidencePacket


def _quarantine_packet_serializer():
    from workflow_scheduler.execution.quarantine_review import serialize_quarantine_evidence_packet

    return serialize_quarantine_evidence_packet


def _quarantine_packet_id_fn():
    from workflow_scheduler.execution.quarantine_review import quarantine_evidence_packet_id

    return quarantine_evidence_packet_id


def _frozen_test_validation_result_type():
    from workflow_scheduler.execution.frozen_test_validation_adapter import FrozenTestValidationResult

    return FrozenTestValidationResult


def _command_run_observation_type():
    from workflow_scheduler.execution.frozen_test_validation_adapter import CommandRunObservation

    return CommandRunObservation


# ---------------------------------------------------------------------------
# The bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationLifecycleEvidenceBundle:
    """One immutable, content-addressed unified validation-lifecycle bundle.

    Every field below is either (a) an already-canonical, already-immutable
    lower-level evidence object embedded by reference/identity, or (b) a
    small amount of #761-owned bookkeeping (schema version, evaluated_at,
    the derived evidence-availability ledger, and the computed ``bundle_id``).
    No field copies human-readable prose from a lower-level object as
    authoritative evidence; every field below the docstring line is either the
    real object or a value independently recomputed from it.
    """

    schema_version: str
    evaluated_at: str
    admission_request: AuthorizedValidationLifecycleRequest
    admission_result: AuthorizedValidationAdmissionResult
    execution_composition: ExecutionCompositionResult | None = None
    pilot_result: object | None = None
    workspace_lifecycle_evidence: object | None = None
    quarantine_packet: object | None = None
    evidence_availability: tuple[EvidenceAvailabilityRecord, ...] = field(init=False)
    side_effects_performed: bool = field(init=False)
    bundle_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION:
            raise ValidationLifecycleEvidenceError("unsupported validation-lifecycle-evidence schema")
        parse_canonical_utc(self.evaluated_at)

        if type(self.admission_request) is not AuthorizedValidationLifecycleRequest:
            raise TypeError("admission_request must be exact AuthorizedValidationLifecycleRequest")
        if type(self.admission_result) is not AuthorizedValidationAdmissionResult:
            raise TypeError("admission_result must be exact AuthorizedValidationAdmissionResult")

        # Reuse the canonical #757 verifier itself to re-prove admission_result
        # belongs to admission_request -- never re-derive admission semantics
        # here. Any drift (identity substitution, tamper, replay, or a stale
        # evaluated_at) fails closed.
        recomputed_admission = verify_authorized_validation_admission(
            self.admission_request, evaluated_at=self.admission_result.evaluated_at
        )
        if recomputed_admission != self.admission_result:
            raise ValidationLifecycleEvidenceError(
                "admission_result does not match recomputed admission for admission_request"
            )
        if self.admission_result.request_id != self.admission_request.request_id:
            raise ValidationLifecycleEvidenceError("admission_result.request_id identity mismatch")

        accepted = self.admission_result.status is AuthorizedValidationAdmissionStatus.ACCEPTED

        if not accepted:
            # Pre-execution admission truth is authoritative. Any downstream
            # runtime evidence attached to a non-accepted admission can only
            # be contradictory (the lifecycle was never authorized to run),
            # so construction fails closed rather than silently discarding or
            # overwriting the admission truth with it.
            if any(
                item is not None
                for item in (
                    self.execution_composition,
                    self.pilot_result,
                    self.workspace_lifecycle_evidence,
                    self.quarantine_packet,
                )
            ):
                raise ValidationLifecycleEvidenceError(
                    "contradictory post-execution evidence attached to a non-accepted admission"
                )
            object.__setattr__(self, "side_effects_performed", False)
            object.__setattr__(
                self,
                "evidence_availability",
                (
                    EvidenceAvailabilityRecord(
                        field_name="execution_composition",
                        availability=EvidenceAvailability.NOT_APPLICABLE,
                        reason="admission-not-accepted",
                    ),
                    EvidenceAvailabilityRecord(
                        field_name="pilot_result",
                        availability=EvidenceAvailability.NOT_APPLICABLE,
                        reason="admission-not-accepted",
                    ),
                    EvidenceAvailabilityRecord(
                        field_name="workspace_lifecycle_evidence",
                        availability=EvidenceAvailability.NOT_APPLICABLE,
                        reason="admission-not-accepted",
                    ),
                    EvidenceAvailabilityRecord(
                        field_name="quarantine_packet",
                        availability=EvidenceAvailability.NOT_APPLICABLE,
                        reason="admission-not-accepted",
                    ),
                ),
            )
            object.__setattr__(self, "bundle_id", _digest("bundle", self._identity_payload()))
            return

        availability: list[EvidenceAvailabilityRecord] = []

        if self.execution_composition is None:
            availability.append(
                EvidenceAvailabilityRecord(
                    field_name="execution_composition",
                    availability=EvidenceAvailability.MISSING_REQUIRED,
                    reason="admission-accepted-without-composition-evidence",
                )
            )
        else:
            if type(self.execution_composition) is not ExecutionCompositionResult:
                raise TypeError("execution_composition must be exact ExecutionCompositionResult")
            self._verify_execution_composition_join()
            availability.append(
                EvidenceAvailabilityRecord(
                    field_name="execution_composition", availability=EvidenceAvailability.PRESENT
                )
            )

        PilotResultType = _pilot_result_type()
        if self.pilot_result is None:
            availability.append(
                EvidenceAvailabilityRecord(
                    field_name="pilot_result",
                    availability=EvidenceAvailability.MISSING_REQUIRED,
                    reason="admission-accepted-without-pilot-evidence",
                )
            )
        else:
            if type(self.pilot_result) is not PilotResultType:
                raise TypeError("pilot_result must be exact SingleIssuePilotResult")
            self._verify_pilot_result_join()
            availability.append(
                EvidenceAvailabilityRecord(field_name="pilot_result", availability=EvidenceAvailability.PRESENT)
            )

        WorkspaceLifecycleEvidenceType = _workspace_lifecycle_evidence_type()
        if self.workspace_lifecycle_evidence is None:
            availability.append(
                EvidenceAvailabilityRecord(
                    field_name="workspace_lifecycle_evidence",
                    availability=EvidenceAvailability.MISSING_REQUIRED,
                    reason="admission-accepted-without-workspace-evidence",
                )
            )
        else:
            if type(self.workspace_lifecycle_evidence) is not WorkspaceLifecycleEvidenceType:
                raise TypeError("workspace_lifecycle_evidence must be exact WorkspaceLifecycleEvidence")
            self._verify_workspace_lifecycle_evidence_join()
            availability.append(
                EvidenceAvailabilityRecord(
                    field_name="workspace_lifecycle_evidence", availability=EvidenceAvailability.PRESENT
                )
            )

        QuarantinePacketType = _quarantine_packet_type()
        pilot_is_quarantined = (
            self.pilot_result is not None and getattr(self.pilot_result, "status", None) == "quarantined"
        )
        if self.quarantine_packet is None:
            availability.append(
                EvidenceAvailabilityRecord(
                    field_name="quarantine_packet",
                    availability=(
                        EvidenceAvailability.MISSING_REQUIRED
                        if pilot_is_quarantined
                        else EvidenceAvailability.NOT_APPLICABLE
                    ),
                    reason="pilot-quarantined" if pilot_is_quarantined else "pilot-not-quarantined",
                )
            )
        else:
            if type(self.quarantine_packet) is not QuarantinePacketType:
                raise TypeError("quarantine_packet must be exact QuarantineEvidencePacket")
            if not pilot_is_quarantined:
                raise ValidationLifecycleEvidenceError(
                    "quarantine_packet supplied without a quarantined pilot_result"
                )
            self._verify_quarantine_packet_join()
            availability.append(
                EvidenceAvailabilityRecord(
                    field_name="quarantine_packet", availability=EvidenceAvailability.PRESENT
                )
            )

        if len(availability) > MAX_EVIDENCE_AVAILABILITY_ITEMS:
            raise ValidationLifecycleEvidenceError("evidence_availability exceeds the bounded item count")
        object.__setattr__(self, "evidence_availability", tuple(availability))

        # side_effects_performed is read directly from the already-verified
        # lower-level ExecutionCompositionResult (itself derived only from
        # SingleIssuePilotResult observed fields) -- never derived from the
        # projected terminal status, and never recomputed by this module.
        object.__setattr__(
            self,
            "side_effects_performed",
            bool(self.execution_composition.side_effects_performed) if self.execution_composition else False,
        )
        object.__setattr__(self, "bundle_id", _digest("bundle", self._identity_payload()))

    # -- join verification -------------------------------------------------

    def _verify_execution_composition_join(self) -> None:
        composition = self.execution_composition
        authorization = self.admission_request.execution_authorization
        execution_stage = self.admission_request.execution_packet_stage
        if composition.request_fingerprint != authorization.request_fingerprint:
            raise ValidationLifecycleEvidenceError("execution_composition.request_fingerprint identity mismatch")
        if composition.command_plan_id != authorization.command_plan_id:
            raise ValidationLifecycleEvidenceError("execution_composition.command_plan_id identity mismatch")
        if composition.repository.casefold() != authorization.repository.casefold():
            raise ValidationLifecycleEvidenceError("execution_composition.repository identity mismatch")
        if composition.expected_sha != authorization.expected_sha:
            raise ValidationLifecycleEvidenceError("execution_composition.expected_sha identity mismatch")
        if execution_stage.request is not None and composition.request_fingerprint != execution_stage.request_fingerprint:
            raise ValidationLifecycleEvidenceError("execution_composition/execution-packet request fingerprint drift")

    def _verify_pilot_result_join(self) -> None:
        pilot = self.pilot_result
        composition = self.execution_composition
        authorization = self.admission_request.execution_authorization
        pilot_id_fn = _pilot_result_id_fn()
        # Reuses the canonical identity function; never re-derives the digest.
        pilot_id_fn(pilot)
        if pilot.repository.casefold() != authorization.repository.casefold():
            raise ValidationLifecycleEvidenceError("pilot_result.repository identity mismatch")
        if pilot.tested_sha != authorization.expected_sha:
            raise ValidationLifecycleEvidenceError("pilot_result.tested_sha identity mismatch")
        if pilot.invocation_id != self.admission_request.authorized_invocation_id:
            raise ValidationLifecycleEvidenceError("pilot_result.invocation_id identity mismatch")
        if composition is not None:
            if not (set(pilot.reason_codes) <= set(composition.reason_codes)):
                raise ValidationLifecycleEvidenceError(
                    "pilot_result.reason_codes is not a subset of execution_composition.reason_codes"
                )
            if composition.status is ExecutionCompositionStatus.CANCELLED and pilot.status != "cancelled":
                raise ValidationLifecycleEvidenceError("pilot_result.status inconsistent with cancelled composition")
            if composition.status in (
                ExecutionCompositionStatus.AGGREGATE_PASS,
                ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING,
            ) and pilot.status != "completed":
                raise ValidationLifecycleEvidenceError("pilot_result.status inconsistent with a passing composition")
            if composition.validation_result is not None:
                if pilot.validation_attempted != composition.validation_result.attempted:
                    raise ValidationLifecycleEvidenceError("pilot_result.validation_attempted drift")
                if composition.validation_result.attempted and pilot.validation_passed != bool(
                    composition.validation_result.passed
                ):
                    raise ValidationLifecycleEvidenceError("pilot_result.validation_passed drift")

    def _verify_workspace_lifecycle_evidence_join(self) -> None:
        evidence = self.workspace_lifecycle_evidence
        execution_stage = self.admission_request.execution_packet_stage
        runtime = execution_stage.runtime_configuration
        authorization = self.admission_request.execution_authorization
        for observation in (evidence.initial, evidence.final):
            if observation.repository_owner.casefold() != runtime.repository_identity.owner.casefold():
                raise ValidationLifecycleEvidenceError("workspace evidence repository_owner identity mismatch")
            if observation.repository_name.casefold() != runtime.repository_identity.repository.casefold():
                raise ValidationLifecycleEvidenceError("workspace evidence repository_name identity mismatch")
            if observation.expected_sha != authorization.expected_sha:
                raise ValidationLifecycleEvidenceError("workspace evidence expected_sha identity mismatch")
        if evidence.validation_only is not True:
            raise ValidationLifecycleEvidenceError("workspace evidence must be validation-only for this lifecycle")
        if self.pilot_result is not None:
            observed = evidence.final.all_changed_paths
            claimed = frozenset(self.pilot_result.changed_paths)
            if observed != claimed:
                raise ValidationLifecycleEvidenceError(
                    "pilot_result.changed_paths does not match #760 final changed-path evidence"
                )

    def _verify_quarantine_packet_join(self) -> None:
        packet = self.quarantine_packet
        pilot = self.pilot_result
        serializer = _quarantine_packet_serializer()
        packet_id_fn = _quarantine_packet_id_fn()
        # Reuses the canonical serializer, which itself re-verifies packet_id.
        serializer(packet)
        if packet.packet_id != packet_id_fn(packet):
            raise ValidationLifecycleEvidenceError("quarantine_packet.packet_id identity mismatch")
        if packet.result_id != _pilot_result_id_fn()(pilot):
            raise ValidationLifecycleEvidenceError("quarantine_packet.result_id does not bind pilot_result")
        for name in ("repository", "invocation_id", "base_sha", "source_head_sha", "tested_sha", "status"):
            if getattr(packet, name) != getattr(pilot, name):
                raise ValidationLifecycleEvidenceError(f"quarantine_packet.{name} drift from pilot_result")

    # -- identity ------------------------------------------------------------

    def _identity_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "domain": "agent-os-validation-lifecycle-evidence-bundle",
            "schema_version": self.schema_version,
            "evaluated_at": self.evaluated_at,
            "admission_request_id": self.admission_request.request_id,
            "admission_status": self.admission_result.status.value,
            "admission_reason_codes": list(self.admission_result.reason_codes),
        }
        payload["execution_composition_evidence_id"] = (
            self.execution_composition.evidence_id if self.execution_composition is not None else None
        )
        payload["pilot_result_id"] = self.pilot_result.result_id if self.pilot_result is not None else None
        payload["workspace_lifecycle_id"] = (
            self.workspace_lifecycle_evidence.lifecycle_id if self.workspace_lifecycle_evidence is not None else None
        )
        payload["quarantine_packet_id"] = (
            self.quarantine_packet.packet_id if self.quarantine_packet is not None else None
        )
        return payload


def build_validation_lifecycle_evidence_bundle(
    *,
    evaluated_at: str,
    admission_request: AuthorizedValidationLifecycleRequest,
    admission_result: AuthorizedValidationAdmissionResult,
    execution_composition: ExecutionCompositionResult | None = None,
    pilot_result: object | None = None,
    workspace_lifecycle_evidence: object | None = None,
    quarantine_packet: object | None = None,
) -> ValidationLifecycleEvidenceBundle:
    """Build one immutable, verified bundle. Performs no I/O and no execution."""
    return ValidationLifecycleEvidenceBundle(
        schema_version=VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        evaluated_at=evaluated_at,
        admission_request=admission_request,
        admission_result=admission_result,
        execution_composition=execution_composition,
        pilot_result=pilot_result,
        workspace_lifecycle_evidence=workspace_lifecycle_evidence,
        quarantine_packet=quarantine_packet,
    )


# ---------------------------------------------------------------------------
# Terminal-result projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationLifecycleResult:
    """One deterministic, reconstructable top-level terminal-result projection."""

    schema_version: str
    bundle_id: str
    request_id: str
    status: ValidationLifecycleTerminalStatus
    reason_codes: tuple[str, ...]
    execution_authorized: bool
    side_effects_performed: bool
    evaluated_at: str
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION:
            raise ValidationLifecycleEvidenceError("unsupported validation-lifecycle-result schema")
        _bounded_text(self.bundle_id, "bundle_id", maximum=256)
        _bounded_text(self.request_id, "request_id", maximum=256)
        if type(self.status) is not ValidationLifecycleTerminalStatus:
            raise TypeError("status must be exact ValidationLifecycleTerminalStatus")
        object.__setattr__(self, "reason_codes", _bounded_reason_codes(self.reason_codes))
        if type(self.execution_authorized) is not bool:
            raise TypeError("execution_authorized must be an exact boolean")
        if type(self.side_effects_performed) is not bool:
            raise TypeError("side_effects_performed must be an exact boolean")
        parse_canonical_utc(self.evaluated_at)
        payload = {
            "domain": "agent-os-validation-lifecycle-result",
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "request_id": self.request_id,
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "execution_authorized": self.execution_authorized,
            "side_effects_performed": self.side_effects_performed,
            "evaluated_at": self.evaluated_at,
        }
        object.__setattr__(self, "result_id", _digest("result", payload))


def _admission_reasons(bundle: ValidationLifecycleEvidenceBundle) -> tuple[str, ...]:
    return tuple(f"admission.{code}" for code in bundle.admission_result.reason_codes)


def _post_admission_predicates(
    bundle: ValidationLifecycleEvidenceBundle,
) -> dict[ValidationLifecycleTerminalStatus, tuple[bool, tuple[str, ...]]]:
    """Pure boolean predicates for every post-admission status, plus reasons.

    This is the single place non-preexecution precedence is decided; nothing
    else in this module branches on status per-field.
    """

    pilot = bundle.pilot_result
    composition = bundle.execution_composition
    workspace = bundle.workspace_lifecycle_evidence
    quarantine_packet = bundle.quarantine_packet

    missing_required = tuple(
        item.field_name for item in bundle.evidence_availability if item.availability is EvidenceAvailability.MISSING_REQUIRED
    )

    quarantined = pilot is not None and pilot.status == "quarantined"
    quarantined_reasons = ("pilot.status:quarantined",) if quarantined else ()
    if quarantine_packet is not None:
        quarantined_reasons += ("quarantine.packet-present",)

    termination_uncertain = pilot is not None and not pilot.termination_confirmed and (
        pilot.executor_started
        or bool(set(pilot.reason_codes) & _TERMINATION_UNCERTAIN_REASON_CODES)
    )
    termination_reasons = (
        tuple(f"termination.{code}" for code in set(pilot.reason_codes) & _TERMINATION_UNCERTAIN_REASON_CODES)
        if pilot is not None
        else ()
    )

    cleanup_failed = pilot is not None and (
        bool(pilot.cleanup_errors)
        or bool(set(pilot.reason_codes) & _CLEANUP_FAILURE_REASON_CODES)
        or (pilot.workspace_created and not (pilot.workspace_filesystem_cleaned and pilot.workspace_metadata_cleaned))
    )
    cleanup_reasons = ("pilot.cleanup-errors",) if pilot is not None and pilot.cleanup_errors else ()

    release_failed = pilot is not None and (
        bool(pilot.release_errors)
        or bool(set(pilot.reason_codes) & _RELEASE_FAILURE_REASON_CODES)
        or (pilot.lease_acquired and not pilot.lease_released)
    )
    release_reasons = ("pilot.release-errors",) if pilot is not None and pilot.release_errors else ()

    timed_out = pilot is not None and pilot.status == "timed-out"
    cancelled = pilot is not None and pilot.status == "cancelled"

    evidence_incomplete = (
        bool(missing_required)
        or composition is None
        or pilot is None
        or workspace is None
        or not workspace.initial.complete
        or not workspace.final.complete
        or composition.validation_result is None
        or (pilot is not None and pilot.status not in _KNOWN_PILOT_STATUSES)
        or (pilot is not None and pilot.status in ("blocked", "stale", "needs-decision"))
    )
    evidence_incomplete_reasons = tuple(f"evidence.missing:{name}" for name in missing_required)

    validation_failed = (
        composition is not None
        and composition.validation_result is not None
        and composition.validation_result.attempted
        and not composition.validation_result.passed
    )

    succeeded = (
        composition is not None
        and pilot is not None
        and workspace is not None
        and quarantine_packet is None
        and not missing_required
        and composition.execution_authorized is True
        and pilot.status == "completed"
        and not pilot.cancellation_requested
        and not pilot.possible_partial_effects
        and pilot.lease_acquired
        and pilot.lease_released
        and pilot.workspace_created
        and pilot.workspace_inspected
        and pilot.workspace_safe
        and pilot.workspace_filesystem_cleaned
        and pilot.workspace_metadata_cleaned
        and not pilot.cleanup_errors
        and not pilot.release_errors
        and pilot.validation_attempted
        and pilot.validation_passed
        and not pilot.reason_codes
        and composition.validation_result is not None
        and composition.validation_result.attempted
        and bool(composition.validation_result.passed)
        and workspace.validation_only_success
        and workspace.satisfies_expected_changed_paths(
            frozenset(bundle.admission_request.lifecycle_policy.expected_changed_paths)
        )
    )

    return {
        ValidationLifecycleTerminalStatus.QUARANTINED: (quarantined, quarantined_reasons),
        ValidationLifecycleTerminalStatus.TERMINATION_UNCERTAIN: (termination_uncertain, termination_reasons),
        ValidationLifecycleTerminalStatus.CLEANUP_FAILED: (cleanup_failed, cleanup_reasons),
        ValidationLifecycleTerminalStatus.RELEASE_FAILED: (release_failed, release_reasons),
        ValidationLifecycleTerminalStatus.TIMED_OUT: (timed_out, ("pilot.status:timed-out",) if timed_out else ()),
        ValidationLifecycleTerminalStatus.CANCELLED: (cancelled, ("pilot.status:cancelled",) if cancelled else ()),
        ValidationLifecycleTerminalStatus.EVIDENCE_INCOMPLETE: (evidence_incomplete, evidence_incomplete_reasons),
        ValidationLifecycleTerminalStatus.VALIDATION_FAILED: (
            validation_failed,
            ("validation.not-passed",) if validation_failed else (),
        ),
        ValidationLifecycleTerminalStatus.SUCCEEDED: (succeeded, ("lifecycle.proven-complete",) if succeeded else ()),
    }


def project_validation_lifecycle_result(
    bundle: ValidationLifecycleEvidenceBundle, *, evaluated_at: str | None = None
) -> ValidationLifecycleResult:
    """The one pure projection function. No other function decides status."""
    if type(bundle) is not ValidationLifecycleEvidenceBundle:
        raise TypeError("bundle must be exact ValidationLifecycleEvidenceBundle")

    resolved_evaluated_at = evaluated_at if evaluated_at is not None else bundle.evaluated_at
    parse_canonical_utc(resolved_evaluated_at)

    admission_status = bundle.admission_result.status
    if admission_status is AuthorizedValidationAdmissionStatus.BLOCKED:
        status = ValidationLifecycleTerminalStatus.BLOCKED
        reasons = _admission_reasons(bundle)
    elif admission_status is AuthorizedValidationAdmissionStatus.STALE:
        status = ValidationLifecycleTerminalStatus.STALE
        reasons = _admission_reasons(bundle)
    elif admission_status is AuthorizedValidationAdmissionStatus.NEEDS_DECISION:
        # A pending human decision is, from #761's terminal vocabulary, a
        # not-yet-authorized pre-execution stop -- the same posture as
        # BLOCKED, never a runtime status.
        status = ValidationLifecycleTerminalStatus.BLOCKED
        reasons = _admission_reasons(bundle) + ("admission.needs-decision",)
    elif admission_status is AuthorizedValidationAdmissionStatus.INVALID:
        # An admission input that fails its own identity/content
        # verification is an evidence-integrity failure, not a legitimate
        # pre-execution admission classification.
        status = ValidationLifecycleTerminalStatus.EVIDENCE_INCOMPLETE
        reasons = _admission_reasons(bundle) + ("admission.invalid",)
    else:
        predicates = _post_admission_predicates(bundle)
        status = ValidationLifecycleTerminalStatus.EVIDENCE_INCOMPLETE
        reasons: tuple[str, ...] = ("lifecycle.precedence-fallback",)
        for candidate in POST_ADMISSION_TERMINAL_STATUS_PRECEDENCE:
            matched, candidate_reasons = predicates[candidate]
            if matched:
                status = candidate
                reasons = _admission_reasons(bundle) + candidate_reasons
                break

    reason_codes = tuple(sorted(set(reasons))) if reasons else ("lifecycle.no-reason-recorded",)

    return ValidationLifecycleResult(
        schema_version=VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        bundle_id=bundle.bundle_id,
        request_id=bundle.admission_request.request_id,
        status=status,
        reason_codes=reason_codes,
        execution_authorized=bool(
            bundle.execution_composition.execution_authorized if bundle.execution_composition is not None else False
        ),
        side_effects_performed=bundle.side_effects_performed,
        evaluated_at=resolved_evaluated_at,
    )


# ---------------------------------------------------------------------------
# Serialization / reconstruction
# ---------------------------------------------------------------------------

_ADMISSION_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "request_id",
        "evaluated_at",
        "status",
        "reason_codes",
        "accepted",
        "execution_authorized",
        "merge_authorized",
        "automatic_retry",
        "side_effects_performed",
    }
)


def _serialize_admission_result(value: AuthorizedValidationAdmissionResult) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "request_id": value.request_id,
        "evaluated_at": value.evaluated_at,
        "status": value.status.value,
        "reason_codes": list(value.reason_codes),
        "accepted": value.accepted,
        "execution_authorized": False,
        "merge_authorized": False,
        "automatic_retry": False,
        "side_effects_performed": False,
    }


def _reconstruct_admission_result(payload: object) -> AuthorizedValidationAdmissionResult:
    if type(payload) is not dict or set(payload) != _ADMISSION_RESULT_KEYS:
        raise ValidationLifecycleEvidenceError("admission_result payload has unknown or missing fields")
    return AuthorizedValidationAdmissionResult(
        schema_version=payload["schema_version"],
        request_id=payload["request_id"],
        evaluated_at=payload["evaluated_at"],
        status=AuthorizedValidationAdmissionStatus(payload["status"]),
        reason_codes=tuple(payload["reason_codes"]),
        accepted=payload["accepted"],
    )


def _serialize_command_run_observation(value: object) -> dict[str, object]:
    return {
        "test_id": value.test_id,
        "outcome": value.outcome,
        "started": value.started,
        "return_code": value.return_code,
        "stdout_text": value.stdout_text,
        "stderr_text": value.stderr_text,
        "changed_paths": list(value.changed_paths),
        "reason": value.reason,
    }


def _reconstruct_command_run_observation(payload: dict[str, object]) -> object:
    CommandRunObservation = _command_run_observation_type()
    return CommandRunObservation(
        test_id=payload["test_id"],
        outcome=payload["outcome"],
        started=payload["started"],
        return_code=payload["return_code"],
        stdout_text=payload["stdout_text"],
        stderr_text=payload["stderr_text"],
        changed_paths=tuple(payload["changed_paths"]),
        reason=payload["reason"],
    )


def _serialize_validation_result(value: object) -> dict[str, object]:
    return {
        "attempted": value.attempted,
        "passed": value.passed,
        "cancellation_requested": value.cancellation_requested,
        "total_timed_out": value.total_timed_out,
        "completed_tests": list(value.completed_tests),
        "changed_paths": list(value.changed_paths),
        "command_outcomes": [_serialize_command_run_observation(item) for item in value.command_outcomes],
        "reason": value.reason,
    }


def _reconstruct_validation_result(payload: dict[str, object]) -> object:
    FrozenTestValidationResult = _frozen_test_validation_result_type()
    return FrozenTestValidationResult(
        attempted=payload["attempted"],
        passed=payload["passed"],
        cancellation_requested=payload["cancellation_requested"],
        total_timed_out=payload["total_timed_out"],
        completed_tests=tuple(payload["completed_tests"]),
        changed_paths=tuple(payload["changed_paths"]),
        command_outcomes=tuple(
            _reconstruct_command_run_observation(item) for item in payload["command_outcomes"]
        ),
        reason=payload["reason"],
    )


def _serialize_execution_composition(value: ExecutionCompositionResult) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "request_fingerprint": value.request_fingerprint,
        "command_plan_id": value.command_plan_id,
        "repository": value.repository,
        "expected_sha": value.expected_sha,
        "profile": value.profile,
        "status": value.status.value,
        "validation_result": (
            _serialize_validation_result(value.validation_result) if value.validation_result is not None else None
        ),
        "aggregate_pending": value.aggregate_pending,
        "execution_authorized": value.execution_authorized,
        "merge_authorized": False,
        "side_effects_performed": value.side_effects_performed,
        "reason_codes": list(value.reason_codes),
        "evidence_id": value.evidence_id,
    }


def _reconstruct_execution_composition(payload: dict[str, object]) -> ExecutionCompositionResult:
    validation_result = (
        _reconstruct_validation_result(payload["validation_result"])
        if payload["validation_result"] is not None
        else None
    )
    return ExecutionCompositionResult(
        request_fingerprint=payload["request_fingerprint"],
        command_plan_id=payload["command_plan_id"],
        repository=payload["repository"],
        expected_sha=payload["expected_sha"],
        profile=payload["profile"],
        status=ExecutionCompositionStatus(payload["status"]),
        validation_result=validation_result,
        aggregate_pending=payload["aggregate_pending"],
        execution_authorized=payload["execution_authorized"],
        side_effects_performed=payload["side_effects_performed"],
        reason_codes=tuple(payload["reason_codes"]),
        evidence_id=payload["evidence_id"],
    )


_PILOT_RESULT_INIT_FALSE_FIELDS = frozenset(
    {
        "authoritative",
        "implementation_authorized",
        "execution_authorized",
        "publication_authorized",
        "merge_authorized",
        "attestation_verified",
        "side_effects_authorized",
        "retry_attempted",
    }
)


def _reconstruct_pilot_result(payload: dict[str, object]) -> object:
    PilotResultType = _pilot_result_type()
    kwargs = {key: value for key, value in payload.items() if key not in _PILOT_RESULT_INIT_FALSE_FIELDS}
    for tuple_field in (
        "issue_numbers",
        "changed_paths",
        "required_tests",
        "completed_tests",
        "reason_codes",
        "details",
        "cleanup_errors",
        "release_errors",
    ):
        kwargs[tuple_field] = tuple(kwargs[tuple_field])
    return PilotResultType(**kwargs)


def _serialize_changed_path_observation(value: object) -> dict[str, object]:
    return value.as_dict()


def _reconstruct_changed_path_observation(payload: dict[str, object]) -> object:
    ChangedPathObservation = _changed_path_observation_type()
    return ChangedPathObservation(
        category=payload["category"],
        path=payload["path"],
        orig_path=payload["orig_path"],
        index_status=payload["index_status"],
        worktree_status=payload["worktree_status"],
        submodule_state=payload["submodule_state"],
        rename_score=payload["rename_score"],
    )


def _reconstruct_workspace_state_observation(payload: dict[str, object]) -> object:
    WorkspaceStateObservation = _workspace_state_observation_type()
    WorktreeListRecord = _worktree_list_record_type()
    worktree_record = None
    if payload["worktree_record"] is not None:
        worktree_record = WorktreeListRecord(**payload["worktree_record"])
    category_fields = (
        "staged",
        "unstaged",
        "untracked",
        "ignored",
        "renamed",
        "copied",
        "deleted",
        "conflict",
        "submodule",
    )
    categories = {
        name: tuple(_reconstruct_changed_path_observation(item) for item in payload[name])
        for name in category_fields
    }
    return WorkspaceStateObservation(
        observation_kind=payload["observation_kind"],
        repository_owner=payload["repository_owner"],
        repository_name=payload["repository_name"],
        workspace_path=payload["workspace_path"],
        branch=payload["branch"],
        expected_sha=payload["expected_sha"],
        observed_sha=payload["observed_sha"],
        lock_identity=payload["lock_identity"],
        worktree_record=worktree_record,
        inspector_identity=payload["inspector_identity"],
        inspector_version=payload["inspector_version"],
        observed_at=payload["observed_at"],
        complete=payload["complete"],
        reason_codes=tuple(payload["reason_codes"]),
        **categories,
    )


def _serialize_workspace_lifecycle_evidence(value: object) -> dict[str, object]:
    return {
        "initial": value.initial.as_dict(),
        "final": value.final.as_dict(),
        "validation_only": value.validation_only,
        "lifecycle_id": value.lifecycle_id,
    }


def _reconstruct_workspace_lifecycle_evidence(payload: dict[str, object]) -> object:
    WorkspaceLifecycleEvidenceType = _workspace_lifecycle_evidence_type()
    initial = _reconstruct_workspace_state_observation(payload["initial"])
    final = _reconstruct_workspace_state_observation(payload["final"])
    reconstructed = WorkspaceLifecycleEvidenceType(
        initial=initial, final=final, validation_only=payload["validation_only"]
    )
    if reconstructed.lifecycle_id != payload["lifecycle_id"]:
        raise ValidationLifecycleEvidenceError("workspace_lifecycle_evidence.lifecycle_id mismatch on reconstruction")
    return reconstructed


def _reconstruct_quarantine_packet(payload: dict[str, object]) -> object:
    QuarantinePacketType = _quarantine_packet_type()
    kwargs = dict(payload)
    kwargs["issue_numbers"] = tuple(kwargs["issue_numbers"])
    for tuple_field in ("changed_paths", "reason_codes", "details", "cleanup_errors", "release_errors"):
        kwargs[tuple_field] = tuple(kwargs[tuple_field])
    return QuarantinePacketType(**kwargs)


_BUNDLE_KEYS = frozenset(
    {
        "schema_version",
        "bundle_id",
        "evaluated_at",
        "admission_request",
        "admission_result",
        "execution_composition",
        "pilot_result",
        "workspace_lifecycle_evidence",
        "quarantine_packet",
        "evidence_availability",
        "side_effects_performed",
    }
)


def serialize_validation_lifecycle_evidence_bundle(
    bundle: ValidationLifecycleEvidenceBundle,
) -> dict[str, object]:
    """Return canonical, bounded, JSON-compatible evidence for one bundle."""
    if type(bundle) is not ValidationLifecycleEvidenceBundle:
        raise TypeError("bundle must be exact ValidationLifecycleEvidenceBundle")

    from .authorized_validation import serialize_authorized_validation_lifecycle_request

    payload: dict[str, object] = {
        "schema_version": bundle.schema_version,
        "bundle_id": bundle.bundle_id,
        "evaluated_at": bundle.evaluated_at,
        "admission_request": serialize_authorized_validation_lifecycle_request(bundle.admission_request),
        "admission_result": _serialize_admission_result(bundle.admission_result),
        "execution_composition": (
            _serialize_execution_composition(bundle.execution_composition)
            if bundle.execution_composition is not None
            else None
        ),
        "pilot_result": (
            _pilot_result_serializer()(bundle.pilot_result) if bundle.pilot_result is not None else None
        ),
        "workspace_lifecycle_evidence": (
            _serialize_workspace_lifecycle_evidence(bundle.workspace_lifecycle_evidence)
            if bundle.workspace_lifecycle_evidence is not None
            else None
        ),
        "quarantine_packet": (
            _quarantine_packet_serializer()(bundle.quarantine_packet)
            if bundle.quarantine_packet is not None
            else None
        ),
        "evidence_availability": [item.as_dict() for item in bundle.evidence_availability],
        "side_effects_performed": bundle.side_effects_performed,
    }
    encoded = _canonical_bytes(payload)
    if len(encoded) > MAX_BUNDLE_SERIALIZED_BYTES:
        raise ValidationLifecycleEvidenceError("validation-lifecycle-evidence bundle exceeds the serialized size bound")
    return payload


def reconstruct_validation_lifecycle_evidence_bundle(
    payload: object,
) -> ValidationLifecycleEvidenceBundle:
    """Reconstruct, re-verify, and recompute identity for one canonical bundle payload."""
    if type(payload) is not dict or set(payload) != _BUNDLE_KEYS:
        raise ValidationLifecycleEvidenceError("bundle payload has unknown or missing fields")

    from .authorized_validation import reconstruct_authorized_validation_lifecycle_request

    admission_request = reconstruct_authorized_validation_lifecycle_request(payload["admission_request"])
    admission_result = _reconstruct_admission_result(payload["admission_result"])
    execution_composition = (
        _reconstruct_execution_composition(payload["execution_composition"])
        if payload["execution_composition"] is not None
        else None
    )
    pilot_result = (
        _reconstruct_pilot_result(payload["pilot_result"]) if payload["pilot_result"] is not None else None
    )
    workspace_lifecycle_evidence = (
        _reconstruct_workspace_lifecycle_evidence(payload["workspace_lifecycle_evidence"])
        if payload["workspace_lifecycle_evidence"] is not None
        else None
    )
    quarantine_packet = (
        _reconstruct_quarantine_packet(payload["quarantine_packet"])
        if payload["quarantine_packet"] is not None
        else None
    )

    rebuilt = build_validation_lifecycle_evidence_bundle(
        evaluated_at=payload["evaluated_at"],
        admission_request=admission_request,
        admission_result=admission_result,
        execution_composition=execution_composition,
        pilot_result=pilot_result,
        workspace_lifecycle_evidence=workspace_lifecycle_evidence,
        quarantine_packet=quarantine_packet,
    )
    if rebuilt.bundle_id != payload["bundle_id"]:
        raise ValidationLifecycleEvidenceError("bundle_id mismatch on reconstruction (tampered or stale)")
    return rebuilt


_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "bundle_id",
        "request_id",
        "status",
        "reason_codes",
        "execution_authorized",
        "side_effects_performed",
        "evaluated_at",
        "result_id",
    }
)


def serialize_validation_lifecycle_result(result: ValidationLifecycleResult) -> dict[str, object]:
    if type(result) is not ValidationLifecycleResult:
        raise TypeError("result must be exact ValidationLifecycleResult")
    return {
        "schema_version": result.schema_version,
        "bundle_id": result.bundle_id,
        "request_id": result.request_id,
        "status": result.status.value,
        "reason_codes": list(result.reason_codes),
        "execution_authorized": result.execution_authorized,
        "side_effects_performed": result.side_effects_performed,
        "evaluated_at": result.evaluated_at,
        "result_id": result.result_id,
    }


def reconstruct_validation_lifecycle_result(payload: object) -> ValidationLifecycleResult:
    if type(payload) is not dict or set(payload) != _RESULT_KEYS:
        raise ValidationLifecycleEvidenceError("result payload has unknown or missing fields")
    rebuilt = ValidationLifecycleResult(
        schema_version=payload["schema_version"],
        bundle_id=payload["bundle_id"],
        request_id=payload["request_id"],
        status=ValidationLifecycleTerminalStatus(payload["status"]),
        reason_codes=tuple(payload["reason_codes"]),
        execution_authorized=payload["execution_authorized"],
        side_effects_performed=payload["side_effects_performed"],
        evaluated_at=payload["evaluated_at"],
    )
    if rebuilt.result_id != payload["result_id"]:
        raise ValidationLifecycleEvidenceError("result_id mismatch on reconstruction (tampered or stale)")
    return rebuilt
