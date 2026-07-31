from dataclasses import replace
from pathlib import Path
import inspect
import sys

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_TOOLING_SOURCE_DIRS = (
    _REPO_ROOT
    / "08_Tooling"
    / "agent-os-execution-service"
    / "src",
    _REPO_ROOT
    / "08_Tooling"
    / "workflow-scheduler"
    / "src",
)

for source_dir in reversed(_TOOLING_SOURCE_DIRS):
    source_text = str(source_dir)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)

from agent_os_execution_service import (
    COMMAND_PLAN_SCHEMA_VERSION,
    COMMAND_REGISTRY_VERSION,
    CommandOperation,
    CommandPlanEntry,
    EvidenceVisibilityPolicy,
    ExecutionAuthorizationEvidence,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceRequest,
    ValidationCommandPlan,
    validation_command_plan_id,
)
from scripts.agent_os_cloud_build_provider import (
    CloudBuildProviderConfiguration,
    CloudBuildProviderObservation,
    CloudBuildProviderResult,
    ProviderObservationStatus,
    ProviderReason,
    ProviderSideEffectState,
    ProviderStatus,
    cloud_build_provider_invocation_id,
    cloud_build_provider_result_id,
    prepare_cloud_build_provider_invocation,
    project_cloud_build_provider_result,
    serialize_cloud_build_provider_configuration,
    serialize_cloud_build_provider_invocation,
    serialize_cloud_build_provider_result,
)
from scripts.agent_os_execution_capabilities import RepositoryIdentity
from scripts.agent_os_remote_validation import (
    ValidationPlan,
    compute_command_set_digest,
    evaluate_dispatch_decision,
    validation_plan_id,
)

SHA = "a" * 40
BASE_SHA = "b" * 40
COMMAND = "python -m pytest"
SELECTOR_VERSION = "1.0.0"
DIGEST = compute_command_set_digest(SELECTOR_VERSION, (COMMAND,))


def _request(*, expires_at="2026-07-31T00:00:00Z"):
    return ExecutionServiceRequest(
        schema_version="1.0",
        request_id="request:804",
        request_revision=1,
        created_at="2026-07-30T19:00:00Z",
        expires_at=expires_at,
        repository_identity=RepositoryIdentity(
            host="github.com", owner="blummer92", repository="agent-os"
        ),
        issue_or_handoff_identity="issue:804",
        canonical_owner="github-service-agent",
        requesting_actor="repository-owner",
        capability=ExecutionServiceCapability.INSPECT_REPOSITORY,
        base_branch="main",
        base_sha=BASE_SHA,
        requested_ref="agent/804-cloud-build-provider-core",
        expected_sha=SHA,
        allowed_paths=("scripts/agent_os_cloud_build_provider",),
        forbidden_paths=(".github/workflows",),
        inspected_file_count_limit=256,
        inspected_byte_limit=1_000_000,
        evidence_visibility_policy=EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        invalidation_conditions=(
            ExecutionServiceInvalidationCondition.EXPECTED_SHA_CHANGED,
            ExecutionServiceInvalidationCondition.REQUEST_EXPIRED,
        ),
    )


def _plan():
    return ValidationPlan(
        selector_version=SELECTOR_VERSION,
        repository="Blummer92/agent-os",
        pull_request=804,
        base_sha=BASE_SHA,
        head_sha=SHA,
        profile="aggregate",
        commands=(COMMAND,),
        command_set_digest=DIGEST,
        reason_codes=("profile.aggregate-configuration",),
        remote_build_required=True,
    )


def _command_plan(request, plan):
    return ValidationCommandPlan(
        schema_version=COMMAND_PLAN_SCHEMA_VERSION,
        registry_version=COMMAND_REGISTRY_VERSION,
        repository=plan.repository,
        issue_or_handoff_identity=request.issue_or_handoff_identity,
        requested_ref=request.requested_ref,
        expected_sha=request.expected_sha,
        request_revision=request.request_revision,
        request_fingerprint=request.request_fingerprint,
        validation_plan_id=validation_plan_id(plan),
        validation_plan_schema_version="1.0",
        selector_version=plan.selector_version,
        profile=plan.profile,
        command_set_digest=plan.command_set_digest,
        entries=(
            CommandPlanEntry(
                operation=CommandOperation.VALIDATION_AGGREGATE,
                argv=("python", "-m", "pytest"),
            ),
        ),
    )


def _configuration():
    return CloudBuildProviderConfiguration(
        project_id="agent-os-502614",
        location="global",
        runtime_service_account_identity=(
            "agent-os-gateway@agent-os-502614.iam.gserviceaccount.com"
        ),
        build_service_account_identity=(
            "agent-os-build@agent-os-502614.iam.gserviceaccount.com"
        ),
        build_definition_identity="cloudbuild:validation:v1",
        builder_image_identity="python@sha256:" + "c" * 64,
        validator_dependency_identity="requirements-dev:sha256:" + "d" * 64,
        evidence_destination_identity="gs://agent-os-evidence/runs",
        max_build_timeout_seconds=900,
        max_output_bytes=1_000_000,
        max_diagnostic_bytes=16_384,
    )


def _authorization(request, command_plan, *, granted=True):
    return ExecutionAuthorizationEvidence(
        authorization_id="authorization:804",
        request_fingerprint=request.request_fingerprint,
        command_plan_id=validation_command_plan_id(command_plan),
        repository="Blummer92/agent-os",
        expected_sha=request.expected_sha,
        authorized_at="2026-07-30T19:30:00Z",
        expires_at="2026-07-30T23:00:00Z",
        execution_authorized=granted,
    )


def _inputs():
    request = _request()
    plan = _plan()
    command_plan = _command_plan(request, plan)
    dispatch = evaluate_dispatch_decision(plan, (), current_pr_head_sha=SHA)
    return (
        request,
        command_plan,
        dispatch,
        _authorization(request, command_plan),
        _configuration(),
    )


def _accepted():
    result = prepare_cloud_build_provider_invocation(
        *_inputs(), resolved_sha=SHA, evaluated_at="2026-07-30T20:00:00Z"
    )
    assert result.status is ProviderStatus.ACCEPTED
    assert result.invocation is not None
    return result


def test_valid_invocation_is_deterministic_and_non_authorizing_for_merge():
    left = _accepted()
    right = _accepted()
    assert left == right
    assert left.invocation_id == right.invocation_id
    assert left.result_id == right.result_id
    assert left.execution_authorized is True
    assert left.merge_authorized is False
    assert left.invocation.merge_authorized is False
    assert left.invocation.side_effects_performed is False
    assert left.invocation.authorization_id == "authorization:804"
    assert cloud_build_provider_invocation_id(left.invocation) == left.invocation_id
    assert cloud_build_provider_result_id(left) == left.result_id


def test_configuration_is_bounded_secret_safe_and_digest_pinned():
    with pytest.raises(ValueError):
        replace(_configuration(), builder_image_identity="python:3.11")
    for secret_like in (
        "Authorization: Bearer abcdefgh",
        "Bearer abcdefgh",
        "token=secret-value",
        "password=secret-value",
        "secret=secret-value",
    ):
        with pytest.raises(ValueError):
            replace(_configuration(), evidence_destination_identity=secret_like)
    with pytest.raises(TypeError):
        replace(_configuration(), max_output_bytes=True)


def test_canonical_serialization_is_stable():
    accepted = _accepted()
    config_payload = serialize_cloud_build_provider_configuration(_configuration())
    invocation_payload = serialize_cloud_build_provider_invocation(accepted.invocation)
    result_payload = serialize_cloud_build_provider_result(accepted)
    assert config_payload == serialize_cloud_build_provider_configuration(_configuration())
    assert invocation_payload["invocation_id"] == accepted.invocation_id
    assert result_payload["result_id"] == accepted.result_id
    assert result_payload["merge_authorized"] is False


@pytest.mark.parametrize(
    "mutation, reason",
    [
        ("expired", ProviderReason.REQUEST_EXPIRED),
        ("denied", ProviderReason.AUTHORIZATION_NOT_GRANTED),
        ("auth-sha", ProviderReason.AUTHORIZATION_MISMATCH),
        ("ref", ProviderReason.REQUESTED_REF_MISMATCH),
        ("repository", ProviderReason.REPOSITORY_MISMATCH),
        ("resolved-sha", ProviderReason.RESOLVED_SHA_MISMATCH),
    ],
)
def test_identity_and_authorization_drift_fails_closed(mutation, reason):
    request, command_plan, dispatch, authorization, configuration = _inputs()
    resolved_sha = SHA
    if mutation == "expired":
        request = _request(expires_at="2026-07-30T19:59:59Z")
    elif mutation == "denied":
        authorization = replace(authorization, execution_authorized=False)
    elif mutation == "auth-sha":
        authorization = replace(authorization, expected_sha="e" * 40)
    elif mutation == "ref":
        command_plan = replace(command_plan, requested_ref="other/ref")
    elif mutation == "repository":
        dispatch = replace(dispatch, repository="other/repo")
    else:
        resolved_sha = "f" * 40
    result = prepare_cloud_build_provider_invocation(
        request,
        command_plan,
        dispatch,
        authorization,
        configuration,
        resolved_sha=resolved_sha,
        evaluated_at="2026-07-30T20:00:00Z",
    )
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert reason in result.reason_codes
    assert result.invocation is None
    assert result.merge_authorized is False


def test_non_launch_dispatch_creates_no_invocation():
    request = _request()
    plan = _plan()
    command_plan = _command_plan(request, plan)
    dispatch = evaluate_dispatch_decision(
        plan,
        (),
        current_pr_head_sha="c" * 40,
    )
    result = prepare_cloud_build_provider_invocation(
        request,
        command_plan,
        dispatch,
        _authorization(request, command_plan),
        _configuration(),
        resolved_sha=SHA,
        evaluated_at="2026-07-30T20:00:00Z",
    )
    assert dispatch.status == "stale-skipped"
    assert result.status is ProviderStatus.SKIPPED
    assert ProviderReason.DISPATCH_NON_LAUNCH in result.reason_codes
    assert result.invocation is None
    assert result.merge_authorized is False
    assert result.side_effect_state is ProviderSideEffectState.NONE


@pytest.mark.parametrize(
    "observed, expected, reason",
    [
        (ProviderObservationStatus.WORKING, ProviderStatus.UNAVAILABLE, ProviderReason.OBSERVATION_NONTERMINAL),
        (ProviderObservationStatus.UNAVAILABLE, ProviderStatus.UNAVAILABLE, ProviderReason.OBSERVATION_UNAVAILABLE),
        (ProviderObservationStatus.UNKNOWN, ProviderStatus.UNKNOWN, ProviderReason.OBSERVATION_UNKNOWN),
        (ProviderObservationStatus.SUCCESS, ProviderStatus.TERMINAL, ProviderReason.ACCEPTED),
        (ProviderObservationStatus.FAILURE, ProviderStatus.TERMINAL, ProviderReason.PROVIDER_FAILURE),
        (ProviderObservationStatus.TIMEOUT, ProviderStatus.TERMINAL, ProviderReason.PROVIDER_TIMEOUT),
        (ProviderObservationStatus.CANCELLED, ProviderStatus.TERMINAL, ProviderReason.PROVIDER_CANCELLED),
        (ProviderObservationStatus.INTERNAL_ERROR, ProviderStatus.TERMINAL, ProviderReason.PROVIDER_INTERNAL_ERROR),
    ],
)
def test_provider_observation_projection(observed, expected, reason):
    invocation = _accepted().invocation
    incomplete = observed in {
        ProviderObservationStatus.WORKING,
        ProviderObservationStatus.UNAVAILABLE,
        ProviderObservationStatus.UNKNOWN,
    }
    observation = CloudBuildProviderObservation(
        invocation_id=invocation.invocation_id,
        build_id=None if observed is ProviderObservationStatus.UNAVAILABLE else "build:804",
        repository=invocation.repository,
        tested_sha=None if incomplete else invocation.resolved_sha,
        terminal_status=observed,
        failed_step="none" if observed is ProviderObservationStatus.SUCCESS else None,
        exit_code=0 if observed is ProviderObservationStatus.SUCCESS else None,
        observed_at="2026-07-30T20:10:00Z",
        source_complete=not incomplete,
        side_effect_state=(
            ProviderSideEffectState.UNKNOWN
            if observed is ProviderObservationStatus.UNKNOWN
            else ProviderSideEffectState.CONFIRMED
        ),
    )
    result = project_cloud_build_provider_result(invocation, observation)
    assert result.status is expected
    assert reason in result.reason_codes
    assert result.merge_authorized is False
    if expected is ProviderStatus.TERMINAL:
        assert result.normalized_cloud_build_evidence is not None
        assert result.normalized_cloud_build_evidence.invocation_id == invocation.invocation_id
    if expected is ProviderStatus.UNKNOWN:
        assert result.side_effect_state is ProviderSideEffectState.UNKNOWN


def test_observation_mismatch_and_incomplete_result_do_not_fabricate_evidence():
    invocation = _accepted().invocation
    observation = CloudBuildProviderObservation(
        invocation_id="other:invocation",
        build_id="build:804",
        repository=invocation.repository,
        tested_sha=invocation.resolved_sha,
        terminal_status=ProviderObservationStatus.SUCCESS,
        failed_step="none",
        exit_code=0,
        observed_at="2026-07-30T20:10:00Z",
        source_complete=True,
        side_effect_state=ProviderSideEffectState.CONFIRMED,
    )
    mismatch = project_cloud_build_provider_result(invocation, observation)
    assert mismatch.status is ProviderStatus.MANUAL_REVIEW
    assert ProviderReason.OBSERVATION_INVOCATION_MISMATCH in mismatch.reason_codes
    assert mismatch.normalized_cloud_build_evidence is None

    incomplete = replace(
        observation,
        invocation_id=invocation.invocation_id,
        build_id=None,
        tested_sha=None,
        source_complete=False,
    )
    unavailable = project_cloud_build_provider_result(invocation, incomplete)
    assert unavailable.status is ProviderStatus.UNAVAILABLE
    assert unavailable.build_id is None
    assert unavailable.tested_sha is None
    assert unavailable.normalized_cloud_build_evidence is None


# --- #804 corrections: command-plan validation, dominance, coherence ----------


def test_malformed_command_plan_field_fails_closed_instead_of_raising():
    """A field type ``ValidationCommandPlan`` never validates itself (it has
    no ``__post_init__``) must never reach an unguarded ``.casefold()``.
    """
    request, command_plan, dispatch, authorization, configuration = _inputs()
    tampered = replace(command_plan, repository=12345)  # type: ignore[arg-type]
    result = prepare_cloud_build_provider_invocation(
        request,
        tampered,
        dispatch,
        authorization,
        configuration,
        resolved_sha=SHA,
        evaluated_at="2026-07-30T20:00:00Z",
    )
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert ProviderReason.COMMAND_PLAN_INVALID in result.reason_codes
    assert result.invocation is None
    assert result.merge_authorized is False


def test_unregistered_argv_never_reaches_an_accepted_invocation():
    request, command_plan, dispatch, authorization, configuration = _inputs()
    rogue_entries = (
        CommandPlanEntry(
            operation=CommandOperation.VALIDATION_AGGREGATE, argv=("rm", "-rf", "/")
        ),
    )
    tampered = replace(command_plan, entries=rogue_entries)
    result = prepare_cloud_build_provider_invocation(
        request,
        tampered,
        dispatch,
        authorization,
        configuration,
        resolved_sha=SHA,
        evaluated_at="2026-07-30T20:00:00Z",
    )
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert ProviderReason.COMMAND_PLAN_INVALID in result.reason_codes
    assert result.invocation is None


def test_pre_pr_schema_command_plan_is_rejected():
    request, command_plan, dispatch, authorization, configuration = _inputs()
    pre_pr_shaped = replace(
        command_plan,
        validation_plan_id="pre-pr-validation-plan:" + "a" * 64,
        validation_plan_schema_version="1.0",
        profile="focused",
        entries=(
            CommandPlanEntry(
                operation=CommandOperation.VALIDATION_FOCUSED,
                argv=(
                    "python",
                    "-m",
                    "pytest",
                    "08_Tooling/notion-navigation-client/tests",
                ),
            ),
        ),
    )
    dispatch = replace(dispatch, profile="focused")
    authorization = replace(
        authorization, command_plan_id=validation_command_plan_id(pre_pr_shaped)
    )
    result = prepare_cloud_build_provider_invocation(
        request,
        pre_pr_shaped,
        dispatch,
        authorization,
        configuration,
        resolved_sha=SHA,
        evaluated_at="2026-07-30T20:00:00Z",
    )
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert ProviderReason.COMMAND_PLAN_UNSUPPORTED_SCHEMA in result.reason_codes
    assert result.invocation is None


def test_unknown_side_effect_dominates_a_successful_terminal_status():
    invocation = _accepted().invocation
    observation = CloudBuildProviderObservation(
        invocation_id=invocation.invocation_id,
        build_id="build:804",
        repository=invocation.repository,
        tested_sha=invocation.resolved_sha,
        terminal_status=ProviderObservationStatus.SUCCESS,
        failed_step="none",
        exit_code=0,
        observed_at="2026-07-30T20:10:00Z",
        source_complete=True,
        side_effect_state=ProviderSideEffectState.UNKNOWN,
    )
    result = project_cloud_build_provider_result(invocation, observation)
    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN
    assert result.normalized_cloud_build_evidence is None
    assert result.reason_codes == (ProviderReason.OBSERVATION_UNKNOWN,)
    assert result.merge_authorized is False


def test_invocation_rejects_argv_identity_that_does_not_match_its_entries():
    invocation = _accepted().invocation
    with pytest.raises(ValueError, match="fixed_argv_identities"):
        replace(invocation, fixed_argv_identities=("0" * 64,))


def test_result_rejects_contradictory_direct_construction():
    accepted = _accepted()
    with pytest.raises(ValueError, match="cannot carry build evidence"):
        replace(accepted, build_id="build:804")
    with pytest.raises(ValueError, match="agree with whether an invocation is carried"):
        replace(accepted, execution_authorized=False)
    with pytest.raises(ValueError, match="unavailable, unknown, and terminal"):
        replace(
            accepted,
            status=ProviderStatus.UNKNOWN,
            invocation=None,
            invocation_id=None,
            execution_authorized=False,
            side_effect_state=ProviderSideEffectState.UNKNOWN,
        )
    manual_review = prepare_cloud_build_provider_invocation(
        *_inputs(), resolved_sha="f" * 40, evaluated_at="2026-07-30T20:00:00Z"
    )
    assert manual_review.status is ProviderStatus.MANUAL_REVIEW
    with pytest.raises(ValueError, match="unknown result requires"):
        replace(
            manual_review,
            status=ProviderStatus.UNKNOWN,
            invocation=accepted.invocation,
            invocation_id=accepted.invocation_id,
            execution_authorized=True,
            side_effect_state=ProviderSideEffectState.CONFIRMED,
        )


def test_result_merge_authorized_is_immutable():
    accepted = _accepted()
    with pytest.raises(TypeError):
        CloudBuildProviderResult(
            schema_version=accepted.schema_version,
            status=accepted.status,
            invocation=accepted.invocation,
            invocation_id=accepted.invocation_id,
            build_id=None,
            tested_sha=None,
            reason_codes=accepted.reason_codes,
            normalized_cloud_build_evidence=None,
            execution_authorized=True,
            side_effect_state=accepted.side_effect_state,
            merge_authorized=True,  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "2026-02-30T00:00:00Z",  # impossible calendar date
        "2026-01-01T25:00:00Z",  # impossible hour
        "2026-01-01T00:61:00Z",  # impossible minute
        "2026-1-1T00:00:00Z",  # not zero-padded
        "not-a-timestamp",
    ],
)
def test_observation_rejects_impossible_or_malformed_timestamps_without_reading_the_clock(
    bad_timestamp,
):
    invocation = _accepted().invocation
    with pytest.raises(ValueError, match="canonical UTC"):
        CloudBuildProviderObservation(
            invocation_id=invocation.invocation_id,
            build_id="build:804",
            repository=invocation.repository,
            tested_sha=invocation.resolved_sha,
            terminal_status=ProviderObservationStatus.SUCCESS,
            failed_step="none",
            exit_code=0,
            observed_at=bad_timestamp,
            source_complete=True,
            side_effect_state=ProviderSideEffectState.CONFIRMED,
        )


def test_public_surface_has_no_shell_sdk_or_io_capability():
    import scripts.agent_os_cloud_build_provider.core as core
    import scripts.agent_os_cloud_build_provider.models as models

    source = inspect.getsource(core) + inspect.getsource(models)
    for forbidden in (
        "subprocess",
        "requests",
        "google.cloud",
        "googleapiclient",
        "PyGithub",
        "os.environ",
        "Path(",
        "open(",
        "shell=True",
    ):
        assert forbidden not in source
