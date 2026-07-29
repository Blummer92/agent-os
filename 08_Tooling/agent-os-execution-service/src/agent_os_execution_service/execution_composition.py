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
    CommandOperation,
    ValidationCommandPlan,
    validation_command_plan_id,
)
from .models import ExecutionServiceRequest, parse_canonical_utc
from .request_validation import validate_execution_service_request

EXECUTION_COMPOSITION_SCHEMA_VERSION = "1.0"

_EXECUTABLE_PROFILES = ("focused", "aggregate")

_PROFILE_OPERATIONS = {
    "static": CommandOperation.VALIDATION_STATIC,
    "focused": CommandOperation.VALIDATION_FOCUSED,
    "aggregate": CommandOperation.VALIDATION_AGGREGATE,
}

# The canonical single-issue runtime proves a complete lifecycle with exactly
# one status. A passing ``FrozenTestValidationResult`` is produced before
# teardown, so it alone never proves that cleanup, release, containment, or
# any other post-validation phase succeeded: only ``completed`` does.
_COMPLETED_RUNTIME_STATUS = "completed"
_CANCELLED_RUNTIME_STATUS = "cancelled"

# Non-completed statuses whose evidence is operational -- something was left
# behind or an adapter/bounded process failed -- rather than a decision
# request. ``quarantined`` dominates: it is exactly the canonical signal for
# a failed cleanup, a failed or ambiguous release, or a containment stop.
_QUARANTINED_RUNTIME_STATUS = "quarantined"
_INFRASTRUCTURE_RUNTIME_STATUSES = frozenset(
    (_QUARANTINED_RUNTIME_STATUS, "failed", "timed-out")
)


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
    if request.requested_ref != command_plan.requested_ref:
        reasons.append("requested-ref-mismatch")
    if request.request_revision != command_plan.request_revision:
        reasons.append("request-revision-mismatch")
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

    expected_operation = _PROFILE_OPERATIONS.get(command_plan.profile)
    if expected_operation is None or any(
        entry.operation is not expected_operation for entry in command_plan.entries
    ):
        reasons.append("command-plan-operation-mismatch")

    if command_plan.profile in _EXECUTABLE_PROFILES:
        # Ordered comparison: the command plan's own canonical order is the
        # authorized one, so a reordering is drift rather than something this
        # module may silently accept.
        plan_argv = tuple(entry.argv for entry in command_plan.entries)
        required_argv = tuple(
            item.argv for item in configuration.required_test_commands
        )
        if not command_plan.entries or plan_argv != required_argv:
            reasons.append("command-plan-argv-mismatch")

    try:
        configuration.verify(pilot_input)
    except ConcreteRuntimeConfigurationError:
        reasons.append("configuration-pilot-input-drift")

    return reasons


def _project_status(
    *,
    runtime_status: object,
    profile: str,
    validation_result: FrozenTestValidationResult | None,
) -> tuple[ExecutionCompositionStatus, bool]:
    """Map one canonical runtime outcome to bounded composition evidence.

    A pass status is projected only when the canonical runtime reports the
    complete lifecycle (``completed``) *and* the retained validation evidence
    passed. A passing validation result over any other runtime status --
    ``quarantined`` after a cleanup or release failure, ``failed``,
    ``timed-out``, ``blocked``, ``stale``, ``needs-decision``, or an unknown
    or malformed status -- never becomes focused or aggregate success.
    """
    focused = profile == "focused"

    if runtime_status == _CANCELLED_RUNTIME_STATUS:
        return ExecutionCompositionStatus.CANCELLED, True

    attempted = validation_result is not None and validation_result.attempted
    passed = attempted and bool(validation_result.passed)  # type: ignore[union-attr]

    if runtime_status == _COMPLETED_RUNTIME_STATUS:
        if not attempted:
            # A complete lifecycle without attempted validation evidence is
            # contradictory; it is a decision request, never a success.
            return ExecutionCompositionStatus.MANUAL_REVIEW, True
        if passed:
            if focused:
                return ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING, True
            return ExecutionCompositionStatus.AGGREGATE_PASS, False
        return (
            (ExecutionCompositionStatus.FOCUSED_FAIL, True)
            if focused
            else (ExecutionCompositionStatus.AGGREGATE_FAIL, False)
        )

    # The runtime did not complete. Quarantine dominates every other reading:
    # something was left behind for a human even when the tests themselves
    # failed, so it is never reduced to an ordinary validation failure.
    if runtime_status == _QUARANTINED_RUNTIME_STATUS:
        return ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE, True
    if attempted and not passed:
        return (
            (ExecutionCompositionStatus.FOCUSED_FAIL, True)
            if focused
            else (ExecutionCompositionStatus.AGGREGATE_FAIL, False)
        )
    if runtime_status in _INFRASTRUCTURE_RUNTIME_STATUSES:
        return ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE, True
    return ExecutionCompositionStatus.MANUAL_REVIEW, True


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
    false; a generic pass boolean is never exposed. A pass status requires
    both a passing retained validation result and a canonical runtime status
    of ``completed``: focused success remains
    ``focused-pass-aggregate-pending`` with ``aggregate_pending`` true, and
    only a completed canonical aggregate run may project ``aggregate-pass``.
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
        # Delegation was entered, so no evidence proves nothing was left
        # behind. Side effects are reported conservatively as possible rather
        # than asserted absent.
        return _fail_closed(
            request=request,
            command_plan=command_plan,
            reasons=(
                "infrastructure-failure:runtime-entrypoint-exception",
                "side-effects-unknown-after-delegation",
            ),
            status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
            execution_authorized=True,
            side_effects_performed=True,
        )

    if type(outcome) is not ConcreteRuntimeExecutionOutcome:
        return _fail_closed(
            request=request,
            command_plan=command_plan,
            reasons=(
                "infrastructure-failure:unexpected-return-shape",
                "side-effects-unknown-after-delegation",
            ),
            status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
            execution_authorized=True,
            side_effects_performed=True,
        )

    pilot_result = outcome.runtime_outcome.result
    validation_result = outcome.validation_result
    side_effects_performed = bool(
        pilot_result.lease_acquired
        or pilot_result.workspace_created
        or pilot_result.executor_called
        or pilot_result.possible_partial_effects
        or pilot_result.cleanup_errors
        or pilot_result.release_errors
    )

    status, aggregate_pending = _project_status(
        runtime_status=pilot_result.status,
        profile=command_plan.profile,
        validation_result=validation_result,
    )

    # Canonical runtime evidence is preserved exactly and only added to: a
    # withheld pass, a failed cleanup, and a failed or ambiguous release stay
    # visible instead of being replaced by a generic success reason.
    composition_reasons = ["runtime-status:" + pilot_result.status]
    if pilot_result.cleanup_errors:
        composition_reasons.append("runtime-cleanup-errors-present")
    if pilot_result.release_errors:
        composition_reasons.append("runtime-release-errors-present")
    if (
        pilot_result.status != _COMPLETED_RUNTIME_STATUS
        and validation_result is not None
        and validation_result.attempted
        and validation_result.passed
    ):
        composition_reasons.append("runtime-incomplete:pass-withheld")
    reason_codes = tuple(
        sorted(set(tuple(composition_reasons) + pilot_result.reason_codes))
    )

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
