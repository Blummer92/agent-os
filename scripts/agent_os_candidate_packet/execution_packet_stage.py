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
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from agent_os_execution_service.command_planning import (
    ValidationCommandPlan,
    build_validation_command_plan,
    validation_command_plan_id,
)
from agent_os_execution_service.models import (
    EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION,
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceRequest,
)
from workflow_scheduler.execution.runtime_configuration import (
    VALIDATION_ONLY_EXECUTION_MODE,
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
    FrozenTestCommand,
    SingleIssuePilotInput,
)

from .approval_stage import ApprovalProjectionStageResult
from .validation_stage import (
    CandidateRuntimeInputs,
    ValidationStageDisposition,
    ValidationStageResult,
    prepare_validation_stage,
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
        pilot_input = SingleIssuePilotInput(
            execution_mode=VALIDATION_ONLY_EXECUTION_MODE,
            issue_numbers=(candidate_runtime_inputs.issue_number,),
            requested_concurrency=1,
            repository=validation.repository or "",
            base_branch=validation.subject.base_branch,
            base_sha=validation.subject.base_sha,
            source_head_sha=validation.subject.expected_source_sha,
            tested_sha=validation.subject.tested_sha,
            branch=validation.subject.branch,
            invocation_id=validation.subject.invocation_id,
            workspace_request_id=_stable_id("workspace", candidate_runtime_inputs),
            projection=projection,
            expected_projection_id=projection.projection_id,
            expected_proposal_id=projection.proposal_id,
            expected_approval_id=projection.approval_id,
            expected_issueplan_evidence=None,
            current_issueplan_evidence=None,
            approval_record=approval_projection_stage_result.decision_revision,
            current_proposal=None,
            repository_state_evidence=candidate_runtime_inputs.repository_state_evidence,
            evaluated_at=candidate_runtime_inputs.evaluated_at,
            validation_plan=validation.validation_plan,
            expected_plan_id=validation.validation_plan_id,
            evidence_bundle=None,
            expected_bundle_id=candidate_runtime_inputs.validation_bundle_id,
            advisory_result=None,
            expected_advisory_result_id=candidate_runtime_inputs.advisory_result_id,
            advisory_render=None,
            expected_advisory_render_id=candidate_runtime_inputs.advisory_render_id,
            allowed_files=validation.subject.allowed_files,
            forbidden_paths=validation.subject.forbidden_paths,
            required_tests=validation.validation_plan.commands,
        )
        runtime = ConcreteRuntimeConfiguration.bind(
            pilot_input,
            repository_identity=candidate_runtime_inputs.repository_identity,
            repository_root=candidate_runtime_inputs.repository_root,
            workspace_parent=candidate_runtime_inputs.workspace_parent,
            required_test_commands=frozen_commands,
            executor_argv=None,
            execution_mode=VALIDATION_ONLY_EXECUTION_MODE,
            executor_timeout_seconds=candidate_runtime_inputs.per_command_timeout_seconds,
            validation_per_command_timeout_seconds=candidate_runtime_inputs.per_command_timeout_seconds,
            validation_total_timeout_seconds=candidate_runtime_inputs.total_timeout_seconds,
            executor_max_output_bytes=candidate_runtime_inputs.max_output_bytes,
            validation_max_output_bytes=candidate_runtime_inputs.max_output_bytes,
        )
        runtime.verify(pilot_input)
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