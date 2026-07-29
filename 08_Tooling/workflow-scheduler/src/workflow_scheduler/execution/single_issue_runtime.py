"""WSC5B1 pure bounded single-issue runtime entrypoint.

This is the deterministic integration layer only. It accepts one already
fully-supplied ``SingleIssuePilotInput`` (the approved execution packet) plus
the five orchestrator-defined adapters, verifies the adapters satisfy their
protocols, calls ``run_single_issue_pilot(...)`` exactly once, and returns the
canonical result together with a bounded, immutable local runtime observation
packet. When the result status is ``quarantined`` it constructs local
quarantine evidence through the existing, unmodified WSC5R public contract.

In validation-only mode the executor adapter is absent by contract rather than
substituted, so the observation records no executor adapter at all.

This module performs no I/O. It defines no subprocess, Git worktree, lease
backend, retry, queue, persistence, GitHub, workflow, or network
implementation, and it does not import the legacy Scheduler executor, request
dispatch, or RetryManager. All approval/projection/IssuePlan/validation-plan/
bundle/advisory/repository/SHA/path/test evidence is reverified exactly once,
inside the unmodified orchestrator, by the canonical public APIs it already
calls -- this module defines no competing validation and does not duplicate
that logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from workflow_scheduler.execution.quarantine_review import (
    QuarantineEvidencePacket,
    build_quarantine_evidence_packet,
)
from workflow_scheduler.execution.single_issue_pilot import (
    RUNTIME_EXECUTION_MODES,
    VALIDATION_ONLY_EXECUTION_MODE,
    CancellationProbe,
    LeaseAdapter,
    PilotExecutor,
    SingleIssuePilotInput,
    SingleIssuePilotResult,
    ValidationAdapter,
    WorkspaceAdapter,
    run_single_issue_pilot,
)

RUNTIME_ENTRYPOINT_SCHEMA_NAME = "agent-os-wsc5b1-runtime-entrypoint"
RUNTIME_ENTRYPOINT_SCHEMA_VERSION = "1.0"

MAX_FIELD_LENGTH = 4096
MAX_OBSERVATION_SERIALIZED_BYTES = 65_536


class RuntimeEntrypointError(TypeError):
    """Raised when the entrypoint receives malformed input or adapters.

    Raised before ``run_single_issue_pilot`` -- and therefore before any
    adapter method -- is ever invoked.
    """


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _semantic_digest(domain: str, payload: object) -> str:
    return hashlib.sha256(
        f"{domain}:v1".encode("utf-8") + b"\0" + _canonical_bytes(payload)
    ).hexdigest()


def _bounded_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeEntrypointError(f"{name} must be a non-empty string")
    if len(value) > MAX_FIELD_LENGTH:
        raise RuntimeEntrypointError(f"{name} exceeds the bounded length")
    return value


# --------------------------------------------------------------------------
# Bounded, immutable, tamper-evident runtime observation
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeObservation:
    """Bounded, immutable local record of exactly one entrypoint invocation."""

    schema_name: str
    schema_version: str
    observation_id: str
    repository: str
    issue_numbers: tuple[int, ...]
    invocation_id: str
    execution_mode: str
    lease_adapter_type: str
    workspace_adapter_type: str
    # ``None`` records that no executor adapter existed for this invocation.
    # Validation-only mode never names an executor it did not have.
    executor_adapter_type: str | None
    validator_adapter_type: str
    cancellation_probe_type: str
    orchestrator_invocation_count: int
    pilot_result_id: str
    pilot_status: str
    quarantine_evidence_built: bool
    quarantine_packet_id: str | None

    def __post_init__(self) -> None:
        if self.schema_name != RUNTIME_ENTRYPOINT_SCHEMA_NAME:
            raise RuntimeEntrypointError("unsupported runtime entrypoint schema name")
        if self.schema_version != RUNTIME_ENTRYPOINT_SCHEMA_VERSION:
            raise RuntimeEntrypointError("unsupported runtime entrypoint schema version")
        if self.orchestrator_invocation_count != 1:
            raise RuntimeEntrypointError(
                "the orchestrator must be invoked exactly once per observation"
            )
        if self.execution_mode not in RUNTIME_EXECUTION_MODES:
            raise RuntimeEntrypointError("unsupported runtime execution mode")
        object.__setattr__(self, "issue_numbers", tuple(self.issue_numbers))
        _bounded_text(self.repository, "repository")
        _bounded_text(self.invocation_id, "invocation_id")
        _bounded_text(self.lease_adapter_type, "lease_adapter_type")
        _bounded_text(self.workspace_adapter_type, "workspace_adapter_type")
        if self.executor_adapter_type is not None:
            _bounded_text(self.executor_adapter_type, "executor_adapter_type")
        elif self.execution_mode != VALIDATION_ONLY_EXECUTION_MODE:
            raise RuntimeEntrypointError(
                "only validation-only mode may record an absent executor adapter"
            )
        _bounded_text(self.validator_adapter_type, "validator_adapter_type")
        _bounded_text(self.cancellation_probe_type, "cancellation_probe_type")
        _bounded_text(self.pilot_result_id, "pilot_result_id")
        _bounded_text(self.pilot_status, "pilot_status")
        if self.quarantine_packet_id is not None:
            _bounded_text(self.quarantine_packet_id, "quarantine_packet_id")


def _observation_payload(observation: RuntimeObservation) -> dict[str, object]:
    return {
        "schema_name": observation.schema_name,
        "schema_version": observation.schema_version,
        "repository": observation.repository,
        "issue_numbers": list(observation.issue_numbers),
        "invocation_id": observation.invocation_id,
        "execution_mode": observation.execution_mode,
        "lease_adapter_type": observation.lease_adapter_type,
        "workspace_adapter_type": observation.workspace_adapter_type,
        "executor_adapter_type": observation.executor_adapter_type,
        "validator_adapter_type": observation.validator_adapter_type,
        "cancellation_probe_type": observation.cancellation_probe_type,
        "orchestrator_invocation_count": observation.orchestrator_invocation_count,
        "pilot_result_id": observation.pilot_result_id,
        "pilot_status": observation.pilot_status,
        "quarantine_evidence_built": observation.quarantine_evidence_built,
        "quarantine_packet_id": observation.quarantine_packet_id,
    }


def runtime_observation_id(observation: RuntimeObservation) -> str:
    """Return the domain-separated identity derived from the full observation."""
    return "runtime-observation:" + _semantic_digest(
        "agent-os-wsc5b1-runtime-observation", _observation_payload(observation)
    )


def serialize_runtime_observation(observation: RuntimeObservation) -> dict[str, object]:
    """Return verified, JSON-compatible, tamper-checked observation evidence."""
    if not isinstance(observation, RuntimeObservation):
        raise RuntimeEntrypointError("observation must be RuntimeObservation")
    expected = runtime_observation_id(observation)
    if observation.observation_id != expected:
        raise RuntimeEntrypointError(
            "runtime observation identity mismatch (tampered or stale)"
        )
    serialized = _observation_payload(observation)
    serialized["observation_id"] = observation.observation_id
    if len(_canonical_bytes(serialized)) > MAX_OBSERVATION_SERIALIZED_BYTES:
        raise RuntimeEntrypointError("runtime observation exceeds the canonical size limit")
    return serialized


# --------------------------------------------------------------------------
# Outcome
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SingleIssueRuntimeOutcome:
    """The canonical pilot result plus bounded local runtime evidence."""

    result: SingleIssuePilotResult
    observation: RuntimeObservation
    quarantine_evidence: QuarantineEvidencePacket | None


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------


def _require_adapter(adapter: object, protocol: type, name: str) -> str:
    if not isinstance(adapter, protocol):
        raise RuntimeEntrypointError(f"{name} does not satisfy its required protocol")
    return type(adapter).__name__


def run_single_issue_runtime_entrypoint(
    pilot_input: SingleIssuePilotInput,
    *,
    lease: LeaseAdapter,
    workspace: WorkspaceAdapter,
    executor: PilotExecutor | None = None,
    validator: ValidationAdapter,
    cancelled: CancellationProbe,
) -> SingleIssueRuntimeOutcome:
    """Validate wiring, run the orchestrator exactly once, and return evidence.

    Every approval/projection/IssuePlan/validation-plan/bundle/advisory/
    repository/SHA/path/test check is performed exactly once, inside the
    unmodified ``run_single_issue_pilot`` orchestrator, through its existing
    canonical public APIs. This function fails closed on malformed input or
    non-conforming adapters before the orchestrator -- and therefore before
    any adapter method -- is ever called, and never invokes the orchestrator
    more than once.

    An absent executor is accepted only when the supplied mode is exactly
    validation-only. Standard mode still requires a protocol-conforming
    executor, and validation-only mode refuses one: an unsupported, malformed,
    or drifted mode fails closed here, before any adapter runs.
    """
    if not isinstance(pilot_input, SingleIssuePilotInput):
        raise RuntimeEntrypointError("pilot_input must be SingleIssuePilotInput")

    mode = pilot_input.execution_mode
    if mode not in RUNTIME_EXECUTION_MODES:
        raise RuntimeEntrypointError("unsupported runtime execution mode")

    lease_type = _require_adapter(lease, LeaseAdapter, "lease")
    workspace_type = _require_adapter(workspace, WorkspaceAdapter, "workspace")
    executor_type: str | None
    if mode == VALIDATION_ONLY_EXECUTION_MODE:
        if executor is not None:
            raise RuntimeEntrypointError(
                "validation-only mode must not be supplied an executor"
            )
        executor_type = None
    else:
        executor_type = _require_adapter(executor, PilotExecutor, "executor")
    validator_type = _require_adapter(validator, ValidationAdapter, "validator")
    if not callable(cancelled):
        raise RuntimeEntrypointError("cancelled must satisfy the CancellationProbe protocol")
    cancellation_type = type(cancelled).__name__

    result = run_single_issue_pilot(
        pilot_input,
        lease=lease,
        workspace=workspace,
        executor=executor,
        validator=validator,
        cancelled=cancelled,
    )

    quarantine_evidence: QuarantineEvidencePacket | None = None
    if result.status == "quarantined":
        quarantine_evidence = build_quarantine_evidence_packet(result)

    payload = {
        "schema_name": RUNTIME_ENTRYPOINT_SCHEMA_NAME,
        "schema_version": RUNTIME_ENTRYPOINT_SCHEMA_VERSION,
        "repository": pilot_input.repository,
        "issue_numbers": list(pilot_input.issue_numbers),
        "invocation_id": pilot_input.invocation_id,
        "execution_mode": mode,
        "lease_adapter_type": lease_type,
        "workspace_adapter_type": workspace_type,
        "executor_adapter_type": executor_type,
        "validator_adapter_type": validator_type,
        "cancellation_probe_type": cancellation_type,
        "orchestrator_invocation_count": 1,
        "pilot_result_id": result.result_id,
        "pilot_status": result.status,
        "quarantine_evidence_built": quarantine_evidence is not None,
        "quarantine_packet_id": (
            quarantine_evidence.packet_id if quarantine_evidence is not None else None
        ),
    }
    observation_id = "runtime-observation:" + _semantic_digest(
        "agent-os-wsc5b1-runtime-observation", payload
    )
    observation = RuntimeObservation(observation_id=observation_id, **payload)
    # Enforce the aggregate canonical size/identity bound here so an
    # oversized or tampered observation can never leave the entrypoint; the
    # original RuntimeObservation object (not the serialized dict) is still
    # what gets returned.
    serialize_runtime_observation(observation)

    return SingleIssueRuntimeOutcome(
        result=result, observation=observation, quarantine_evidence=quarantine_evidence
    )
