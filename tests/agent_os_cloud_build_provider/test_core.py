from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SHA = "a" * 40
DIGEST = "b" * 64


class Operation(str, Enum):
    VALIDATION_AGGREGATE = "validation.aggregate"


@dataclass(frozen=True)
class Entry:
    operation: Operation
    argv: tuple[str, ...]


@dataclass(frozen=True)
class Request:
    request_id: str = "req-804"
    request_revision: int = 1
    request_fingerprint: str = DIGEST
    issue_or_handoff_identity: str = "issue:804"
    requested_ref: str = "agent/804-cloud-build-provider-contract"
    expected_sha: str = SHA
    repository_identity: object = field(default_factory=lambda: SimpleNamespace(owner="Blummer92", repository="agent-os"))


@dataclass(frozen=True)
class Plan:
    repository: str = "Blummer92/agent-os"
    requested_ref: str = "agent/804-cloud-build-provider-contract"
    expected_sha: str = SHA
    request_revision: int = 1
    request_fingerprint: str = DIGEST
    validation_plan_id: str = "validation-plan:" + DIGEST
    selector_version: str = "1.0"
    profile: str = "aggregate"
    command_set_digest: str = DIGEST
    entries: tuple[Entry, ...] = (Entry(Operation.VALIDATION_AGGREGATE, ("python", "-m", "pytest")),)


@dataclass(frozen=True)
class Decision:
    status: str = "launch-eligible"
    launch_recommended: bool = True
    repository: str = "Blummer92/agent-os"
    head_sha: str = SHA
    profile: str = "aggregate"
    selector_version: str = "1.0"
    command_set_digest: str = DIGEST
    plan_id: str = "validation-plan:" + DIGEST
    decision_id: str = "decision:" + DIGEST
    dispatch_identity: str = "dispatch:" + DIGEST


@dataclass(frozen=True)
class Authorization:
    authorization_id: str = "auth-804"
    request_fingerprint: str = DIGEST
    command_plan_id: str = "command-plan:" + DIGEST
    repository: str = "Blummer92/agent-os"
    expected_sha: str = SHA
    authorized_at: str = "2026-07-30T19:00:00Z"
    expires_at: str = "2026-07-30T22:00:00Z"
    execution_authorized: bool = True


def _install_stubs() -> None:
    execution = ModuleType("agent_os_execution_service")
    execution.ExecutionAuthorizationEvidence = Authorization
    execution.ExecutionServiceRequest = Request
    execution.ValidationCommandPlan = Plan
    execution.execution_service_request_fingerprint = lambda value: value.request_fingerprint
    execution.validate_execution_service_request = lambda value, evaluated_at: ()
    execution.validation_command_plan_id = lambda value: "command-plan:" + DIGEST
    remote = ModuleType("scripts.agent_os_remote_validation")
    remote.DispatchDecision = Decision
    remote.dispatch_decision_id = lambda value: value.decision_id
    reporting = ModuleType("scripts.agent_os_cloud_build_reporting")

    class Overall(str, Enum):
        SUCCESS = "success"
        FAILURE = "failure"
        TIMEOUT = "timeout"
        CANCELLED = "cancelled"
        INTERNAL_ERROR = "internal-error"

    reporting.OverallResult = Overall
    reporting.normalize_cloud_build_evidence = lambda **kwargs: SimpleNamespace(**kwargs)
    sys.modules["agent_os_execution_service"] = execution
    sys.modules["scripts.agent_os_remote_validation"] = remote
    sys.modules["scripts.agent_os_cloud_build_reporting"] = reporting


_install_stubs()
provider = importlib.import_module("scripts.agent_os_cloud_build_provider")


def configuration():
    return provider.CloudBuildProviderConfiguration(
        schema_version="1.0",
        project_id="agent-os-502614",
        location="us-central1",
        runtime_service_account_identity="runtime@example.iam",
        build_service_account_identity="build@example.iam",
        build_definition_identity="build-definition:v1",
        builder_image_identity="us-docker.pkg.dev/project/repo/validator@sha256:" + "c" * 64,
        validator_dependency_identity="requirements-lock:" + DIGEST,
        evidence_destination_identity="gs://agent-os-evidence/provider",
        max_build_timeout_seconds=1800,
        max_output_bytes=100000,
        max_diagnostic_bytes=4096,
    )


def accepted():
    return provider.prepare_cloud_build_provider_invocation(
        Request(),
        Plan(),
        Decision(),
        Authorization(),
        configuration(),
        resolved_sha=SHA,
        evaluated_at="2026-07-30T20:00:00Z",
    )


def test_valid_invocation_is_deterministic_and_non_authorizing():
    first = accepted()
    second = accepted()
    assert first.status is provider.ProviderResultStatus.ACCEPTED
    assert first.result_id == second.result_id
    assert first.invocation.invocation_id == second.invocation.invocation_id
    assert first.merge_authorized is False
    assert first.invocation.merge_authorized is False
    assert first.invocation.side_effects_performed is False


@pytest.mark.parametrize(
    "decision",
    [
        Decision(status="stale-skipped", launch_recommended=False),
        Decision(status="duplicate-no-op", launch_recommended=False),
        Decision(status="reused", launch_recommended=False),
        Decision(status="supersede-required", launch_recommended=False),
        Decision(status="manual-review", launch_recommended=False),
    ],
)
def test_non_launch_decisions_create_no_invocation(decision):
    result = provider.prepare_cloud_build_provider_invocation(
        Request(),
        Plan(),
        decision,
        Authorization(),
        configuration(),
        resolved_sha=SHA,
        evaluated_at="2026-07-30T20:00:00Z",
    )
    assert result.status is provider.ProviderResultStatus.SKIPPED
    assert result.invocation is None


def test_sha_and_authorization_fail_closed():
    wrong = provider.prepare_cloud_build_provider_invocation(
        Request(),
        Plan(),
        Decision(),
        Authorization(execution_authorized=False),
        configuration(),
        resolved_sha="d" * 40,
        evaluated_at="2026-07-30T20:00:00Z",
    )
    assert wrong.status is provider.ProviderResultStatus.MANUAL_REVIEW
    assert provider.ProviderReason.AUTHORIZATION_NOT_GRANTED in wrong.reason_codes
    assert provider.ProviderReason.IDENTITY_RESOLVED_SHA_MISMATCH in wrong.reason_codes


def test_boolean_and_mutable_builder_are_rejected():
    with pytest.raises(ValueError):
        provider.CloudBuildProviderConfiguration(
            schema_version="1.0",
            project_id="p",
            location="l",
            runtime_service_account_identity="r",
            build_service_account_identity="b",
            build_definition_identity="d",
            builder_image_identity="python:3.11",
            validator_dependency_identity="v",
            evidence_destination_identity="e",
            max_build_timeout_seconds=True,
            max_output_bytes=1,
            max_diagnostic_bytes=1,
        )


def test_unknown_outcome_is_explicit_and_non_retryable():
    invocation = accepted().invocation
    observation = provider.CloudBuildProviderObservation(
        schema_version="1.0",
        invocation_id=invocation.invocation_id,
        build_id=None,
        repository=invocation.repository,
        tested_sha=None,
        provider_status=provider.ProviderStatus.UNKNOWN,
        failed_step=None,
        exit_code=None,
        observed_at="2026-07-30T20:01:00Z",
        source_complete=False,
        side_effect_state=provider.SideEffectState.UNKNOWN,
    )
    result = provider.project_cloud_build_provider_result(invocation, observation)
    assert result.status is provider.ProviderResultStatus.UNKNOWN
    assert result.side_effect_state is provider.SideEffectState.UNKNOWN


def test_terminal_success_reuses_reporting_evidence():
    invocation = accepted().invocation
    observation = provider.CloudBuildProviderObservation(
        schema_version="1.0",
        invocation_id=invocation.invocation_id,
        build_id="build-1",
        repository=invocation.repository,
        tested_sha=SHA,
        provider_status=provider.ProviderStatus.SUCCESS,
        failed_step="none",
        exit_code=0,
        observed_at="2026-07-30T20:02:00Z",
        source_complete=True,
        side_effect_state=provider.SideEffectState.CONFIRMED,
    )
    result = provider.project_cloud_build_provider_result(invocation, observation)
    assert result.status is provider.ProviderResultStatus.TERMINAL
    assert result.normalized_cloud_build_evidence.build_id == "build-1"
    assert result.merge_authorized is False


def test_control_characters_and_secrets_are_rejected():
    with pytest.raises(ValueError):
        provider.CloudBuildProviderConfiguration(
            schema_version="1.0",
            project_id="authorization: token",
            location="l",
            runtime_service_account_identity="r",
            build_service_account_identity="b",
            build_definition_identity="d",
            builder_image_identity="x@sha256:" + "c" * 64,
            validator_dependency_identity="v",
            evidence_destination_identity="e",
            max_build_timeout_seconds=1,
            max_output_bytes=1,
            max_diagnostic_bytes=1,
        )


def test_public_surface_has_no_command_or_shell_input():
    import inspect

    parameters = inspect.signature(provider.prepare_cloud_build_provider_invocation).parameters
    assert "command" not in parameters
    assert "argv" not in parameters
    assert "shell" not in parameters
