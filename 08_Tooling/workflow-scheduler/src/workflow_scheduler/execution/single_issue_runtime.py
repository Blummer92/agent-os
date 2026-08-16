"""WSC5B1 pure bounded single-issue runtime entrypoint.

This is the deterministic integration layer only. It accepts one already
fully-supplied ``SingleIssuePilotInput`` (the approved execution packet) plus
the orchestrator-defined adapters, verifies the adapters satisfy their
protocols, calls ``run_single_issue_pilot(...)`` exactly once, and returns the
canonical result together with a bounded, immutable local runtime observation
packet. When the result status is ``quarantined`` it constructs local
quarantine evidence through the existing, unmodified WSC5R public contract.

AOS-RUNNER1D adds one optional dependency-preparation adapter. When supplied,
a thin runtime gate delegates workspace inspection first, admits dependency
preparation only after that observation proves the same safe workspace facts
the pilot will reverify, and refuses provider/validation delegation until
current READY dependency evidence exists. If provider output changes a bound
dependency manifest, lock/constraints input, or declared local-project source,
the validator gate performs one changed-input recheck before validation. That
second check is not a retry of a failed preparation.

In validation-only mode the executor adapter is absent by contract rather than
substituted, so the observation records no executor adapter at all.

This module performs no subprocess, Git, package-manager, lease-backend,
network, queue, persistence, GitHub, or workflow I/O. Executable preparation
remains behind the injected dependency adapter. All approval/projection/
IssuePlan/validation-plan/bundle/advisory/repository/SHA/path/test evidence is
reverified by the canonical pilot public APIs rather than duplicated here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
)
from workflow_scheduler.execution.dependency_preparation import (
    POST_PREPARATION_DRIFT,
    DependencyPreparationAdapter,
)
from workflow_scheduler.execution.quarantine_review import (
    QuarantineEvidencePacket,
    build_quarantine_evidence_packet,
)
from workflow_scheduler.execution.single_issue_pilot import (
    RUNTIME_EXECUTION_MODES,
    VALIDATION_ONLY_EXECUTION_MODE,
    CancellationProbe,
    LeaseAdapter,
    PilotExecutionObservation,
    PilotExecutionRequest,
    PilotExecutor,
    PilotValidationObservation,
    PilotValidationRequest,
    SingleIssuePilotInput,
    SingleIssuePilotResult,
    ValidationAdapter,
    WorkspaceAdapter,
    WorkspaceHandle,
    WorkspaceInspection,
    WorkspaceRequest,
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
# Dependency readiness runtime gate
# --------------------------------------------------------------------------


class _DependencyRuntimeGate:
    def __init__(
        self,
        adapter: DependencyPreparationAdapter,
        pilot_input: SingleIssuePilotInput,
    ) -> None:
        self._adapter = adapter
        self._pilot_input = pilot_input
        self.evidence: list[DependencyReadinessEvidence] = []
        self.ready = False
        self.recheck_required = False
        self.post_preparation_observations: list[object] = []
        self._post_preparation_reason: str | None = None
        self._workspace: object | None = None
        self._handle: WorkspaceHandle | None = None

    def bind_workspace(self, workspace: object, handle: WorkspaceHandle) -> None:
        """Remember the inspected workspace so a later recheck reuses the same seam."""
        self._workspace = workspace
        self._handle = handle

    def ensure_ready_with_workspace_integrity(self, workspace_identity: str) -> bool:
        """Prepare, then prove the post-preparation workspace state before continuing."""
        if not self.ensure_ready(workspace_identity):
            return False
        if self._workspace is None or self._handle is None:
            self.ready = False
            self._post_preparation_reason = "complete-state-inspection-unavailable"
            return False
        return self.confirm_post_preparation_workspace(self._workspace, self._handle)

    def confirm_post_preparation_workspace(
        self, workspace: object, handle: WorkspaceHandle
    ) -> bool:
        """Reuse the existing complete workspace-state inspection after preparation.

        Successful preparation may run package-manager and build-backend code, so
        the pre-preparation observation is no longer sufficient evidence. This
        reuses the #760 complete inspection the bound workspace adapter already
        owns; it creates no second workspace-integrity mechanism. Missing or
        unresolved complete-state evidence fails closed.
        """
        inspector = getattr(workspace, "inspect_complete_state", None)
        if not callable(inspector):
            self.ready = False
            self._post_preparation_reason = "complete-state-inspection-unavailable"
            return False
        observation = inspector(handle, observation_kind="initial")
        self.post_preparation_observations.append(observation)
        complete = getattr(observation, "complete", False)
        is_clean = getattr(observation, "is_clean", False)
        observed_sha = getattr(observation, "observed_sha", None)
        if (
            complete is not True
            or is_clean is not True
            or observed_sha != self._pilot_input.source_head_sha
        ):
            self.ready = False
            self._post_preparation_reason = POST_PREPARATION_DRIFT
            return False
        self._post_preparation_reason = None
        return True

    def ensure_ready(self, workspace_identity: str) -> bool:
        self._post_preparation_reason = None
        evidence = self._adapter.prepare(workspace_identity=workspace_identity)
        if type(evidence) is not DependencyReadinessEvidence:
            raise RuntimeError(
                "dependency preparer must return exact DependencyReadinessEvidence"
            )
        self.evidence.append(evidence)
        if evidence.workspace_identity != workspace_identity:
            raise RuntimeError("dependency readiness workspace identity drifted")
        if evidence.source_sha != self._pilot_input.source_head_sha:
            raise RuntimeError("dependency readiness source SHA drifted")
        if not evidence.is_current(self._pilot_input.evaluated_at):
            self.ready = False
            self.recheck_required = False
            return False
        self.ready = evidence.preparation_status is DependencyPreparationStatus.READY
        self.recheck_required = False
        return self.ready

    def note_executor_changes(self, changed_paths: tuple[str, ...]) -> None:
        if self._adapter.requires_recheck(tuple(changed_paths)):
            self.ready = False
            self.recheck_required = True

    @property
    def blocker_summary(self) -> str:
        if self._post_preparation_reason is not None:
            return f"dependency-readiness:{self._post_preparation_reason}"
        if not self.evidence:
            return "dependency-readiness:no-evidence"
        latest = self.evidence[-1]
        reasons = ",".join(latest.reason_codes) or latest.preparation_status.value
        return f"dependency-readiness:{reasons}"


class _DependencyReadyWorkspaceAdapter:
    def __init__(
        self,
        adapter: WorkspaceAdapter,
        gate: _DependencyRuntimeGate,
        pilot_input: SingleIssuePilotInput,
    ) -> None:
        self._adapter = adapter
        self._gate = gate
        self._pilot_input = pilot_input

    def create(self, request: WorkspaceRequest):
        return self._adapter.create(request)

    def inspect(self, handle: WorkspaceHandle):
        inspection = self._adapter.inspect(handle)
        if not _workspace_observation_is_safe(inspection, self._pilot_input):
            return inspection
        self._gate.bind_workspace(self._adapter, handle)
        if self._gate.ensure_ready_with_workspace_integrity(handle.workspace_identity):
            return inspection
        return replace(
            inspection,
            resolved=False,
            reason=self._gate.blocker_summary,
        )

    def inspect_complete_state(self, handle: WorkspaceHandle, *, observation_kind: str):
        return self._adapter.inspect_complete_state(
            handle, observation_kind=observation_kind
        )

    def cleanup(self, handle: WorkspaceHandle):
        return self._adapter.cleanup(handle)


def _workspace_observation_is_safe(
    inspection: object,
    pilot_input: SingleIssuePilotInput,
) -> bool:
    if type(inspection) is not WorkspaceInspection:
        return False
    return (
        inspection.resolved
        and not inspection.missing
        and not inspection.prunable
        and not inspection.reused
        and not inspection.detached
        and inspection.clean
        and (not inspection.locked or inspection.locked_expected)
        and inspection.repository == pilot_input.repository
        and inspection.branch == pilot_input.branch
        and inspection.expected_revision == pilot_input.source_head_sha
        and inspection.actual_revision == pilot_input.source_head_sha
    )


class _DependencyReadyExecutor:
    def __init__(self, adapter: PilotExecutor, gate: _DependencyRuntimeGate) -> None:
        self._adapter = adapter
        self._gate = gate

    def run(self, request: PilotExecutionRequest) -> PilotExecutionObservation:
        if not self._gate.ready:
            raise RuntimeError("executor dispatch refused without READY dependency evidence")
        observation = self._adapter.run(request)
        if type(observation) is PilotExecutionObservation:
            self._gate.note_executor_changes(tuple(observation.changed_paths))
        return observation


class _DependencyReadyValidator:
    def __init__(self, adapter: ValidationAdapter, gate: _DependencyRuntimeGate) -> None:
        self._adapter = adapter
        self._gate = gate

    def validate(self, request: PilotValidationRequest) -> PilotValidationObservation:
        if self._gate.recheck_required:
            if not self._gate.ensure_ready_with_workspace_integrity(
                request.workspace_identity
            ):
                return PilotValidationObservation(
                    attempted=False,
                    passed=False,
                    started=False,
                    # No validation command was ever dispatched, so there is
                    # nothing whose termination could be in question --
                    # vacuously terminal, matching every never-started
                    # command in the frozen-test aggregation.
                    termination_confirmed=True,
                    possible_partial_effects=False,
                    reason=self._gate.blocker_summary,
                )
        if not self._gate.ready:
            return PilotValidationObservation(
                attempted=False,
                passed=False,
                started=False,
                termination_confirmed=True,
                possible_partial_effects=False,
                reason=self._gate.blocker_summary,
            )
        return self._adapter.validate(request)


# --------------------------------------------------------------------------
# Outcome
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SingleIssueRuntimeOutcome:
    """The canonical pilot result plus bounded local runtime evidence."""

    result: SingleIssuePilotResult
    observation: RuntimeObservation
    quarantine_evidence: QuarantineEvidencePacket | None
    dependency_readiness_evidence: tuple[DependencyReadinessEvidence, ...] = ()


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
    dependency_preparer: DependencyPreparationAdapter | None = None,
) -> SingleIssueRuntimeOutcome:
    """Validate wiring, run the orchestrator exactly once, and return evidence.

    The optional dependency preparer is a single runtime-owned gate. It is
    invoked only after a safe workspace inspection and before provider or
    validation delegation. A changed dependency input may trigger one new
    readiness check before validation; failed preparation is never retried.
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
    if dependency_preparer is not None and not isinstance(
        dependency_preparer, DependencyPreparationAdapter
    ):
        raise RuntimeEntrypointError(
            "dependency_preparer does not satisfy DependencyPreparationAdapter"
        )

    runtime_workspace: WorkspaceAdapter = workspace
    runtime_executor: PilotExecutor | None = executor
    runtime_validator: ValidationAdapter = validator
    gate: _DependencyRuntimeGate | None = None
    if dependency_preparer is not None:
        gate = _DependencyRuntimeGate(dependency_preparer, pilot_input)
        runtime_workspace = _DependencyReadyWorkspaceAdapter(
            workspace, gate, pilot_input
        )
        if executor is not None:
            runtime_executor = _DependencyReadyExecutor(executor, gate)
        runtime_validator = _DependencyReadyValidator(validator, gate)

    result = run_single_issue_pilot(
        pilot_input,
        lease=lease,
        workspace=runtime_workspace,
        executor=runtime_executor,
        validator=runtime_validator,
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
    serialize_runtime_observation(observation)

    return SingleIssueRuntimeOutcome(
        result=result,
        observation=observation,
        quarantine_evidence=quarantine_evidence,
        dependency_readiness_evidence=(
            () if gate is None else tuple(gate.evidence)
        ),
    )
