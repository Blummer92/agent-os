"""Focused regressions for #1210: candidate-bound pre-PR plan admission.

A canonical ``PrePrValidationPlan`` already converts to the standard
``ValidationCommandPlan`` transport through ``build_validation_command_plan``'s
existing pre-PR branch (#723/#1030). These tests exercise the remaining gap:
``prepare_cloud_build_provider_invocation`` admitting that converted plan
through the exact same identity, authorization, and dispatch-eligibility gate
used for a positive-PR plan -- never as its own authority, and never with an
invented pull request.
"""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from agent_os_execution_service import (
    EvidenceVisibilityPolicy,
    ExecutionAuthorizationEvidence,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceRequest,
    build_validation_command_plan,
    validation_command_plan_id,
)
from scripts.agent_os_cloud_build_provider import (
    CloudBuildProviderConfiguration,
    CloudBuildProviderInvocation,
    ProviderReason,
    ProviderStatus,
    prepare_cloud_build_provider_invocation,
)
from scripts.agent_os_execution_capabilities import RepositoryIdentity
from scripts.agent_os_remote_validation import (
    PrePrValidationSubject,
    evaluate_pre_pr_dispatch_decision,
    load_rule_map,
    pre_pr_validation_dispatch_identity,
    select_pre_pr_validation_plan,
)

BASE_SHA = "1" * 40
SOURCE_SHA = "2" * 40
TESTED_SHA = "3" * 40
ALLOWED_PATH = "08_Tooling/notion-navigation-client/module.py"
COMMAND = "python -m pytest 08_Tooling/notion-navigation-client/tests"
CREATED_AT = "2026-08-27T00:00:00Z"
EXPIRES_AT = "2026-08-27T04:00:00Z"
EVALUATED_AT = "2026-08-27T01:00:00Z"
AUTHORIZED_AT = "2026-08-27T00:30:00Z"
AUTH_EXPIRES_AT = "2026-08-27T03:00:00Z"


def _subject(**overrides: object) -> PrePrValidationSubject:
    values: dict[str, object] = dict(
        repository="Blummer92/agent-os",
        issue_number=1210,
        invocation_id="invocation:1210:cbp6",
        base_branch="main",
        base_sha=BASE_SHA,
        branch="agent/1210-pre-pr-cloud-build-admission",
        expected_source_sha=SOURCE_SHA,
        tested_sha=TESTED_SHA,
        allowed_files=(ALLOWED_PATH,),
        forbidden_paths=(".github/workflows",),
        required_command_identities=(COMMAND,),
        approval_id="approval:1210:0001",
        approval_revision=1,
        projection_id="projection:1210:0001",
        implementation_contract_fingerprint="a" * 64,
        execution_mode="validation-only",
        candidate_bound=True,
    )
    values.update(overrides)
    return PrePrValidationSubject(**values)  # type: ignore[arg-type]


def _historical_subject(**overrides: object) -> PrePrValidationSubject:
    """A non-candidate-bound (default-bound) pre-PR subject, e.g. #726.

    ``tested_sha`` must equal ``expected_source_sha`` outside candidate-bound
    mode, and repository/issue/base_branch/execution_mode/candidate_bound all
    keep their canonical defaults.
    """
    values: dict[str, object] = dict(
        invocation_id="invocation:726:legacy",
        base_sha=BASE_SHA,
        branch="agent/726-pre-pr-legacy",
        expected_source_sha=SOURCE_SHA,
        tested_sha=SOURCE_SHA,
        allowed_files=(ALLOWED_PATH,),
        forbidden_paths=(".github/workflows",),
        required_command_identities=(COMMAND,),
        approval_id="approval:726:0001",
        approval_revision=1,
        projection_id="projection:726:0001",
        implementation_contract_fingerprint="b" * 64,
    )
    values.update(overrides)
    return PrePrValidationSubject(**values)  # type: ignore[arg-type]


def _plan(subject: PrePrValidationSubject):
    return select_pre_pr_validation_plan(subject, load_rule_map())


def _request_for(subject: PrePrValidationSubject, *, expires_at: str = EXPIRES_AT):
    return ExecutionServiceRequest(
        schema_version="1.0",
        request_id=f"request:{subject.issue_number}",
        request_revision=1,
        created_at=CREATED_AT,
        expires_at=expires_at,
        repository_identity=RepositoryIdentity(
            host="github.com", owner="blummer92", repository="agent-os"
        ),
        issue_or_handoff_identity=f"issue:{subject.issue_number}",
        canonical_owner="github-service-agent",
        requesting_actor="repository-owner",
        capability=ExecutionServiceCapability.INSPECT_REPOSITORY,
        base_branch=subject.base_branch,
        base_sha=subject.base_sha,
        requested_ref=subject.branch,
        expected_sha=subject.expected_source_sha,
        allowed_paths=subject.allowed_files,
        forbidden_paths=subject.forbidden_paths,
        inspected_file_count_limit=256,
        inspected_byte_limit=1_000_000,
        evidence_visibility_policy=EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        invalidation_conditions=(
            ExecutionServiceInvalidationCondition.EXPECTED_SHA_CHANGED,
            ExecutionServiceInvalidationCondition.REQUEST_EXPIRED,
        ),
    )


def _authorization_for(request, command_plan, *, granted: bool = True):
    return ExecutionAuthorizationEvidence(
        authorization_id=f"authorization:{request.issue_or_handoff_identity}",
        request_fingerprint=request.request_fingerprint,
        command_plan_id=validation_command_plan_id(command_plan),
        repository="Blummer92/agent-os",
        expected_sha=request.expected_sha,
        authorized_at=AUTHORIZED_AT,
        expires_at=AUTH_EXPIRES_AT,
        execution_authorized=granted,
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


def _pipeline(subject: PrePrValidationSubject):
    """Build one full, self-consistent pre-PR admission pipeline."""
    plan = _plan(subject)
    request = _request_for(subject)
    command_plan = build_validation_command_plan(request, plan, evaluated_at=EVALUATED_AT)
    dispatch = evaluate_pre_pr_dispatch_decision(
        plan, current_source_sha=subject.expected_source_sha
    )
    authorization = _authorization_for(request, command_plan)
    configuration = _configuration()
    return plan, request, command_plan, dispatch, authorization, configuration


def _accepted(subject: PrePrValidationSubject | None = None):
    subject = subject or _subject()
    _plan_obj, request, command_plan, dispatch, authorization, configuration = _pipeline(
        subject
    )
    result = prepare_cloud_build_provider_invocation(
        request,
        command_plan,
        dispatch,
        authorization,
        configuration,
        resolved_sha=subject.expected_source_sha,
        evaluated_at=EVALUATED_AT,
    )
    assert result.status is ProviderStatus.ACCEPTED
    assert result.invocation is not None
    return result


def test_candidate_bound_pre_pr_plan_is_accepted_with_no_pull_request():
    result = _accepted()
    invocation = result.invocation
    assert invocation.validation_plan_id.startswith("pre-pr-validation-plan:")
    assert invocation.execution_authorized is True
    assert invocation.merge_authorized is False
    assert invocation.side_effects_performed is False
    assert invocation.profile == "focused"
    # Absence of a pull request is native to the schema, never a placeholder.
    assert "pull_request" not in {field.name for field in fields(CloudBuildProviderInvocation)}


def test_candidate_bound_pre_pr_admission_is_deterministic():
    left = _accepted()
    right = _accepted()
    assert left == right
    assert left.invocation_id == right.invocation_id
    assert left.result_id == right.result_id


def test_dispatch_decision_represents_absence_of_pull_request_natively():
    subject = _subject()
    plan = _plan(subject)
    dispatch = evaluate_pre_pr_dispatch_decision(
        plan, current_source_sha=subject.expected_source_sha
    )
    assert dispatch.pull_request is None
    assert dispatch.status == "launch-eligible"
    assert dispatch.launch_recommended is True
    assert dispatch.dispatch_identity == pre_pr_validation_dispatch_identity(plan)


def test_historical_non_candidate_bound_subject_is_accepted_when_fully_matched():
    """#726-style default-bound subjects get no weaker treatment."""
    result = _accepted(_historical_subject())
    assert result.invocation.repository == "Blummer92/agent-os"


def test_historical_non_candidate_bound_subject_still_requires_exact_identity_match():
    subject = _historical_subject()
    _plan_obj, request, command_plan, dispatch, authorization, configuration = _pipeline(
        subject
    )
    # A different historical invocation produces a different plan identity;
    # the original authorization/dispatch must not carry over to it.
    other_subject = _historical_subject(invocation_id="invocation:726:other")
    _other_plan, other_request, other_command_plan, _other_dispatch, _other_auth, _cfg = (
        _pipeline(other_subject)
    )
    assert other_command_plan.validation_plan_id != command_plan.validation_plan_id

    result = prepare_cloud_build_provider_invocation(
        other_request,
        other_command_plan,
        dispatch,
        authorization,
        configuration,
        resolved_sha=other_subject.expected_source_sha,
        evaluated_at=EVALUATED_AT,
    )
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert ProviderReason.AUTHORIZATION_MISMATCH in result.reason_codes
    assert result.invocation is None


def test_pre_pr_subject_field_drift_changes_identity_and_fails_closed():
    subject = _subject()
    _plan_obj, _request_obj, command_plan, dispatch, authorization, configuration = (
        _pipeline(subject)
    )

    drifted_subject = replace(subject, approval_id="approval:1210:0002")
    drifted_plan, drifted_request, drifted_command_plan, _d, _a, _c = _pipeline(
        drifted_subject
    )
    assert drifted_command_plan.validation_plan_id != command_plan.validation_plan_id

    result = prepare_cloud_build_provider_invocation(
        drifted_request,
        drifted_command_plan,
        dispatch,
        authorization,
        configuration,
        resolved_sha=drifted_subject.expected_source_sha,
        evaluated_at=EVALUATED_AT,
    )
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert ProviderReason.AUTHORIZATION_MISMATCH in result.reason_codes
    assert result.invocation is None


@pytest.mark.parametrize(
    "mutation, reason",
    [
        ("expired", ProviderReason.REQUEST_EXPIRED),
        ("denied", ProviderReason.AUTHORIZATION_NOT_GRANTED),
        ("auth-sha", ProviderReason.AUTHORIZATION_MISMATCH),
        ("ref", ProviderReason.REQUESTED_REF_MISMATCH),
        ("repository", ProviderReason.REPOSITORY_MISMATCH),
        ("resolved-sha", ProviderReason.RESOLVED_SHA_MISMATCH),
        ("plan-id", ProviderReason.AUTHORIZATION_MISMATCH),
    ],
)
def test_pre_pr_identity_and_authorization_drift_fails_closed(mutation, reason):
    subject = _subject()
    _plan_obj, request, command_plan, dispatch, authorization, configuration = _pipeline(
        subject
    )
    resolved_sha = subject.expected_source_sha
    if mutation == "expired":
        request = _request_for(subject, expires_at="2026-08-27T00:59:59Z")
    elif mutation == "denied":
        authorization = replace(authorization, execution_authorized=False)
    elif mutation == "auth-sha":
        authorization = replace(authorization, expected_sha="e" * 40)
    elif mutation == "ref":
        command_plan = replace(command_plan, requested_ref="other/ref")
    elif mutation == "repository":
        dispatch = replace(dispatch, repository="other/repo")
    elif mutation == "plan-id":
        command_plan = replace(
            command_plan, validation_plan_id="pre-pr-validation-plan:" + "f" * 64
        )
    else:
        resolved_sha = "f" * 40

    result = prepare_cloud_build_provider_invocation(
        request,
        command_plan,
        dispatch,
        authorization,
        configuration,
        resolved_sha=resolved_sha,
        evaluated_at=EVALUATED_AT,
    )
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert reason in result.reason_codes
    assert result.invocation is None
    assert result.merge_authorized is False


def test_stale_pre_pr_dispatch_creates_no_invocation():
    subject = _subject()
    _plan_obj, request, command_plan, _dispatch, authorization, configuration = _pipeline(
        subject
    )
    plan = _plan(subject)
    stale_dispatch = evaluate_pre_pr_dispatch_decision(
        plan, current_source_sha="9" * 40
    )
    assert stale_dispatch.status == "stale-skipped"
    assert stale_dispatch.launch_recommended is False

    result = prepare_cloud_build_provider_invocation(
        request,
        command_plan,
        stale_dispatch,
        authorization,
        configuration,
        resolved_sha=subject.expected_source_sha,
        evaluated_at=EVALUATED_AT,
    )
    assert result.status is ProviderStatus.SKIPPED
    assert result.reason_codes == (ProviderReason.DISPATCH_NON_LAUNCH,)
    assert result.invocation is None
    assert result.merge_authorized is False


def test_invalid_pre_pr_plan_type_produces_manual_review_dispatch_decision():
    decision = evaluate_pre_pr_dispatch_decision(
        "not-a-plan", current_source_sha=SOURCE_SHA
    )
    assert decision.status == "manual-review"
    assert decision.launch_recommended is False
    assert decision.dispatch_identity is None
    assert decision.plan_id is None
    assert decision.pull_request is None


def test_pre_pr_dispatch_decision_is_deterministic():
    subject = _subject()
    plan = _plan(subject)
    left = evaluate_pre_pr_dispatch_decision(
        plan, current_source_sha=subject.expected_source_sha
    )
    right = evaluate_pre_pr_dispatch_decision(
        plan, current_source_sha=subject.expected_source_sha
    )
    assert left == right
