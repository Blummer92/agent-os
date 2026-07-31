import ast
from dataclasses import dataclass, field, replace
from pathlib import Path
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
    CloudBuildObservationOutcome,
    CloudBuildObservationRequest,
    CloudBuildProviderAdapter,
    CloudBuildProviderClient,
    CloudBuildProviderConfiguration,
    CloudBuildProviderResult,
    CloudBuildReconciliationOutcome,
    CloudBuildReconciliationRequest,
    CloudBuildSubmissionOutcome,
    CloudBuildSubmissionRequest,
    ProviderReason,
    ProviderSideEffectState,
    ProviderStatus,
    cloud_build_provider_invocation_id,
    prepare_cloud_build_provider_invocation,
)
from scripts.agent_os_cloud_build_reporting import OverallResult, normalize_cloud_build_evidence
from scripts.agent_os_execution_capabilities import RepositoryIdentity
from scripts.agent_os_remote_validation import (
    ValidationPlan,
    compute_command_set_digest,
    evaluate_dispatch_decision,
    validation_plan_id,
)

SHA = "a" * 40
BASE_SHA = "b" * 40
OTHER_SHA = "e" * 40
COMMAND = "python -m pytest"
SELECTOR_VERSION = "1.0.0"
DIGEST = compute_command_set_digest(SELECTOR_VERSION, (COMMAND,))
OBSERVED_AT = "2026-07-31T00:05:00Z"
OBSERVED_AT_LATER = "2026-07-31T00:06:00Z"


def _request(*, expires_at="2026-07-31T00:00:00Z"):
    return ExecutionServiceRequest(
        schema_version="1.0",
        request_id="request:805",
        request_revision=1,
        created_at="2026-07-30T19:00:00Z",
        expires_at=expires_at,
        repository_identity=RepositoryIdentity(
            host="github.com", owner="blummer92", repository="agent-os"
        ),
        issue_or_handoff_identity="issue:805",
        canonical_owner="github-service-agent",
        requesting_actor="repository-owner",
        capability=ExecutionServiceCapability.INSPECT_REPOSITORY,
        base_branch="main",
        base_sha=BASE_SHA,
        requested_ref="agent/805-cloud-build-provider-adapter",
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
        pull_request=805,
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


def _configuration_variant():
    return replace(
        _configuration(),
        evidence_destination_identity="gs://agent-os-evidence/other-runs",
        configuration_fingerprint="",
    )


def _authorization(request, command_plan, *, granted=True):
    return ExecutionAuthorizationEvidence(
        authorization_id="authorization:805",
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


def _invocation(configuration=None):
    inputs = list(_inputs())
    if configuration is not None:
        inputs[4] = configuration
    result = prepare_cloud_build_provider_invocation(
        *inputs, resolved_sha=SHA, evaluated_at="2026-07-30T20:00:00Z"
    )
    assert result.status is ProviderStatus.ACCEPTED
    assert result.invocation is not None
    return result.invocation


class FakeCloudBuildClient:
    """Injected test double satisfying CloudBuildProviderClient exactly."""

    def __init__(
        self,
        *,
        submit_result=None,
        submit_error=None,
        observe_results=None,
        observe_error=None,
        reconcile_result=None,
        reconcile_error=None,
    ):
        self._submit_result = submit_result
        self._submit_error = submit_error
        self._observe_results = observe_results or []
        self._observe_error = observe_error
        self._reconcile_result = reconcile_result
        self._reconcile_error = reconcile_error
        self.submit_calls = []
        self.observe_calls = []
        self.reconcile_calls = []

    def submit(self, request):
        self.submit_calls.append(request)
        if self._submit_error is not None:
            raise self._submit_error
        return self._submit_result

    def observe(self, request):
        self.observe_calls.append(request)
        if self._observe_error is not None:
            raise self._observe_error
        index = len(self.observe_calls) - 1
        if index < len(self._observe_results):
            return self._observe_results[index]
        return self._observe_results[-1]

    def reconcile(self, request):
        self.reconcile_calls.append(request)
        if self._reconcile_error is not None:
            raise self._reconcile_error
        return self._reconcile_result


def _adapter(client, *, configuration=None, max_poll_attempts=8):
    return CloudBuildProviderAdapter(
        client=client,
        configuration=configuration or _configuration(),
        max_poll_attempts=max_poll_attempts,
    )


# 1. valid invocation submits exactly once.
def test_valid_invocation_submits_exactly_once():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    result = _adapter(client).run(invocation)
    assert len(client.submit_calls) == 1
    assert result.status is ProviderStatus.TERMINAL
    assert result.build_id == "build-1"


# 2. invalid or drifted invocation submits zero times.
@pytest.mark.parametrize("bad_kind", ["wrong-type", "drifted"])
def test_invalid_or_drifted_invocation_submits_zero_times(bad_kind):
    if bad_kind == "wrong-type":
        invocation = object()
    else:
        invocation = _invocation()
        object.__setattr__(invocation, "resolved_sha", OTHER_SHA)
        assert invocation.invocation_id != cloud_build_provider_invocation_id(invocation)

    client = FakeCloudBuildClient()
    result = _adapter(client).run(invocation)
    assert client.submit_calls == []
    assert client.observe_calls == []
    assert client.reconcile_calls == []
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert ProviderReason.INPUT_INVALID_TYPE in result.reason_codes
    assert result.invocation is None
    assert result.execution_authorized is False


# 3. bound configuration and command identities are transported exactly.
def test_submission_transports_bound_identities_exactly():
    invocation = _invocation()
    configuration = _configuration()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    _adapter(client, configuration=configuration).run(invocation)
    assert len(client.submit_calls) == 1
    transported = client.submit_calls[0]
    assert isinstance(transported, CloudBuildSubmissionRequest)
    assert transported.repository == invocation.repository
    assert transported.resolved_sha == invocation.resolved_sha
    assert transported.profile == invocation.profile
    assert transported.selector_version == invocation.selector_version
    assert transported.command_set_digest == invocation.command_set_digest
    assert transported.fixed_command_entries == invocation.fixed_command_entries
    assert transported.fixed_argv_identities == invocation.fixed_argv_identities
    assert transported.provider_configuration_fingerprint == invocation.provider_configuration_fingerprint
    assert transported.project_id == configuration.project_id
    assert transported.location == configuration.location
    assert transported.build_service_account_identity == configuration.build_service_account_identity
    assert transported.build_definition_identity == configuration.build_definition_identity
    assert transported.builder_image_identity == configuration.builder_image_identity
    assert transported.validator_dependency_identity == configuration.validator_dependency_identity
    assert transported.evidence_destination_identity == configuration.evidence_destination_identity
    assert transported.max_build_timeout_seconds == configuration.max_build_timeout_seconds
    assert transported.max_output_bytes == configuration.max_output_bytes
    # carry the invocation ID as provider metadata, and nothing else.
    assert transported.provider_metadata == {"invocation_id": invocation.invocation_id}


# 4. confirmed submission returns one build ID.
def test_confirmed_submission_returns_one_build_id():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-42", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    result = _adapter(client).run(invocation)
    assert result.build_id == "build-42"
    assert isinstance(result.build_id, str)


# 5. pre-submission failure has no side effect.
def test_pre_submission_failure_has_no_side_effect():
    invocation = _invocation()
    object.__setattr__(invocation, "resolved_sha", OTHER_SHA)
    client = FakeCloudBuildClient()
    result = _adapter(client).run(invocation)
    assert client.submit_calls == []
    assert result.side_effect_state is ProviderSideEffectState.NONE


# 6. ambiguous post-submission failure returns unknown and does not retry.
def test_ambiguous_post_submission_failure_returns_unknown_without_retry():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_error=ConnectionError("connection reset while waiting for a response"),
        reconcile_result=CloudBuildReconciliationOutcome(matches=(), observed_at=OBSERVED_AT),
    )
    result = _adapter(client).run(invocation)
    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN
    assert len(client.submit_calls) == 1
    assert len(client.reconcile_calls) == 1


# 7. permission denied.
def test_permission_denied_result():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="denied", observed_at=OBSERVED_AT, diagnostic="permission denied"),
    )
    result = _adapter(client).run(invocation)
    assert client.observe_calls == []
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert result.reason_codes == (ProviderReason.PROVIDER_PERMISSION_DENIED,)
    assert result.side_effect_state is ProviderSideEffectState.NONE
    assert result.build_id is None
    assert result.merge_authorized is False


# 8. provider unavailable and internal error.
@pytest.mark.parametrize("kind", ["unavailable", "internal-error"])
def test_provider_unavailable_and_internal_error(kind):
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind=kind, observed_at=OBSERVED_AT),
    )
    result = _adapter(client).run(invocation)
    assert client.observe_calls == []
    assert result.status is ProviderStatus.UNAVAILABLE
    assert result.side_effect_state is ProviderSideEffectState.NONE
    assert result.build_id is None


# 9. working and terminal observations.
def test_working_observation_exhausts_bounded_polling():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[CloudBuildObservationOutcome(kind="working", observed_at=OBSERVED_AT)],
    )
    adapter = _adapter(client, max_poll_attempts=3)
    result = adapter.run(invocation)
    assert len(client.observe_calls) == 3
    assert result.status is ProviderStatus.UNAVAILABLE
    assert result.side_effect_state is ProviderSideEffectState.CONFIRMED


def test_terminal_observation_after_working_polls():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(kind="working", observed_at=OBSERVED_AT),
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            ),
        ],
    )
    adapter = _adapter(client, max_poll_attempts=5)
    result = adapter.run(invocation)
    assert len(client.observe_calls) == 2
    assert result.status is ProviderStatus.TERMINAL


# 10. exact tested-SHA verification.
def test_tested_sha_mismatch_fails_closed():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=OTHER_SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    result = _adapter(client).run(invocation)
    assert result.status is ProviderStatus.MANUAL_REVIEW
    assert ProviderReason.OBSERVATION_TESTED_SHA_MISMATCH in result.reason_codes
    assert result.side_effect_state is ProviderSideEffectState.CONFIRMED


# 11. truthful failed-step and exit-code behavior.
def test_failure_observation_carries_true_failed_step_and_exit_code():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="failure",
                tested_sha=SHA,
                failed_step="pytest",
                exit_code=1,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    result = _adapter(client).run(invocation)
    assert result.status is ProviderStatus.TERMINAL
    evidence = result.normalized_cloud_build_evidence
    assert evidence.failed_step == "pytest"
    assert evidence.exit_code == 1
    assert evidence.overall_result is OverallResult.FAILURE


# 12. one exact reconciliation match.
def test_reconciliation_single_match_recovers_confirmed_build():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="ambiguous", observed_at=OBSERVED_AT),
        reconcile_result=CloudBuildReconciliationOutcome(matches=("build-recovered",), observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    result = _adapter(client).run(invocation)
    assert len(client.submit_calls) == 1
    assert len(client.reconcile_calls) == 1
    assert result.status is ProviderStatus.TERMINAL
    assert result.build_id == "build-recovered"


# 13. zero and multiple reconciliation matches.
@pytest.mark.parametrize("matches", [(), ("build-a", "build-b")])
def test_reconciliation_ambiguous_match_counts_stay_unknown(matches):
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="ambiguous", observed_at=OBSERVED_AT),
        reconcile_result=CloudBuildReconciliationOutcome(matches=matches, observed_at=OBSERVED_AT),
    )
    result = _adapter(client).run(invocation)
    assert client.observe_calls == []
    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN


# 14. unsupported cancellation.
def test_client_protocol_exposes_no_cancellation_capability():
    assert not hasattr(CloudBuildProviderClient, "cancel")
    assert set(CloudBuildProviderClient.__protocol_attrs__) == {"submit", "observe", "reconcile"}


def test_cancelled_observation_is_relayed_without_adapter_initiated_cancellation():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[CloudBuildObservationOutcome(kind="cancelled", observed_at=OBSERVED_AT_LATER, source_complete=False)],
    )
    result = _adapter(client).run(invocation)
    assert not hasattr(client, "cancel")
    assert result.side_effect_state is ProviderSideEffectState.CONFIRMED


# 15. duplicate adapter operation does not submit twice.
def test_duplicate_run_does_not_resubmit():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    adapter = _adapter(client)
    adapter.run(invocation)
    with pytest.raises(RuntimeError):
        adapter.run(invocation)
    assert len(client.submit_calls) == 1


# 16. hostile diagnostics and secret redaction.
def test_hostile_diagnostics_are_sanitized_and_bounded():
    invocation = _invocation()
    hostile = "Authorization: Bearer abcd1234efgh5678\x07\x01" + ("x" * 2000)
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[CloudBuildObservationOutcome(kind="working", observed_at=OBSERVED_AT, diagnostic=hostile)],
    )
    adapter = _adapter(client, max_poll_attempts=1)
    adapter.run(invocation)
    assert "Bearer" not in adapter.last_diagnostic
    assert "\x07" not in adapter.last_diagnostic
    assert "\x01" not in adapter.last_diagnostic
    assert len(adapter.last_diagnostic) <= 512


def test_raised_exception_diagnostics_never_include_exception_message():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_error=RuntimeError("token=super-secret-value leaked from /etc/private/creds"),
        reconcile_result=CloudBuildReconciliationOutcome(matches=(), observed_at=OBSERVED_AT),
    )
    adapter = _adapter(client)
    adapter.run(invocation)
    assert "super-secret-value" not in adapter.last_diagnostic
    assert "/etc/private/creds" not in adapter.last_diagnostic


# 17. bounded poll count and diagnostics.
def test_poll_count_is_bounded():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[CloudBuildObservationOutcome(kind="working", observed_at=OBSERVED_AT, diagnostic="still building")],
    )
    adapter = _adapter(client, max_poll_attempts=4)
    adapter.run(invocation)
    assert adapter.poll_attempts == 4
    assert len(client.observe_calls) == 4
    assert adapter.last_diagnostic == "still building"


def test_max_poll_attempts_is_bounded_at_construction():
    client = FakeCloudBuildClient()
    with pytest.raises(ValueError):
        _adapter(client, max_poll_attempts=0)
    with pytest.raises(ValueError):
        _adapter(client, max_poll_attempts=31)


# 18. terminal evidence reuses the existing #685 projection.
def test_terminal_result_reuses_normalize_cloud_build_evidence_projection():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    result = _adapter(client).run(invocation)
    expected = normalize_cloud_build_evidence(
        build_id="build-1",
        tested_sha=SHA,
        repository=invocation.repository,
        overall_result=OverallResult.SUCCESS,
        terminal=True,
        source_complete=True,
        invocation_id=invocation.invocation_id,
        failed_step="none",
        exit_code=0,
        observed_at=OBSERVED_AT_LATER,
    )
    assert result.normalized_cloud_build_evidence == expected


# 19. every result keeps merge_authorized=false.
def test_all_result_paths_keep_merge_authorized_false():
    scenarios = []

    drifted = _invocation()
    object.__setattr__(drifted, "resolved_sha", OTHER_SHA)
    scenarios.append((drifted, FakeCloudBuildClient()))

    scenarios.append((
        _invocation(),
        FakeCloudBuildClient(submit_result=CloudBuildSubmissionOutcome(kind="denied", observed_at=OBSERVED_AT)),
    ))
    scenarios.append((
        _invocation(),
        FakeCloudBuildClient(submit_result=CloudBuildSubmissionOutcome(kind="unavailable", observed_at=OBSERVED_AT)),
    ))
    scenarios.append((
        _invocation(),
        FakeCloudBuildClient(
            submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-9", observed_at=OBSERVED_AT),
            observe_results=[
                CloudBuildObservationOutcome(
                    kind="success",
                    tested_sha=SHA,
                    failed_step="none",
                    exit_code=0,
                    observed_at=OBSERVED_AT_LATER,
                    source_complete=True,
                )
            ],
        ),
    ))
    scenarios.append((
        _invocation(),
        FakeCloudBuildClient(
            submit_result=CloudBuildSubmissionOutcome(kind="ambiguous", observed_at=OBSERVED_AT),
            reconcile_result=CloudBuildReconciliationOutcome(matches=(), observed_at=OBSERVED_AT),
        ),
    ))

    for invocation, client in scenarios:
        result = _adapter(client).run(invocation)
        assert isinstance(result, CloudBuildProviderResult)
        assert result.merge_authorized is False
        if result.invocation is not None:
            assert result.invocation.merge_authorized is False


# 20. no live Cloud, GitHub, credential, workflow, IAM, deployment, or unrelated external write occurs.
def test_adapter_module_imports_no_live_io_or_sdk():
    source_path = _REPO_ROOT / "scripts" / "agent_os_cloud_build_provider" / "adapter.py"
    tree = ast.parse(source_path.read_text())
    allowed_absolute = {"__future__", "re", "dataclasses", "typing"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed_absolute, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                assert node.module is not None and node.module.split(".")[0] in allowed_absolute, node.module
            else:
                assert node.module in {"core", "models"}, node.module
    lowered = source_path.read_text().lower()
    for forbidden in ("google.cloud", "googleapiclient", "requests.", "subprocess", "socket.", "urllib"):
        assert forbidden not in lowered


def test_adapter_never_calls_client_outside_injected_protocol_methods():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=SHA,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    _adapter(client).run(invocation)
    assert len(client.submit_calls) == 1
    assert len(client.observe_calls) == 1
    assert len(client.reconcile_calls) == 0


# --- PR #818 review Finding 1: configuration-fingerprint drift is untested. ---
def test_configuration_fingerprint_drift_submits_zero_times():
    configuration_a = _configuration()
    invocation = _invocation(configuration=configuration_a)
    configuration_b = _configuration_variant()
    assert configuration_b.configuration_fingerprint != configuration_a.configuration_fingerprint

    client = FakeCloudBuildClient()
    result = _adapter(client, configuration=configuration_b).run(invocation)

    assert client.submit_calls == []
    assert client.observe_calls == []
    assert client.reconcile_calls == []
    assert result.side_effect_state is ProviderSideEffectState.NONE
    assert result.merge_authorized is False
    assert result.invocation is None
    assert result.execution_authorized is False


# --- PR #818 review Finding 2: post-submission exception/malformed-response
# paths in observe() and reconcile(), and the submit()-malformed-outcome and
# _safe_observation fail-closed fallback, were untested. ---
def test_malformed_submit_outcome_reconciles_and_fails_closed_without_retry():
    invocation = _invocation()
    hostile = "not-a-real-submission-outcome token=abc123-should-not-leak"
    client = FakeCloudBuildClient(
        submit_result=hostile,
        reconcile_result=CloudBuildReconciliationOutcome(matches=(), observed_at=OBSERVED_AT),
    )
    adapter = _adapter(client)
    result = adapter.run(invocation)

    assert len(client.submit_calls) == 1
    assert len(client.reconcile_calls) == 1
    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN
    assert hostile not in adapter.last_diagnostic
    assert "abc123-should-not-leak" not in repr(result)

    with pytest.raises(RuntimeError):
        adapter.run(invocation)
    assert len(client.submit_calls) == 1


def test_reconciliation_exception_after_ambiguous_submission_returns_unknown_without_retry():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="ambiguous", observed_at=OBSERVED_AT),
        reconcile_error=RuntimeError("token=super-secret-reconcile-value from /etc/private/creds"),
    )
    adapter = _adapter(client)
    result = adapter.run(invocation)

    assert len(client.submit_calls) == 1
    assert len(client.reconcile_calls) == 1
    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN
    assert "super-secret-reconcile-value" not in adapter.last_diagnostic
    assert "/etc/private/creds" not in adapter.last_diagnostic

    with pytest.raises(RuntimeError):
        adapter.run(invocation)
    assert len(client.submit_calls) == 1
    assert len(client.reconcile_calls) == 1


def test_malformed_reconciliation_outcome_stays_unknown_without_retry():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="ambiguous", observed_at=OBSERVED_AT),
        reconcile_result={"matches": ["build-x"]},
    )
    adapter = _adapter(client)
    result = adapter.run(invocation)

    assert len(client.submit_calls) == 1
    assert len(client.reconcile_calls) == 1
    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN
    assert result.build_id is None

    with pytest.raises(RuntimeError):
        adapter.run(invocation)
    assert len(client.submit_calls) == 1


def test_observation_exception_after_confirmed_build_returns_unknown_without_retry():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_error=RuntimeError("token=super-secret-observe-value from /etc/private/creds"),
    )
    adapter = _adapter(client)
    result = adapter.run(invocation)

    assert len(client.submit_calls) == 1
    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN
    assert "super-secret-observe-value" not in adapter.last_diagnostic
    assert "/etc/private/creds" not in adapter.last_diagnostic

    with pytest.raises(RuntimeError):
        adapter.run(invocation)
    assert len(client.submit_calls) == 1


def test_malformed_observation_outcome_fails_closed_without_retry():
    invocation = _invocation()
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[object()],
    )
    adapter = _adapter(client)
    result = adapter.run(invocation)

    assert len(client.submit_calls) == 1
    assert len(client.observe_calls) == 1
    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN

    with pytest.raises(RuntimeError):
        adapter.run(invocation)
    assert len(client.submit_calls) == 1


def test_safe_observation_fallback_rejects_invalid_tested_sha_format():
    invocation = _invocation()
    hostile = "not-a-real-sha-value"
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="success",
                tested_sha=hostile,
                failed_step="none",
                exit_code=0,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    result = _adapter(client).run(invocation)

    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN
    assert result.build_id is None
    assert result.tested_sha is None
    assert result.normalized_cloud_build_evidence is None
    assert hostile not in repr(result)


def test_safe_observation_fallback_rejects_hostile_failed_step_value():
    invocation = _invocation()
    hostile = "token=super-secret-step-value"
    client = FakeCloudBuildClient(
        submit_result=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observe_results=[
            CloudBuildObservationOutcome(
                kind="failure",
                tested_sha=SHA,
                failed_step=hostile,
                exit_code=1,
                observed_at=OBSERVED_AT_LATER,
                source_complete=True,
            )
        ],
    )
    result = _adapter(client).run(invocation)

    assert result.status is ProviderStatus.UNKNOWN
    assert result.side_effect_state is ProviderSideEffectState.UNKNOWN
    assert result.build_id is None
    assert result.tested_sha is None
    assert result.normalized_cloud_build_evidence is None
    assert hostile not in repr(result)
