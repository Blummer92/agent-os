from __future__ import annotations

import re
from datetime import datetime, timezone

from agent_os_execution_service import (
    ExecutionAuthorizationEvidence,
    ExecutionServiceReason,
    ExecutionServiceRequest,
    ValidationCommandPlan,
    execution_service_request_fingerprint,
    validate_execution_service_request,
    validation_command_plan_id,
)
from scripts.agent_os_cloud_build_reporting import OverallResult, normalize_cloud_build_evidence
from scripts.agent_os_remote_validation import DispatchDecision, dispatch_decision_id

from .models import (
    PROVIDER_SCHEMA_VERSION,
    CloudBuildProviderConfiguration,
    CloudBuildProviderInvocation,
    CloudBuildProviderObservation,
    CloudBuildProviderResult,
    ProviderCommandEntry,
    ProviderObservationStatus,
    ProviderReason,
    ProviderSideEffectState,
    ProviderStatus,
    argv_identity,
    cloud_build_provider_configuration_fingerprint,
)

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_PROFILE_OPERATION = {
    "static": "validation.static",
    "focused": "validation.focused",
    "aggregate": "validation.aggregate",
}
_NON_LAUNCH_STATUSES = {
    "reused",
    "duplicate-no-op",
    "stale-skipped",
    "supersede-required",
    "manual-review",
}


def prepare_cloud_build_provider_invocation(
    request: object,
    command_plan: object,
    dispatch_decision: object,
    authorization: object,
    configuration: object,
    *,
    resolved_sha: object,
    evaluated_at: object,
) -> CloudBuildProviderResult:
    reasons: set[ProviderReason] = set()
    if type(request) is not ExecutionServiceRequest:
        reasons.add(ProviderReason.INPUT_INVALID_TYPE)
    if type(command_plan) is not ValidationCommandPlan:
        reasons.add(ProviderReason.INPUT_INVALID_TYPE)
    if type(dispatch_decision) is not DispatchDecision:
        reasons.add(ProviderReason.INPUT_INVALID_TYPE)
    if type(authorization) is not ExecutionAuthorizationEvidence:
        reasons.add(ProviderReason.INPUT_INVALID_TYPE)
    if type(configuration) is not CloudBuildProviderConfiguration:
        reasons.add(ProviderReason.INPUT_INVALID_TYPE)
    if type(resolved_sha) is not str or not _SHA40_RE.fullmatch(resolved_sha):
        reasons.add(ProviderReason.INPUT_MALFORMED)
    if type(evaluated_at) is not str or _parse_utc(evaluated_at) is None:
        reasons.add(ProviderReason.INPUT_MALFORMED)
    if reasons:
        return _result(
            status=ProviderStatus.MANUAL_REVIEW,
            reasons=reasons,
            execution_authorized=False,
        )

    assert type(request) is ExecutionServiceRequest
    assert type(command_plan) is ValidationCommandPlan
    assert type(dispatch_decision) is DispatchDecision
    assert type(authorization) is ExecutionAuthorizationEvidence
    assert type(configuration) is CloudBuildProviderConfiguration
    assert type(resolved_sha) is str
    assert type(evaluated_at) is str

    request_reasons = validate_execution_service_request(request, evaluated_at=evaluated_at)
    if request_reasons:
        if ExecutionServiceReason.EXPIRED_REQUEST in request_reasons:
            reasons.add(ProviderReason.REQUEST_EXPIRED)
        else:
            reasons.add(ProviderReason.REQUEST_INVALID)
    if request.request_fingerprint != execution_service_request_fingerprint(request):
        reasons.add(ProviderReason.REQUEST_FINGERPRINT_MISMATCH)

    try:
        computed_plan_id = validation_command_plan_id(command_plan)
    except (TypeError, ValueError):
        computed_plan_id = None
        reasons.add(ProviderReason.COMMAND_PLAN_INVALID)

    request_repository = f"{request.repository_identity.owner}/{request.repository_identity.repository}"
    if request_repository.casefold() != command_plan.repository.casefold():
        reasons.add(ProviderReason.REPOSITORY_MISMATCH)
    if request.requested_ref != command_plan.requested_ref:
        reasons.add(ProviderReason.REQUESTED_REF_MISMATCH)
    if request.expected_sha != command_plan.expected_sha:
        reasons.add(ProviderReason.EXPECTED_SHA_MISMATCH)
    if request.request_revision != command_plan.request_revision:
        reasons.add(ProviderReason.COMMAND_PLAN_REQUEST_MISMATCH)
    if request.request_fingerprint != command_plan.request_fingerprint:
        reasons.add(ProviderReason.COMMAND_PLAN_REQUEST_MISMATCH)
    if request.issue_or_handoff_identity != command_plan.issue_or_handoff_identity:
        reasons.add(ProviderReason.COMMAND_PLAN_REQUEST_MISMATCH)

    expected_operation = _PROFILE_OPERATION.get(command_plan.profile)
    if expected_operation is None:
        reasons.add(ProviderReason.PROFILE_MISMATCH)
    elif any(entry.operation.value != expected_operation for entry in command_plan.entries):
        reasons.add(ProviderReason.COMMAND_PLAN_OPERATION_MISMATCH)
    if len({entry.argv for entry in command_plan.entries}) != len(command_plan.entries):
        reasons.add(ProviderReason.COMMAND_PLAN_ARGV_MISMATCH)

    try:
        computed_dispatch_id = dispatch_decision_id(dispatch_decision)
    except (TypeError, ValueError):
        computed_dispatch_id = None
        reasons.add(ProviderReason.DISPATCH_INVALID)
    if computed_dispatch_id is not None and computed_dispatch_id != dispatch_decision.decision_id:
        reasons.add(ProviderReason.DISPATCH_ID_MISMATCH)
    if dispatch_decision.status in _NON_LAUNCH_STATUSES or not dispatch_decision.launch_recommended:
        reasons.add(ProviderReason.DISPATCH_NON_LAUNCH)
    if dispatch_decision.status != "launch-eligible":
        reasons.add(ProviderReason.DISPATCH_NON_LAUNCH)
    if dispatch_decision.repository is None or dispatch_decision.repository.casefold() != command_plan.repository.casefold():
        reasons.add(ProviderReason.REPOSITORY_MISMATCH)
    if dispatch_decision.head_sha != command_plan.expected_sha:
        reasons.add(ProviderReason.EXPECTED_SHA_MISMATCH)
    if dispatch_decision.profile != command_plan.profile:
        reasons.add(ProviderReason.PROFILE_MISMATCH)
    if dispatch_decision.selector_version != command_plan.selector_version:
        reasons.add(ProviderReason.DIGEST_MISMATCH)
    if dispatch_decision.command_set_digest != command_plan.command_set_digest:
        reasons.add(ProviderReason.DIGEST_MISMATCH)
    if dispatch_decision.plan_id != command_plan.validation_plan_id:
        reasons.add(ProviderReason.COMMAND_PLAN_VALIDATION_PLAN_MISMATCH)
    if not dispatch_decision.dispatch_identity:
        reasons.add(ProviderReason.DISPATCH_IDENTITY_MISMATCH)

    if not authorization.execution_authorized:
        reasons.add(ProviderReason.AUTHORIZATION_NOT_GRANTED)
    authorized_at = _parse_utc(authorization.authorized_at)
    expires_at = _parse_utc(authorization.expires_at)
    evaluated = _parse_utc(evaluated_at)
    if authorized_at is None or expires_at is None or evaluated is None:
        reasons.add(ProviderReason.AUTHORIZATION_INVALID)
    elif not (authorized_at <= evaluated < expires_at):
        reasons.add(ProviderReason.AUTHORIZATION_INACTIVE)
    if authorization.request_fingerprint != request.request_fingerprint:
        reasons.add(ProviderReason.AUTHORIZATION_MISMATCH)
    if computed_plan_id is None or authorization.command_plan_id != computed_plan_id:
        reasons.add(ProviderReason.AUTHORIZATION_MISMATCH)
    if authorization.repository.casefold() != request_repository.casefold():
        reasons.add(ProviderReason.AUTHORIZATION_MISMATCH)
    if authorization.expected_sha != request.expected_sha:
        reasons.add(ProviderReason.AUTHORIZATION_MISMATCH)

    if resolved_sha != request.expected_sha:
        reasons.add(ProviderReason.RESOLVED_SHA_MISMATCH)
    if configuration.configuration_fingerprint != cloud_build_provider_configuration_fingerprint(configuration):
        reasons.add(ProviderReason.PROVIDER_CONFIGURATION_FINGERPRINT_MISMATCH)

    if reasons:
        non_launch_only = reasons == {ProviderReason.DISPATCH_NON_LAUNCH}
        return _result(
            status=ProviderStatus.SKIPPED if non_launch_only else ProviderStatus.MANUAL_REVIEW,
            reasons=reasons,
            execution_authorized=False,
        )

    provider_entries = tuple(
        ProviderCommandEntry(operation=entry.operation.value, argv=entry.argv)
        for entry in command_plan.entries
    )
    argv_ids = tuple(argv_identity(entry) for entry in provider_entries)
    invocation = CloudBuildProviderInvocation(
        schema_version=PROVIDER_SCHEMA_VERSION,
        request_id=request.request_id,
        request_revision=request.request_revision,
        request_fingerprint=request.request_fingerprint,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        command_plan_id=computed_plan_id,
        validation_plan_id=command_plan.validation_plan_id,
        dispatch_decision_id=dispatch_decision.decision_id,
        dispatch_identity=dispatch_decision.dispatch_identity,
        authorization_id=authorization.authorization_id,
        repository=command_plan.repository,
        requested_ref=command_plan.requested_ref,
        expected_sha=command_plan.expected_sha,
        resolved_sha=resolved_sha,
        profile=command_plan.profile,
        selector_version=command_plan.selector_version,
        command_set_digest=command_plan.command_set_digest,
        fixed_command_entries=provider_entries,
        fixed_argv_identities=argv_ids,
        provider_configuration_fingerprint=configuration.configuration_fingerprint,
    )
    return _result(
        status=ProviderStatus.ACCEPTED,
        reasons={ProviderReason.ACCEPTED},
        invocation=invocation,
        invocation_id=invocation.invocation_id,
        execution_authorized=True,
    )


def project_cloud_build_provider_result(
    invocation: object,
    observation: object,
) -> CloudBuildProviderResult:
    if type(invocation) is not CloudBuildProviderInvocation or type(observation) is not CloudBuildProviderObservation:
        return _result(
            status=ProviderStatus.MANUAL_REVIEW,
            reasons={ProviderReason.INPUT_INVALID_TYPE},
            execution_authorized=False,
        )

    reasons: set[ProviderReason] = set()
    if observation.invocation_id != invocation.invocation_id:
        reasons.add(ProviderReason.OBSERVATION_INVOCATION_MISMATCH)
    if observation.repository.casefold() != invocation.repository.casefold():
        reasons.add(ProviderReason.OBSERVATION_REPOSITORY_MISMATCH)
    if observation.tested_sha is not None and observation.tested_sha != invocation.resolved_sha:
        reasons.add(ProviderReason.OBSERVATION_TESTED_SHA_MISMATCH)
    if reasons:
        return _result(
            status=ProviderStatus.MANUAL_REVIEW,
            reasons=reasons,
            invocation=invocation,
            invocation_id=invocation.invocation_id,
            build_id=observation.build_id,
            tested_sha=observation.tested_sha,
            execution_authorized=True,
            side_effect_state=observation.side_effect_state,
        )

    if observation.terminal_status is ProviderObservationStatus.WORKING:
        return _result(
            status=ProviderStatus.UNAVAILABLE,
            reasons={ProviderReason.OBSERVATION_NONTERMINAL},
            invocation=invocation,
            invocation_id=invocation.invocation_id,
            build_id=observation.build_id,
            tested_sha=observation.tested_sha,
            execution_authorized=True,
            side_effect_state=observation.side_effect_state,
        )
    if observation.terminal_status is ProviderObservationStatus.UNAVAILABLE:
        return _result(
            status=ProviderStatus.UNAVAILABLE,
            reasons={ProviderReason.OBSERVATION_UNAVAILABLE},
            invocation=invocation,
            invocation_id=invocation.invocation_id,
            build_id=observation.build_id,
            tested_sha=observation.tested_sha,
            execution_authorized=True,
            side_effect_state=observation.side_effect_state,
        )
    if observation.terminal_status is ProviderObservationStatus.UNKNOWN:
        return _result(
            status=ProviderStatus.UNKNOWN,
            reasons={ProviderReason.OBSERVATION_UNKNOWN},
            invocation=invocation,
            invocation_id=invocation.invocation_id,
            build_id=observation.build_id,
            tested_sha=observation.tested_sha,
            execution_authorized=True,
            side_effect_state=ProviderSideEffectState.UNKNOWN,
        )

    if not observation.source_complete or observation.build_id is None or observation.tested_sha is None:
        return _result(
            status=ProviderStatus.UNAVAILABLE,
            reasons={ProviderReason.OBSERVATION_INCOMPLETE},
            invocation=invocation,
            invocation_id=invocation.invocation_id,
            build_id=observation.build_id,
            tested_sha=observation.tested_sha,
            execution_authorized=True,
            side_effect_state=observation.side_effect_state,
        )

    overall, reason = _overall_result(observation.terminal_status)
    try:
        evidence = normalize_cloud_build_evidence(
            build_id=observation.build_id,
            tested_sha=observation.tested_sha,
            repository=observation.repository,
            overall_result=overall,
            terminal=True,
            source_complete=observation.source_complete,
            invocation_id=invocation.invocation_id,
            failed_step=observation.failed_step,
            exit_code=observation.exit_code,
            observed_at=observation.observed_at,
        )
    except (TypeError, ValueError):
        return _result(
            status=ProviderStatus.MANUAL_REVIEW,
            reasons={ProviderReason.RESULT_AMBIGUOUS},
            invocation=invocation,
            invocation_id=invocation.invocation_id,
            build_id=observation.build_id,
            tested_sha=observation.tested_sha,
            execution_authorized=True,
            side_effect_state=observation.side_effect_state,
        )

    return _result(
        status=ProviderStatus.TERMINAL,
        reasons={reason},
        invocation=invocation,
        invocation_id=invocation.invocation_id,
        build_id=observation.build_id,
        tested_sha=observation.tested_sha,
        normalized_cloud_build_evidence=evidence,
        execution_authorized=True,
        side_effect_state=observation.side_effect_state,
    )


def _overall_result(status: ProviderObservationStatus) -> tuple[OverallResult, ProviderReason]:
    mapping = {
        ProviderObservationStatus.SUCCESS: (OverallResult.SUCCESS, ProviderReason.ACCEPTED),
        ProviderObservationStatus.FAILURE: (OverallResult.FAILURE, ProviderReason.PROVIDER_FAILURE),
        ProviderObservationStatus.TIMEOUT: (OverallResult.TIMEOUT, ProviderReason.PROVIDER_TIMEOUT),
        ProviderObservationStatus.CANCELLED: (OverallResult.CANCELLED, ProviderReason.PROVIDER_CANCELLED),
        ProviderObservationStatus.INTERNAL_ERROR: (OverallResult.INTERNAL_ERROR, ProviderReason.PROVIDER_INTERNAL_ERROR),
    }
    return mapping[status]


def _result(
    *,
    status: ProviderStatus,
    reasons: set[ProviderReason],
    invocation: CloudBuildProviderInvocation | None = None,
    invocation_id: str | None = None,
    build_id: str | None = None,
    tested_sha: str | None = None,
    normalized_cloud_build_evidence=None,
    execution_authorized: bool,
    side_effect_state: ProviderSideEffectState = ProviderSideEffectState.NONE,
) -> CloudBuildProviderResult:
    return CloudBuildProviderResult(
        schema_version=PROVIDER_SCHEMA_VERSION,
        status=status,
        invocation=invocation,
        invocation_id=invocation_id,
        build_id=build_id,
        tested_sha=tested_sha,
        reason_codes=tuple(sorted(reasons, key=lambda item: item.value)),
        normalized_cloud_build_evidence=normalized_cloud_build_evidence,
        execution_authorized=execution_authorized,
        side_effect_state=side_effect_state,
    )


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        return None
    return parsed
