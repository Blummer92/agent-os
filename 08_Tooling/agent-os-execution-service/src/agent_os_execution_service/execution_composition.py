"""Thin, non-authorizing composition boundary for governed validation execution.

This module consumes caller-supplied immutable evidence (an exact
``ExecutionServiceRequest``, an exact ``ValidationCommandPlan``, explicit
execution-authorization evidence, and a caller-supplied Workflow Scheduler
runtime configuration/pilot input), revalidates every bound identity, and
delegates exactly once to the canonical
``run_concrete_runtime_entrypoint_with_validation_evidence`` entrypoint. It
retains and returns the exact canonical ``FrozenTestValidationResult``
without rerunning validation or constructing a competing per-command
evidence model.

It implements no process runner, executor, worktree manager, lease system,
scheduler, retry loop, command registry, or shell parser. Local bounded
worktree creation, exact validation-command execution, changed-path
inspection, cleanup, release, quarantine, and evidence return are expected
authorized runtime operations performed by the reused Workflow Scheduler
lifecycle, not by this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from workflow_scheduler.execution.concrete_runtime_adapters import (
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
    ConcreteRuntimeExecutionOutcome,
    run_concrete_runtime_entrypoint_with_validation_evidence,
)
from workflow_scheduler.execution.frozen_test_validation_adapter import (
    FrozenTestValidationResult,
)
from workflow_scheduler.execution.single_issue_pilot import (
    CancellationProbe,
    SingleIssuePilotInput,
)

from .command_planning import (
    COMMAND_PLAN_SCHEMA_VERSION,
    COMMAND_REGISTRY_VERSION,
    ValidationCommandPlan,
    validation_command_plan_id,
)
from .models import ExecutionServiceRequest, parse_canonical_utc
from .request_validation import validate_execution_service_request

EXECUTION_COMPOSITION_SCHEMA_VERSION = "1.0"

_EXECUTABLE_PROFILES = ("focused", "aggregate")


class ExecutionCompositionStatus(str, Enum):
    FOCUSED_PASS_AGGREGATE_PENDING = "focused-pass-aggregate-pending"
    FOCUSED_FAIL = "focused-fail"
    AGGREGATE_PASS = "aggregate-pass"
    AGGREGATE_FAIL = "aggregate-fail"
    MANUAL_REVIEW = "manual-review"
    CANCELLED = "cancelled"
    INFRASTRUCTURE_FAILURE = "infrastructure-failure"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAuthorizationEvidence:
    """Explicit, caller-supplied authorization binding one plan to one SHA."""

    authorization_id: str
    request_fingerprint: str
    command_plan_id: str
    repository: str
    expected_sha: str
    authorized_at: str
    expires_at: str
    execution_authorized: bool
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in (
            "authorization_id",
            "request_fingerprint",
            "command_plan_id",
            "repository",
            "expected_sha",
        ):
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise TypeError(f"{name} must be a non-empty exact string")
        if type(self.execution_authorized) is not bool:
            raise TypeError("execution_authorized must be an exact boolean")
        parse_canonical_utc(self.authorized_at)
        parse_canonical_utc(self.expires_at)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionCompositionResult:
    """Bounded, non-authorizing evidence for one composition attempt."""

    schema_version: str = EXECUTION_COMPOSITION_SCHEMA_VERSION
    request_fingerprint: str
    command_plan_id: str
    repository: str
    expected_sha: str
    profile: str
    status: ExecutionCompositionStatus
    validation_result: FrozenTestValidationResult | None
    aggregate_pending: bool
    execution_authorized: bool
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: bool
    reason_codes: tuple[str, ...]
    evidence_id: str


def _evidence_id(*, status: ExecutionCompositionStatus, profile: str, **fields: object) -> str:
    payload = {
        "domain": "agent-os-execution-composition-evidence",
        "schema_version": EXECUTION_COMPOSITION_SCHEMA_VERSION,
        "status": status.value,
        "profile": profile,
        **fields,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(b"agent-os-execution-composition:v1\0" + encoded).hexdigest()
    return f"execution-composition:{digest}"


def _fail_closed(
    *,
    request: ExecutionServiceRequest,
    command_plan: ValidationCommandPlan,
    reasons: tuple[str, ...],
    status: ExecutionCompositionStatus = ExecutionCompositionStatus.MANUAL_REVIEW,
    execution_authorized: bool = False,
    side_effects_performed: bool = False,
) -> ExecutionCompositionResult:
    evidence_id = _evidence_id(
        status=status,
        profile=command_plan.profile,
        request_fingerprint=request.request_fingerprint,
        command_plan_id=validation_command_plan_id(command_plan),
        reasons=list(reasons),
    )
    return ExecutionCompositionResult(
        request_fingerprint=request.request_fingerprint,
        command_plan_id=validation_command_plan_id(command_plan),
        repository=command_plan.repository,
        expected_sha=command_plan.expected_sha,
        profile=command_plan.profile,
        status=status,
        validation_result=None,
        aggregate_pending=True,
        execution_authorized=execution_authorized,
        side_effects_performed=side_effects_performed,
        reason_codes=tuple(sorted(set(reasons))),
        evidence_id=evidence_id,
    )


def _identity_mismatches(
    *,
    request: ExecutionServiceRequest,
    command_plan: ValidationCommandPlan,
    authorization: ExecutionAuthorizationEvidence,
    evaluated_at: str,
    pilot_input: SingleIssuePilotInput,
    configuration: ConcreteRuntimeConfiguration,
) -> list[str]:
    reasons: list[str] = []
    request_repository = (
        f"{request.repository_identity.owner}/{request.repository_identity.repository}"
    )

    request_reasons = validate_execution_service_request(request, evaluated_at=evaluated_at)
    if request_reasons:
        reasons.extend(f"request-invalid:{item.value}" for item in request_reasons)

    if request.request_fingerprint != command_plan.request_fingerprint:
        reasons.append("request-fingerprint-mismatch")
    if request_repository.casefold() != command_plan.repository.casefold():
        reasons.append("repository-mismatch")
    if request.expected_sha != command_plan.expected_sha:
        reasons.append("expected-sha-mismatch")
    if (
        command_plan.schema_version != COMMAND_PLAN_SCHEMA_VERSION
        or command_plan.registry_version != COMMAND_REGISTRY_VERSION
    ):
        reasons.append("command-plan-version-mismatch")

    computed_plan_id = validation_command_plan_id(command_plan)
    if authorization.command_plan_id != computed_plan_id:
        reasons.append("authorization-plan-id-mismatch")
    if authorization.request_fingerprint != request.request_fingerprint:
        reasons.append("authorization-request-fingerprint-mismatch")
    if authorization.repository.casefold() != request_repository.casefold():
        reasons.append("authorization-repository-mismatch")
    if authorization.expected_sha != request.expected_sha:
        reasons.append("authorization-expected-sha-mismatch")
    if not authorization.execution_authorized:
        reasons.append("authorization-not-granted")

    try:
        evaluated = parse_canonical_utc(evaluated_at)
        authorized_at = parse_canonical_utc(authorization.authorized_at)
        expires_at = parse_canonical_utc(authorization.expires_at)
    except (TypeError, ValueError):
        reasons.append("authorization-timestamp-malformed")
    else:
        if not (authorized_at <= evaluated < expires_at):
            reasons.append("authorization-expired-or-not-yet-active")

    if configuration.repository.casefold() != request_repository.casefold():
        reasons.append("configuration-repository-mismatch")
    if configuration.source_head_sha != request.expected_sha:
        reasons.append("configuration-source-sha-mismatch")
    if configuration.tested_sha != request.expected_sha:
        reasons.append("configuration-tested-sha-mismatch")
    if configuration.validation_plan_id != command_plan.validation_plan_id:
        reasons.append("configuration-validation-plan-id-mismatch")
    if tuple(sorted(configuration.allowed_files)) != tuple(sorted(request.allowed_paths)):
        reasons.append("configuration-allowed-files-mismatch")
    if tuple(sorted(configuration.forbidden_paths)) != tuple(sorted(request.forbidden_paths)):
        reasons.append("configuration-forbidden-paths-mismatch")

    if command_plan.profile in _EXECUTABLE_PROFILES:
        plan_argv = tuple(sorted(entry.argv for entry in command_plan.entries))
        required_argv = tuple(
            sorted(item.argv for item in configuration.required_test_commands)
        )
        if not command_plan.entries or plan_argv != required_argv:
            reasons.append("command-plan-argv-mismatch")

    try:
        configuration.verify(pilot_input)
    except ConcreteRuntimeConfigurationError:
        reasons.append("configuration-pilot-input-drift")

    return reasons


def compose_and_run_validation(
    *,
    request: ExecutionServiceRequest,
    command_plan: ValidationCommandPlan,
    authorization: ExecutionAuthorizationEvidence,
    evaluated_at: str,
    pilot_input: SingleIssuePilotInput,
    configuration: ConcreteRuntimeConfiguration,
    cancelled: CancellationProbe,
    git_runner: object | None = None,
    process_cancelled: object | None = None,
    changed_paths_inspector: object | None = None,
) -> ExecutionCompositionResult:
    """Revalidate identity, then delegate exactly once to the canonical entrypoint.

    Returns bounded, non-authorizing evidence. ``merge_authorized`` is always
    false; a generic pass boolean is never exposed. Focused success remains
    ``focused-pass-aggregate-pending`` with ``aggregate_pending`` true; only
    canonical aggregate success may project ``aggregate-pass``.
    """
    if type(request) is not ExecutionServiceRequest:
        raise TypeError("request must be an exact ExecutionServiceRequest")
    if type(command_plan) is not ValidationCommandPlan:
        raise TypeError("command_plan must be an exact ValidationCommandPlan")
    if type(authorization) is not ExecutionAuthorizationEvidence:
        raise TypeError("authorization must be exact ExecutionAuthorizationEvidence")
    if not isinstance(pilot_input, SingleIssuePilotInput):
        raise TypeError("pilot_input must be SingleIssuePilotInput")
    if not isinstance(configuration, ConcreteRuntimeConfiguration):
        raise TypeError("configuration must be ConcreteRuntimeConfiguration")

    mismatches = _identity_mismatches(
        request=request,
        command_plan=command_plan,
        authorization=authorization,
        evaluated_at=evaluated_at,
        pilot_input=pilot_input,
        configuration=configuration,
    )
    if mismatches:
        return _fail_closed(
            request=request,
            command_plan=command_plan,
            reasons=tuple(mismatches),
        )

    if command_plan.profile not in _EXECUTABLE_PROFILES:
        return _fail_closed(
            request=request,
            command_plan=command_plan,
            reasons=("unsupported-profile-no-execution",),
            execution_authorized=authorization.execution_authorized,
        )

    # Delegate exactly once through the canonical validation-evidence
    # entrypoint. All process execution, worktree creation, lease handling,
    # changed-path inspection, cleanup, release, and quarantine are owned by
    # the reused Workflow Scheduler lifecycle; this module performs none of
    # them directly.
    try:
        outcome = run_concrete_runtime_entrypoint_with_validation_evidence(
            pilot_input,
            configuration,
            cancelled=cancelled,
            git_runner=git_runner,
            process_cancelled=process_cancelled,
            changed_paths_inspector=changed_paths_inspector,
        )
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except Exception:  # noqa: BLE001 - bounded operational-boundary conversion
        return _fail_closed(
            request=request,
            command_plan=command_plan,
            reasons=("infrastructure-failure:runtime-entrypoint-exception",),
            status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
            execution_authorized=True,
            side_effects_performed=False,
        )

    if type(outcome) is not ConcreteRuntimeExecutionOutcome:
        return _fail_closed(
            request=request,
            command_plan=command_plan,
            reasons=("infrastructure-failure:unexpected-return-shape",),
            status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
            execution_authorized=True,
            side_effects_performed=False,
        )

    pilot_result = outcome.runtime_outcome.result
    validation_result = outcome.validation_result
    side_effects_performed = bool(pilot_result.lease_acquired or pilot_result.workspace_created)

    reason_codes = tuple(sorted(set(("runtime-status:" + pilot_result.status,) + pilot_result.reason_codes)))

    if pilot_result.status == "cancelled":
        status = ExecutionCompositionStatus.CANCELLED
        aggregate_pending = True
    elif validation_result is None or not validation_result.attempted:
        status = ExecutionCompositionStatus.MANUAL_REVIEW
        aggregate_pending = True
    elif validation_result.passed:
        if command_plan.profile == "focused":
            status = ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
            aggregate_pending = True
        else:
            status = ExecutionCompositionStatus.AGGREGATE_PASS
            aggregate_pending = False
    else:
        if command_plan.profile == "focused":
            status = ExecutionCompositionStatus.FOCUSED_FAIL
            aggregate_pending = True
        else:
            status = ExecutionCompositionStatus.AGGREGATE_FAIL
            aggregate_pending = False

    evidence_id = _evidence_id(
        status=status,
        profile=command_plan.profile,
        request_fingerprint=request.request_fingerprint,
        command_plan_id=validation_command_plan_id(command_plan),
        pilot_result_id=pilot_result.result_id,
    )

    return ExecutionCompositionResult(
        request_fingerprint=request.request_fingerprint,
        command_plan_id=validation_command_plan_id(command_plan),
        repository=command_plan.repository,
        expected_sha=command_plan.expected_sha,
        profile=command_plan.profile,
        status=status,
        validation_result=validation_result,
        aggregate_pending=aggregate_pending,
        execution_authorized=True,
        side_effects_performed=side_effects_performed,
        reason_codes=reason_codes,
        evidence_id=evidence_id,
    )
