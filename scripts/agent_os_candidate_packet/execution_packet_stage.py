"""Non-executing validation/execution packet coordinator for AOS-AUTO1E (#754).

The stage consumes an already-valid candidate-bound pre-PR validation stage and
constructs the canonical execution-service request, fixed-argv validation command
plan, and the canonical #1032 pure Workflow Scheduler runtime configuration.
It imports no executable runtime adapter and performs no command, Git, lease,
worktree, network, provider, or Scheduler lifecycle action.

``GO`` means the packet is structurally complete. It is not execution authority:
all objects produced here remain non-authorizing and execution requires a separate
runtime/operator authorization record outside this issue.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from agent_os_execution_service.command_planning import (
    ValidationCommandPlan,
    build_validation_command_plan,
    reconstruct_validation_command_plan,
    serialize_validation_command_plan,
    validation_command_plan_id,
)
from agent_os_execution_service.models import (
    EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION,
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceRequest,
    reconstruct_execution_service_request,
    serialize_execution_service_request,
)
from workflow_scheduler.execution.runtime_configuration import (
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
    FrozenTestCommand,
    reconstruct_concrete_runtime_configuration,
    runtime_configuration_payload,
)

from .approval_stage import ApprovalProjectionStageResult
from .stage_models import STAGE_SCHEMA_VERSION, require_exact_keys
from .validation_stage import (
    CandidateRuntimeInputs,
    ValidationStageDisposition,
    ValidationStageResult,
    prepare_validation_stage,
    validation_stage_result_from_dict,
    validation_stage_result_to_dict,
)


class ExecutionPacketDisposition(str, Enum):
    GO = "GO"
    BLOCKED = "BLOCKED"
    NEEDS_DECISION = "NEEDS-DECISION"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPacketStageResult:
    disposition: ExecutionPacketDisposition
    validation_stage: ValidationStageResult
    request: ExecutionServiceRequest | None
    command_plan: ValidationCommandPlan | None
    runtime_configuration: ConcreteRuntimeConfiguration | None
    request_fingerprint: str | None
    command_plan_id: str | None
    runtime_configuration_fingerprint: str | None
    packet_complete: bool
    runtime_capability_available: bool
    execution_authorization_present: bool
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    automatic_retry: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.disposition) is not ExecutionPacketDisposition:
            raise TypeError("disposition must be ExecutionPacketDisposition")
        if type(self.validation_stage) is not ValidationStageResult:
            raise TypeError("validation_stage must be exact ValidationStageResult")
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        if self.packet_complete:
            if type(self.request) is not ExecutionServiceRequest:
                raise ValueError("complete packet requires canonical request")
            if type(self.command_plan) is not ValidationCommandPlan:
                raise ValueError("complete packet requires canonical command plan")
            if type(self.runtime_configuration) is not ConcreteRuntimeConfiguration:
                raise ValueError("complete packet requires canonical runtime configuration")
            if not self.request_fingerprint or not self.command_plan_id or not self.runtime_configuration_fingerprint:
                raise ValueError("complete packet requires every canonical fingerprint")
        elif self.runtime_configuration is not None:
            raise ValueError("incomplete packet cannot carry runtime configuration")


_EXECUTION_PACKET_STAGE_RESULT_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "disposition",
        "validation_stage",
        "request",
        "command_plan",
        "runtime_configuration",
        "request_fingerprint",
        "command_plan_id",
        "runtime_configuration_fingerprint",
        "packet_complete",
        "runtime_capability_available",
        "execution_authorization_present",
        "reason_codes",
        "execution_authorized",
        "merge_authorized",
        "automatic_retry",
        "side_effects_performed",
    }
)


def execution_packet_stage_result_to_dict(
    result: ExecutionPacketStageResult,
) -> dict[str, Any]:
    """Serialize one canonical ExecutionPacketStageResult, delegating every nested object.

    ``validation_stage`` reuses this package's own ``validation_stage_result``
    transport; ``request``, ``command_plan``, and ``runtime_configuration``
    each reuse their owning package's canonical transport. Nothing here
    reimplements a nested shape.
    """
    if not isinstance(result, ExecutionPacketStageResult):
        raise TypeError("result must be an ExecutionPacketStageResult")
    payload = {
        "schema_version": STAGE_SCHEMA_VERSION,
        "disposition": result.disposition.value,
        "validation_stage": validation_stage_result_to_dict(result.validation_stage),
        "request": (
            None
            if result.request is None
            else serialize_execution_service_request(result.request)
        ),
        "command_plan": (
            None
            if result.command_plan is None
            else serialize_validation_command_plan(result.command_plan)
        ),
        "runtime_configuration": (
            None
            if result.runtime_configuration is None
            else runtime_configuration_payload(result.runtime_configuration)
        ),
        "request_fingerprint": result.request_fingerprint,
        "command_plan_id": result.command_plan_id,
        "runtime_configuration_fingerprint": result.runtime_configuration_fingerprint,
        "packet_complete": result.packet_complete,
        "runtime_capability_available": result.runtime_capability_available,
        "execution_authorization_present": result.execution_authorization_present,
        "reason_codes": list(result.reason_codes),
        "execution_authorized": False,
        "merge_authorized": False,
        "automatic_retry": False,
        "side_effects_performed": False,
    }
    if execution_packet_stage_result_from_dict(payload) != result:
        raise ValueError("result has noncanonical execution packet stage fields")
    return payload


def execution_packet_stage_result_from_dict(
    payload: Mapping[str, Any],
) -> ExecutionPacketStageResult:
    """Reconstruct one canonical ExecutionPacketStageResult, failing closed on drift.

    ``request_fingerprint``, ``command_plan_id``, and
    ``runtime_configuration_fingerprint`` are re-derived from the reconstructed
    nested objects and compared against the carried identities, and the
    command plan's own carried ``request_fingerprint``/``validation_plan_id``
    are checked against the request and validation-stage plan identity rather
    than trusted as free-standing scalars.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("execution packet stage result must be a mapping")
    if payload.get("schema_version") != STAGE_SCHEMA_VERSION:
        raise ValueError("unsupported stage schema_version")
    require_exact_keys(
        payload,
        _EXECUTION_PACKET_STAGE_RESULT_PAYLOAD_KEYS,
        "execution packet stage result",
    )
    for name in (
        "execution_authorized",
        "merge_authorized",
        "automatic_retry",
        "side_effects_performed",
    ):
        if payload[name] is not False:
            raise ValueError(f"{name} must be false")
    for name in (
        "packet_complete",
        "runtime_capability_available",
        "execution_authorization_present",
    ):
        if type(payload[name]) is not bool:
            raise ValueError(f"{name} must be an exact boolean")

    disposition = ExecutionPacketDisposition(payload["disposition"])
    validation_stage = validation_stage_result_from_dict(payload["validation_stage"])

    request_payload = payload["request"]
    command_plan_payload = payload["command_plan"]
    runtime_configuration_data = payload["runtime_configuration"]
    request_fingerprint = payload["request_fingerprint"]
    command_plan_id = payload["command_plan_id"]
    runtime_configuration_fingerprint = payload["runtime_configuration_fingerprint"]

    request: ExecutionServiceRequest | None = None
    if request_payload is not None:
        request = reconstruct_execution_service_request(request_payload)
        if request.request_fingerprint != request_fingerprint:
            raise ValueError("request_fingerprint does not match the canonical request")

    command_plan: ValidationCommandPlan | None = None
    if command_plan_payload is not None:
        command_plan = reconstruct_validation_command_plan(command_plan_payload)
        if validation_command_plan_id(command_plan) != command_plan_id:
            raise ValueError("command_plan_id does not match the canonical command plan")
        if request is not None and command_plan.request_fingerprint != request.request_fingerprint:
            raise ValueError("command plan does not bind to the execution-service request")
        if (
            validation_stage.validation_plan_id is not None
            and command_plan.validation_plan_id != validation_stage.validation_plan_id
        ):
            raise ValueError("command plan does not bind to the validation stage's plan")

    runtime_configuration: ConcreteRuntimeConfiguration | None = None
    if runtime_configuration_data is not None:
        if runtime_configuration_fingerprint is None:
            raise ValueError("runtime configuration requires its fingerprint")
        try:
            runtime_configuration = reconstruct_concrete_runtime_configuration(
                runtime_configuration_data,
                configuration_fingerprint=runtime_configuration_fingerprint,
            )
        except ConcreteRuntimeConfigurationError as error:
            raise ValueError(f"runtime configuration is invalid: {error}") from error
        if runtime_configuration.configuration_fingerprint != runtime_configuration_fingerprint:
            raise ValueError(
                "runtime_configuration_fingerprint does not match the canonical configuration"
            )

    reason_codes = payload["reason_codes"]
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise ValueError("reason_codes must be a list of strings")

    return ExecutionPacketStageResult(
        disposition=disposition,
        validation_stage=validation_stage,
        request=request,
        command_plan=command_plan,
        runtime_configuration=runtime_configuration,
        request_fingerprint=request_fingerprint,
        command_plan_id=command_plan_id,
        runtime_configuration_fingerprint=runtime_configuration_fingerprint,
        packet_complete=payload["packet_complete"],
        runtime_capability_available=payload["runtime_capability_available"],
        execution_authorization_present=payload["execution_authorization_present"],
        reason_codes=tuple(reason_codes),
    )


def prepare_execution_packet(
    approval_projection_stage_result: ApprovalProjectionStageResult,
    candidate_runtime_inputs: CandidateRuntimeInputs,
) -> ExecutionPacketStageResult:
    """Build every non-executing #754 packet object in one deterministic call."""

    validation = prepare_validation_stage(
        approval_projection_stage_result,
        candidate_runtime_inputs,
    )
    if validation.disposition is not ValidationStageDisposition.GO:
        return _result(
            ExecutionPacketDisposition.BLOCKED,
            validation,
            candidate_runtime_inputs,
            reason_codes=("validation-stage-not-go", *validation.reason_codes),
        )

    assert validation.subject is not None
    assert validation.validation_plan is not None
    assert validation.validation_plan_id is not None
    projection = approval_projection_stage_result.projection
    if projection is None:
        return _result(
            ExecutionPacketDisposition.BLOCKED,
            validation,
            candidate_runtime_inputs,
            reason_codes=("upstream-projection-missing",),
        )

    try:
        request = _build_request(validation, candidate_runtime_inputs)
        command_plan = build_validation_command_plan(
            request,
            validation.validation_plan,
            evaluated_at=candidate_runtime_inputs.evaluated_at,
        )
    except (TypeError, ValueError):
        return _result(
            ExecutionPacketDisposition.BLOCKED,
            validation,
            candidate_runtime_inputs,
            reason_codes=("execution-request-or-command-plan-invalid",),
        )

    plan_id = validation_command_plan_id(command_plan)
    if not candidate_runtime_inputs.runtime_capability_available:
        return _result(
            ExecutionPacketDisposition.BLOCKED,
            validation,
            candidate_runtime_inputs,
            request=request,
            command_plan=command_plan,
            command_plan_id=plan_id,
            reason_codes=("runtime-capability-unavailable",),
        )

    try:
        frozen_commands = tuple(
            FrozenTestCommand(test_id=command, argv=entry.argv)
            for command, entry in zip(
                validation.validation_plan.commands,
                command_plan.entries,
                strict=True,
            )
        )
        runtime = ConcreteRuntimeConfiguration.bind_candidate(
            repository=validation.repository or "",
            issue_number=candidate_runtime_inputs.issue_number,
            invocation_id=validation.subject.invocation_id,
            workspace_request_id=_stable_id("workspace", candidate_runtime_inputs),
            base_branch=validation.subject.base_branch,
            base_sha=validation.subject.base_sha,
            source_head_sha=validation.subject.expected_source_sha,
            tested_sha=validation.subject.tested_sha,
            branch=validation.subject.branch,
            projection_id=projection.projection_id,
            approval_id=projection.approval_id,
            validation_plan_id=validation.validation_plan_id,
            validation_bundle_id=candidate_runtime_inputs.validation_bundle_id,
            advisory_result_id=candidate_runtime_inputs.advisory_result_id,
            advisory_render_id=candidate_runtime_inputs.advisory_render_id,
            repository_identity=candidate_runtime_inputs.repository_identity,
            repository_root=candidate_runtime_inputs.repository_root,
            workspace_parent=candidate_runtime_inputs.workspace_parent,
            required_test_commands=frozen_commands,
            allowed_files=validation.subject.allowed_files,
            forbidden_paths=validation.subject.forbidden_paths,
            executor_timeout_seconds=candidate_runtime_inputs.per_command_timeout_seconds,
            validation_per_command_timeout_seconds=candidate_runtime_inputs.per_command_timeout_seconds,
            validation_total_timeout_seconds=candidate_runtime_inputs.total_timeout_seconds,
            executor_max_output_bytes=candidate_runtime_inputs.max_output_bytes,
            validation_max_output_bytes=candidate_runtime_inputs.max_output_bytes,
            required_environment_spec=candidate_runtime_inputs.required_environment_spec,
        )
    except (ConcreteRuntimeConfigurationError, TypeError, ValueError):
        return _result(
            ExecutionPacketDisposition.BLOCKED,
            validation,
            candidate_runtime_inputs,
            request=request,
            command_plan=command_plan,
            command_plan_id=plan_id,
            reason_codes=("runtime-configuration-invalid",),
        )

    disposition = (
        ExecutionPacketDisposition.GO
        if candidate_runtime_inputs.execution_authorization_present
        else ExecutionPacketDisposition.NEEDS_DECISION
    )
    reasons = () if disposition is ExecutionPacketDisposition.GO else ("execution-authorization-not-present",)
    return ExecutionPacketStageResult(
        disposition=disposition,
        validation_stage=validation,
        request=request,
        command_plan=command_plan,
        runtime_configuration=runtime,
        request_fingerprint=request.request_fingerprint,
        command_plan_id=plan_id,
        runtime_configuration_fingerprint=runtime.configuration_fingerprint,
        packet_complete=True,
        runtime_capability_available=True,
        execution_authorization_present=candidate_runtime_inputs.execution_authorization_present,
        reason_codes=reasons,
    )


def _build_request(
    validation: ValidationStageResult,
    inputs: CandidateRuntimeInputs,
) -> ExecutionServiceRequest:
    assert validation.subject is not None
    invalidation_conditions = tuple(
        sorted(ExecutionServiceInvalidationCondition, key=lambda item: item.value)
    )
    return ExecutionServiceRequest(
        schema_version=EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION,
        request_id=_stable_id("request", inputs),
        request_revision=inputs.request_revision,
        created_at=inputs.created_at,
        expires_at=inputs.expires_at,
        repository_identity=inputs.repository_identity,
        issue_or_handoff_identity=f"issue:{inputs.issue_number}",
        canonical_owner=inputs.canonical_owner,
        requesting_actor=inputs.requesting_actor,
        capability=ExecutionServiceCapability.VERIFY_REPOSITORY_STATE,
        base_branch=validation.subject.base_branch,
        base_sha=validation.subject.base_sha,
        requested_ref=validation.subject.branch,
        expected_sha=validation.subject.expected_source_sha,
        allowed_paths=validation.subject.allowed_files,
        forbidden_paths=validation.subject.forbidden_paths,
        inspected_file_count_limit=inputs.inspected_file_count_limit,
        inspected_byte_limit=inputs.inspected_byte_limit,
        evidence_visibility_policy=EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        invalidation_conditions=invalidation_conditions,
    )


def _stable_id(kind: str, inputs: CandidateRuntimeInputs) -> str:
    expected_paths = "\0".join(inputs.expected_changed_paths)
    digest = hashlib.sha256(
        (
            "agent-os-candidate-packet-v1\0"
            + kind
            + "\0"
            + f"{inputs.repository_identity.owner}/{inputs.repository_identity.repository}"
            + "\0"
            + str(inputs.issue_number)
            + "\0"
            + inputs.invocation_id
            + "\0"
            + inputs.candidate_sha
            + "\0"
            + expected_paths
        ).encode("utf-8")
    ).hexdigest()
    return f"candidate-{kind}:{digest}"


def _result(
    disposition: ExecutionPacketDisposition,
    validation: ValidationStageResult,
    inputs: CandidateRuntimeInputs,
    *,
    request: ExecutionServiceRequest | None = None,
    command_plan: ValidationCommandPlan | None = None,
    command_plan_id: str | None = None,
    reason_codes: tuple[str, ...],
) -> ExecutionPacketStageResult:
    return ExecutionPacketStageResult(
        disposition=disposition,
        validation_stage=validation,
        request=request,
        command_plan=command_plan,
        runtime_configuration=None,
        request_fingerprint=None if request is None else request.request_fingerprint,
        command_plan_id=command_plan_id,
        runtime_configuration_fingerprint=None,
        packet_complete=False,
        runtime_capability_available=inputs.runtime_capability_available,
        execution_authorization_present=inputs.execution_authorization_present,
        reason_codes=reason_codes,
    )
