from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = ROOT / "08_Tooling/agent-os-execution-service/src"
for path in (ROOT, EXECUTION_SERVICE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_os_execution_service import (  # noqa: E402
    EvidenceVisibilityPolicy,
    ExecutionAuthorizationEvidence,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceRequest,
    build_validation_command_plan,
    validation_command_plan_id,
)
from scripts.agent_os_cloud_build_provider import (  # noqa: E402
    CloudBuildProviderConfiguration,
    CloudBuildProviderObservation,
    ProviderReason,
    ProviderResultStatus,
    ProviderStatus,
    SideEffectState,
    prepare_cloud_build_provider_invocation,
    project_cloud_build_provider_result,
)
from scripts.agent_os_execution_capabilities import RepositoryIdentity  # noqa: E402
from scripts.agent_os_remote_validation import (  # noqa: E402
    DispatchEvidence,
    ValidationPlan,
    compute_command_set_digest,
    evaluate_dispatch_decision,
)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
OTHER_SHA = "c" * 40
DIGEST = "d" * 64
BRANCH = "agent/804-cloud-build-provider-contract"
EVALUATED_AT = "2026-07-30T20:00:00Z"


def _request(**changes: object) -> ExecutionServiceRequest:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": "req-804",
        "request_revision": 1,
        "created_at": "2026-07-30T19:00:00Z",
        "expires_at": "2026-07-30T22:00:00Z",
        "repository_identity": RepositoryIdentity(
            host="github.com", owner="Blummer92", repository="agent-os"
        ),
        "issue_or_handoff_identity": "issue:804",
        "canonical_owner": "github-service-agent",
        "requesting_actor": "blummer92",
        "capability": ExecutionServiceCapability.VERIFY_REPOSITORY_STATE,
        "base_branch": "main",
        "base_sha": BASE_SHA,
        "requested_ref": BRANCH,
        "expected_sha": HEAD_SHA,
        "allowed_paths": (
            "scripts/agent_os_cloud_build_provider",
            "tests/agent_os_cloud_build_provider",
        ),
        "forbidden_paths": (".github/workflows",),
        "inspected_file_count_limit": 64,
        "inspected_byte_limit": 1_000_000,
        "evidence_visibility_policy": EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        "invalidation_conditions": (
            ExecutionServiceInvalidationCondition.EXPECTED_SHA_CHANGED,
        ),
    }
    values.update(changes)
    return ExecutionServiceRequest(**values)  # type: ignore[arg-type]


def _validation_plan(**changes: object) -> ValidationPlan:
    commands = ("python -m pytest",)
    values: dict[str, object] = {
        "selector_version": "1.0.0",
        "repository": "Blummer92/agent-os",
        "pull_request": 804,
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "profile": "aggregate",
        "commands": commands,
        "command_set_digest": compute_command_set_digest("1.0.0", commands),
        "reason_codes": ("profile.aggregate-configuration",),
        "remote_build_required": True,
    }
    values.update(changes)
    return ValidationPlan(**values)  # type: ignore[arg-type]


def _inputs():
    request = _request()
    validation_plan = _validation_plan()
    command_plan = build_validation_command_plan(
        request, validation_plan, evaluated_at=EVALUATED_AT
    )
    decision = evaluate_dispatch_decision(
        validation_plan, (), current_pr_head_sha=HEAD_SHA
    )
    authorization = ExecutionAuthorizationEvidence(
        authorization_id="auth-804",
        request_fingerprint=request.request_fingerprint,
        command_plan_id=validation_command_plan_id(command_plan),
        repository=command_plan.repository,
        expected_sha=command_plan.expected_sha,
        authorized_at="2026-07-30T19:30:00Z",
        expires_at="2026-07-30T21:00:00Z",
        execution_authorized=True,
    )
    return request, validation_plan, command_plan, decision, authorization


def _configuration(**changes: object) -> CloudBuildProviderConfiguration:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "project_id": "agent-os-502614",
        "location": "us-central1",
        "runtime_service_account_identity": "runtime@example.iam",
        "build_service_account_identity": "build@example.iam",
        "build_definition_identity": "build-definition:v1",
        "builder_image_identity": (
            "us-docker.pkg.dev/project/repo/validator@sha256:" + "e" * 64
        ),
        "validator_dependency_identity": "requirements-lock:" + DIGEST,
        "evidence_destination_identity": "gs://agent-os-evidence/provider",
        "max_build_timeout_seconds": 1800,
        "max_output_bytes": 100_000,
        "max_diagnostic_bytes": 4096,
    }
    values.update(changes)
    return CloudBuildProviderConfiguration(**values)  # type: ignore[arg-type]


def _accepted():
    request, _, command_plan, decision, authorization = _inputs()
    return prepare_cloud_build_provider_invocation(
        request,
        command_plan,
        decision,
        authorization,
        _configuration(),
        resolved_sha=HEAD_SHA,
        evaluated_at=EVALUATED_AT,
    )


def test_valid_invocation_is_deterministic_and_non_authorizing() -> None:
    first = _accepted()
    second = _accepted()
    assert first.status is ProviderResultStatus.ACCEPTED
    assert first.result_id == second.result_id
    assert first.invocation is not None
    assert second.invocation is not None
    assert first.invocation.invocation_id == second.invocation.invocation_id
    assert first.merge_authorized is False
    assert first.invocation.merge_authorized is False
    assert first.invocation.side_effects_performed is False


def test_canonical_nonlaunch_decisions_create_no_invocation() -> None:
    request, plan, command_plan, _, authorization = _inputs()
    decisions = (
        evaluate_dispatch_decision(plan, (), current_pr_head_sha=OTHER_SHA),
        evaluate_dispatch_decision(
            plan,
            (DispatchEvidence(record_id="active", validation_plan=plan, attempt=0, state="active"),),
            current_pr_head_sha=HEAD_SHA,
        ),
        evaluate_dispatch_decision(
            plan,
            (DispatchEvidence(record_id="passed", validation_plan=plan, attempt=0, state="succeeded"),),
            current_pr_head_sha=HEAD_SHA,
        ),
        evaluate_dispatch_decision(
            plan,
            (
                DispatchEvidence(
                    record_id="other-active",
                    validation_plan=replace(plan, head_sha=OTHER_SHA),
                    attempt=0,
                    state="active",
                ),
            ),
            current_pr_head_sha=HEAD_SHA,
        ),
    )
    assert {item.status for item in decisions} == {
        "stale-skipped",
        "duplicate-no-op",
        "reused",
        "supersede-required",
    }
    for decision in decisions:
        result = prepare_cloud_build_provider_invocation(
            request,
            command_plan,
            decision,
            authorization,
            _configuration(),
            resolved_sha=HEAD_SHA,
            evaluated_at=EVALUATED_AT,
        )
        assert result.status is ProviderResultStatus.SKIPPED
        assert result.invocation is None


def test_malformed_dispatch_identity_fails_closed() -> None:
    request, _, command_plan, decision, authorization = _inputs()
    malformed = replace(decision, decision_id="validation-dispatch-decision:" + "0" * 64)
    result = prepare_cloud_build_provider_invocation(
        request,
        command_plan,
        malformed,
        authorization,
        _configuration(),
        resolved_sha=HEAD_SHA,
        evaluated_at=EVALUATED_AT,
    )
    assert result.status is ProviderResultStatus.MANUAL_REVIEW
    assert ProviderReason.DISPATCH_INVALID in result.reason_codes
    assert result.invocation is None


def test_sha_and_authorization_fail_closed() -> None:
    request, _, command_plan, decision, authorization = _inputs()
    result = prepare_cloud_build_provider_invocation(
        request,
        command_plan,
        decision,
        replace(authorization, execution_authorized=False),
        _configuration(),
        resolved_sha=OTHER_SHA,
        evaluated_at=EVALUATED_AT,
    )
    assert result.status is ProviderResultStatus.MANUAL_REVIEW
    assert ProviderReason.AUTHORIZATION_NOT_GRANTED in result.reason_codes
    assert ProviderReason.IDENTITY_RESOLVED_SHA_MISMATCH in result.reason_codes


def test_boolean_and_mutable_builder_are_rejected() -> None:
    with pytest.raises(ValueError):
        _configuration(max_build_timeout_seconds=True)
    with pytest.raises(ValueError):
        _configuration(builder_image_identity="python:3.11")


def test_unknown_outcome_is_explicit_and_non_retryable() -> None:
    invocation = _accepted().invocation
    assert invocation is not None
    observation = CloudBuildProviderObservation(
        schema_version="1.0",
        invocation_id=invocation.invocation_id,
        build_id=None,
        repository=invocation.repository,
        tested_sha=None,
        provider_status=ProviderStatus.UNKNOWN,
        failed_step=None,
        exit_code=None,
        observed_at="2026-07-30T20:01:00Z",
        source_complete=False,
        side_effect_state=SideEffectState.UNKNOWN,
    )
    result = project_cloud_build_provider_result(invocation, observation)
    assert result.status is ProviderResultStatus.UNKNOWN
    assert result.side_effect_state is SideEffectState.UNKNOWN
    assert result.reason_codes == (ProviderReason.PROVIDER_UNKNOWN_OUTCOME,)


def test_terminal_success_reuses_reporting_evidence() -> None:
    from scripts.agent_os_cloud_build_reporting import CloudBuildResultEvidence

    invocation = _accepted().invocation
    assert invocation is not None
    observation = CloudBuildProviderObservation(
        schema_version="1.0",
        invocation_id=invocation.invocation_id,
        build_id="build-1",
        repository=invocation.repository,
        tested_sha=HEAD_SHA,
        provider_status=ProviderStatus.SUCCESS,
        failed_step="none",
        exit_code=0,
        observed_at="2026-07-30T20:02:00Z",
        source_complete=True,
        side_effect_state=SideEffectState.CONFIRMED,
    )
    result = project_cloud_build_provider_result(invocation, observation)
    assert result.status is ProviderResultStatus.TERMINAL
    assert type(result.normalized_cloud_build_evidence) is CloudBuildResultEvidence
    assert result.normalized_cloud_build_evidence.build_id == "build-1"
    assert result.reason_codes == (ProviderReason.ACCEPTED,)
    assert result.merge_authorized is False


def test_observation_identity_drift_fails_closed() -> None:
    invocation = _accepted().invocation
    assert invocation is not None
    observation = CloudBuildProviderObservation(
        schema_version="1.0",
        invocation_id=invocation.invocation_id,
        build_id="build-2",
        repository=invocation.repository,
        tested_sha=OTHER_SHA,
        provider_status=ProviderStatus.SUCCESS,
        failed_step="none",
        exit_code=0,
        observed_at="2026-07-30T20:03:00Z",
        source_complete=True,
        side_effect_state=SideEffectState.CONFIRMED,
    )
    result = project_cloud_build_provider_result(invocation, observation)
    assert result.status is ProviderResultStatus.MANUAL_REVIEW
    assert ProviderReason.OBSERVATION_TESTED_SHA_MISMATCH in result.reason_codes


def test_controls_secrets_and_unbounded_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        _configuration(project_id="authorization: token")
    with pytest.raises(ValueError):
        _configuration(location="us-central1\nsecret")
    with pytest.raises(ValueError):
        _configuration(max_output_bytes=10_000_001)


def test_public_surface_has_no_shell_or_arbitrary_argv_input() -> None:
    parameters = inspect.signature(prepare_cloud_build_provider_invocation).parameters
    assert "command" not in parameters
    assert "argv" not in parameters
    assert "shell" not in parameters
