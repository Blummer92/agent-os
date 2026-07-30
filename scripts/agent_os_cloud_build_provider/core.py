"""Pure provider preparation and observation projection for Cloud Build."""
from __future__ import annotations

from datetime import datetime, timezone

from agent_os_execution_service import (
    ExecutionAuthorizationEvidence,
    ExecutionServiceRequest,
    ValidationCommandPlan,
    execution_service_request_fingerprint,
    validate_execution_service_request,
    validation_command_plan_id,
)
from scripts.agent_os_remote_validation import DispatchDecision, dispatch_decision_id
from scripts.agent_os_cloud_build_reporting import OverallResult, normalize_cloud_build_evidence

from .models import (
    PROVIDER_SCHEMA_VERSION,
    CloudBuildProviderConfiguration,
    CloudBuildProviderInvocation,
    CloudBuildProviderObservation,
    CloudBuildProviderResult,
    ProviderCommandEntry,
    ProviderReason,
    ProviderResultStatus,
    ProviderStatus,
    SideEffectState,
    cloud_build_provider_configuration_fingerprint,
    command_argv_identity,
)


def _utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _result(*, status: ProviderResultStatus, reasons: set[ProviderReason], invocation: CloudBuildProviderInvocation | None = None,
            build_id: str | None = None, tested_sha: str | None = None, evidence: object | None = None,
            execution_authorized: bool = False, side_effect_state: SideEffectState = SideEffectState.NONE) -> CloudBuildProviderResult:
    return CloudBuildProviderResult(
        schema_version=PROVIDER_SCHEMA_VERSION,
        status=status,
        invocation=invocation,
        invocation_id=None if invocation is None else invocation.invocation_id,
        build_id=build_id,
        tested_sha=tested_sha,
        reason_codes=tuple(sorted(reasons, key=lambda item: item.value)),
        normalized_cloud_build_evidence=evidence,
        execution_authorized=execution_authorized,
        side_effect_state=side_effect_state,
    )


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
    if type(resolved_sha) is not str or type(evaluated_at) is not str:
        reasons.add(ProviderReason.INPUT_INVALID_TYPE)
    if reasons:
        return _result(status=ProviderResultStatus.MANUAL_REVIEW, reasons=reasons)

    assert isinstance(request, ExecutionServiceRequest)
    assert isinstance(command_plan, ValidationCommandPlan)
    assert isinstance(dispatch_decision, DispatchDecision)
    assert isinstance(authorization, ExecutionAuthorizationEvidence)
    assert isinstance(configuration, CloudBuildProviderConfiguration)
    assert isinstance(resolved_sha, str)
    assert isinstance(evaluated_at, str)

    try:
        request_reasons = validate_execution_service_request(request, evaluated_at=evaluated_at)
    except (TypeError, ValueError):
        request_reasons = ("invalid",)
    if request_reasons:
        reasons.add(ProviderReason.REQUEST_INVALID)
    try:
        if request.request_fingerprint != execution_service_request_fingerprint(request):
            reasons.add(ProviderReason.REQUEST_FINGERPRINT_MISMATCH)
    except (TypeError, ValueError):
        reasons.add(ProviderReason.REQUEST_FINGERPRINT_MISMATCH)
    try:
        plan_id = validation_command_plan_id(command_plan)
    except (TypeError, ValueError):
        plan_id = ""
        reasons.add(ProviderReason.COMMAND_PLAN_INVALID)
    try:
        decision_id = dispatch_decision_id(dispatch_decision)
    except (TypeError, ValueError):
        decision_id = ""
        reasons.add(ProviderReason.DISPATCH_INVALID)

    if reasons:
        return _result(status=ProviderResultStatus.MANUAL_REVIEW, reasons=reasons)

    launch_eligible = dispatch_decision.status == "launch-eligible" and dispatch_decision.launch_recommended is True
    if not launch_eligible:
        return _result(status=ProviderResultStatus.SKIPPED, reasons={ProviderReason.DISPATCH_NOT_LAUNCH_ELIGIBLE})

    repository = f"{request.repository_identity.owner}/{request.repository_identity.repository}"
    identities = (
        repository.casefold() == command_plan.repository.casefold() == str(dispatch_decision.repository).casefold() == authorization.repository.casefold(),
        request.requested_ref == command_plan.requested_ref,
        request.expected_sha == command_plan.expected_sha == dispatch_decision.head_sha == authorization.expected_sha,
        resolved_sha == request.expected_sha,
        request.request_fingerprint == command_plan.request_fingerprint == authorization.request_fingerprint,
        request.request_revision == command_plan.request_revision,
        command_plan.profile == dispatch_decision.profile,
        command_plan.selector_version == dispatch_decision.selector_version,
        command_plan.command_set_digest == dispatch_decision.command_set_digest,
        command_plan.validation_plan_id == dispatch_decision.plan_id,
        plan_id == authorization.command_plan_id,
        decision_id == dispatch_decision.decision_id,
    )
    mapped = (
        ProviderReason.IDENTITY_REPOSITORY_MISMATCH,
        ProviderReason.IDENTITY_REF_MISMATCH,
        ProviderReason.IDENTITY_EXPECTED_SHA_MISMATCH,
        ProviderReason.IDENTITY_RESOLVED_SHA_MISMATCH,
        ProviderReason.REQUEST_FINGERPRINT_MISMATCH,
        ProviderReason.COMMAND_PLAN_INVALID,
        ProviderReason.IDENTITY_PROFILE_MISMATCH,
        ProviderReason.DISPATCH_IDENTITY_MISMATCH,
        ProviderReason.IDENTITY_COMMAND_DIGEST_MISMATCH,
        ProviderReason.DISPATCH_IDENTITY_MISMATCH,
        ProviderReason.AUTHORIZATION_INVALID,
        ProviderReason.DISPATCH_INVALID,
    )
    for ok, reason in zip(identities, mapped):
        if not ok:
            reasons.add(reason)

    try:
        evaluated = _utc(evaluated_at)
        active = _utc(authorization.authorized_at) <= evaluated < _utc(authorization.expires_at)
    except (TypeError, ValueError):
        active = False
    if authorization.execution_authorized is not True:
        reasons.add(ProviderReason.AUTHORIZATION_NOT_GRANTED)
    if not active:
        reasons.add(ProviderReason.AUTHORIZATION_EXPIRED)
    try:
        cloud_build_provider_configuration_fingerprint(configuration)
    except (TypeError, ValueError):
        reasons.add(ProviderReason.PROVIDER_CONFIG_FINGERPRINT_MISMATCH)

    if reasons:
        return _result(status=ProviderResultStatus.MANUAL_REVIEW, reasons=reasons)

    entries = tuple(
        ProviderCommandEntry(operation=entry.operation.value, argv=tuple(entry.argv))
        for entry in command_plan.entries
    )
    invocation = CloudBuildProviderInvocation(
        schema_version=PROVIDER_SCHEMA_VERSION,
        request_id=request.request_id,
        request_revision=request.request_revision,
        request_fingerprint=request.request_fingerprint,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        command_plan_id=plan_id,
        validation_plan_id=command_plan.validation_plan_id,
        dispatch_decision_id=decision_id,
        dispatch_identity=str(dispatch_decision.dispatch_identity),
        authorization_id=authorization.authorization_id,
        repository=repository,
        requested_ref=request.requested_ref,
        expected_sha=request.expected_sha,
        resolved_sha=resolved_sha,
        profile=command_plan.profile,
        selector_version=command_plan.selector_version,
        command_set_digest=command_plan.command_set_digest,
        fixed_command_entries=entries,
        fixed_argv_identities=tuple(command_argv_identity(entry) for entry in entries),
        provider_configuration_fingerprint=configuration.configuration_fingerprint,
    )
    return _result(
        status=ProviderResultStatus.ACCEPTED,
        reasons={ProviderReason.ACCEPTED},
        invocation=invocation,
        execution_authorized=True,
    )


def project_cloud_build_provider_result(
    invocation: object,
    observation: object,
) -> CloudBuildProviderResult:
    if type(invocation) is not CloudBuildProviderInvocation or type(observation) is not CloudBuildProviderObservation:
        return _result(status=ProviderResultStatus.MANUAL_REVIEW, reasons={ProviderReason.INPUT_INVALID_TYPE})
    assert isinstance(invocation, CloudBuildProviderInvocation)
    assert isinstance(observation, CloudBuildProviderObservation)
    reasons: set[ProviderReason] = set()
    if observation.invocation_id != invocation.invocation_id:
        reasons.add(ProviderReason.OBSERVATION_INVOCATION_MISMATCH)
    if observation.repository.casefold() != invocation.repository.casefold():
        reasons.add(ProviderReason.OBSERVATION_REPOSITORY_MISMATCH)
    if observation.tested_sha is not None and observation.tested_sha != invocation.expected_sha:
        reasons.add(ProviderReason.OBSERVATION_TESTED_SHA_MISMATCH)
    if reasons:
        return _result(status=ProviderResultStatus.MANUAL_REVIEW, reasons=reasons, invocation=invocation,
                       execution_authorized=True, side_effect_state=observation.side_effect_state)

    if observation.provider_status is ProviderStatus.WORKING:
        return _result(status=ProviderResultStatus.UNAVAILABLE, reasons={ProviderReason.PROVIDER_NONTERMINAL},
                       invocation=invocation, build_id=observation.build_id, tested_sha=observation.tested_sha,
                       execution_authorized=True, side_effect_state=observation.side_effect_state)
    if observation.provider_status is ProviderStatus.UNKNOWN or observation.side_effect_state is SideEffectState.UNKNOWN:
        return _result(status=ProviderResultStatus.UNKNOWN, reasons={ProviderReason.PROVIDER_UNKNOWN_OUTCOME},
                       invocation=invocation, build_id=observation.build_id, tested_sha=observation.tested_sha,
                       execution_authorized=True, side_effect_state=SideEffectState.UNKNOWN)
    if observation.provider_status is ProviderStatus.UNAVAILABLE:
        return _result(status=ProviderResultStatus.UNAVAILABLE, reasons={ProviderReason.PROVIDER_UNAVAILABLE},
                       invocation=invocation, build_id=observation.build_id, tested_sha=observation.tested_sha,
                       execution_authorized=True, side_effect_state=observation.side_effect_state)

    status_map = {
        ProviderStatus.SUCCESS: OverallResult.SUCCESS,
        ProviderStatus.FAILURE: OverallResult.FAILURE,
        ProviderStatus.TIMEOUT: OverallResult.TIMEOUT,
        ProviderStatus.CANCELLED: OverallResult.CANCELLED,
        ProviderStatus.INTERNAL_ERROR: OverallResult.INTERNAL_ERROR,
    }
    overall = status_map.get(observation.provider_status)
    if overall is None or not observation.source_complete or observation.build_id is None or observation.tested_sha is None:
        return _result(status=ProviderResultStatus.MANUAL_REVIEW, reasons={ProviderReason.OBSERVATION_INVALID},
                       invocation=invocation, execution_authorized=True, side_effect_state=observation.side_effect_state)
    try:
        evidence = normalize_cloud_build_evidence(
            build_id=observation.build_id,
            tested_sha=observation.tested_sha,
            repository=observation.repository,
            overall_result=overall,
            terminal=True,
            source_complete=True,
            invocation_id=invocation.invocation_id,
            failed_step=observation.failed_step,
            exit_code=observation.exit_code,
            observed_at=observation.observed_at,
        )
    except (TypeError, ValueError):
        return _result(status=ProviderResultStatus.MANUAL_REVIEW, reasons={ProviderReason.OBSERVATION_INVALID},
                       invocation=invocation, execution_authorized=True, side_effect_state=observation.side_effect_state)
    reason = {
        ProviderStatus.SUCCESS: ProviderReason.ACCEPTED,
        ProviderStatus.FAILURE: ProviderReason.PROVIDER_FAILURE,
        ProviderStatus.TIMEOUT: ProviderReason.PROVIDER_TIMEOUT,
        ProviderStatus.CANCELLED: ProviderReason.PROVIDER_CANCELLED,
        ProviderStatus.INTERNAL_ERROR: ProviderReason.PROVIDER_INTERNAL_ERROR,
    }[observation.provider_status]
    return _result(status=ProviderResultStatus.TERMINAL, reasons={reason}, invocation=invocation,
                   build_id=observation.build_id, tested_sha=observation.tested_sha, evidence=evidence,
                   execution_authorized=True, side_effect_state=observation.side_effect_state)
