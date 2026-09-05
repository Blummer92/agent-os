from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEDULER_SRC = _REPO_ROOT / "08_Tooling/workflow-scheduler/src"
if str(_SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(_SCHEDULER_SRC))

from scripts.agent_os_cloud_build_provider import (
    CloudBuildObservationOutcome,
    CloudBuildProviderAdapter,
    CloudBuildProviderConfiguration,
    CloudBuildReconciliationOutcome,
    CloudBuildSubmissionOutcome,
    ProviderStatus,
)
from tests.agent_os_cloud_build_provider.test_adapter import _invocation
from workflow_scheduler.execution.cloud_build_lease_lifecycle import (
    CloudBuildLeaseBinding,
    run_cloud_build_lease_lifecycle,
)
from workflow_scheduler.execution.single_issue_pilot import (
    PilotLeaseGrant,
    PilotLeaseReleaseObservation,
    pilot_holder_identity,
    pilot_lease_identity,
)

SHA = "a" * 40
OBSERVED_AT = "2026-07-31T00:05:00Z"


class FakeClient:
    def __init__(self, *, submit, observations=(), reconciliation=None):
        self.submit_result = submit
        self.observations = list(observations)
        self.reconciliation = reconciliation
        self.submit_calls = []
        self.observe_calls = []
        self.reconcile_calls = []

    def submit(self, request):
        self.submit_calls.append(request)
        return self.submit_result

    def observe(self, request):
        self.observe_calls.append(request)
        if not self.observations:
            raise AssertionError("observation not configured")
        index = min(len(self.observe_calls) - 1, len(self.observations) - 1)
        return self.observations[index]

    def reconcile(self, request):
        self.reconcile_calls.append(request)
        return self.reconciliation


class FakeLease:
    def __init__(self, *, release_result=True):
        self.acquire_calls = []
        self.release_calls = []
        self.release_result = release_result

    def acquire(self, request):
        self.acquire_calls.append(request)
        return PilotLeaseGrant(
            acquired=True,
            lease_identity=pilot_lease_identity(request),
            holder_identity=pilot_holder_identity(request),
            generation=1,
        )

    def release(self, grant):
        self.release_calls.append(grant)
        return PilotLeaseReleaseObservation(
            released=self.release_result,
            lease_identity=grant.lease_identity,
            holder_identity=grant.holder_identity,
            generation=grant.generation,
            ambiguous=not self.release_result,
        )


def _configuration():
    return CloudBuildProviderConfiguration(
        project_id="agent-os-502614",
        location="global",
        runtime_service_account_identity="agent-os-gateway@agent-os-502614.iam.gserviceaccount.com",
        build_service_account_identity="agent-os-build@agent-os-502614.iam.gserviceaccount.com",
        build_definition_identity="cloudbuild:validation:v1",
        builder_image_identity="python@sha256:" + "c" * 64,
        validator_dependency_identity="requirements-dev:sha256:" + "d" * 64,
        evidence_destination_identity="gs://agent-os-evidence/runs",
        max_build_timeout_seconds=900,
        max_output_bytes=1_000_000,
        max_diagnostic_bytes=16_384,
    )


def _binding(invocation):
    return CloudBuildLeaseBinding(
        repository=invocation.repository,
        issue_number=805,
        issue_or_handoff_identity=invocation.issue_or_handoff_identity,
        invocation_id=invocation.invocation_id,
        branch=invocation.requested_ref,
        source_head_sha=invocation.resolved_sha,
        workspace_request_id="workspace:1211",
        projection_id="projection:1211",
        approval_id="approval:1211",
    )


def _adapter(client):
    return CloudBuildProviderAdapter(client=client, configuration=_configuration(), max_poll_attempts=1)


def test_working_provider_evidence_retains_exact_lease():
    invocation = _invocation(_configuration())
    client = FakeClient(
        submit=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observations=(CloudBuildObservationOutcome(kind="working", observed_at=OBSERVED_AT),),
    )
    lease = FakeLease()

    result = run_cloud_build_lease_lifecycle(
        binding=_binding(invocation), invocation=invocation, provider=_adapter(client), lease=lease
    )

    assert result.disposition == "nonterminal-lease-retained"
    assert result.lease_retained is True
    assert result.termination_proven is False
    assert lease.release_calls == []
    assert len(client.submit_calls) == 1


def test_ambiguous_submit_reconciles_same_invocation_and_retains_lease_when_unknown():
    invocation = _invocation(_configuration())
    client = FakeClient(
        submit=CloudBuildSubmissionOutcome(kind="ambiguous", observed_at=OBSERVED_AT),
        reconciliation=CloudBuildReconciliationOutcome(matches=(), observed_at=OBSERVED_AT),
    )
    lease = FakeLease()

    result = run_cloud_build_lease_lifecycle(
        binding=_binding(invocation), invocation=invocation, provider=_adapter(client), lease=lease
    )

    assert result.provider_result is not None
    assert result.provider_result.status is ProviderStatus.UNKNOWN
    assert result.disposition == "unknown-lease-retained"
    assert len(client.submit_calls) == 1
    assert len(client.reconcile_calls) == 1
    assert lease.release_calls == []


def test_terminal_success_releases_only_the_exact_lease():
    invocation = _invocation(_configuration())
    client = FakeClient(
        submit=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observations=(
            CloudBuildObservationOutcome(
                kind="success", tested_sha=SHA, observed_at=OBSERVED_AT, source_complete=True
            ),
        ),
    )
    lease = FakeLease()

    result = run_cloud_build_lease_lifecycle(
        binding=_binding(invocation), invocation=invocation, provider=_adapter(client), lease=lease
    )

    assert result.disposition == "terminal-released"
    assert result.termination_proven is True
    assert result.lease_retained is False
    assert len(lease.release_calls) == 1
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False


def test_identity_mismatch_fails_before_lease_or_provider_call():
    invocation = _invocation(_configuration())
    binding = _binding(invocation)
    binding = CloudBuildLeaseBinding(
        repository=binding.repository,
        issue_number=binding.issue_number,
        issue_or_handoff_identity=binding.issue_or_handoff_identity,
        invocation_id=binding.invocation_id,
        branch=binding.branch,
        source_head_sha="f" * 40,
        workspace_request_id=binding.workspace_request_id,
        projection_id=binding.projection_id,
        approval_id=binding.approval_id,
    )
    client = FakeClient(submit=CloudBuildSubmissionOutcome(kind="ambiguous", observed_at=OBSERVED_AT))
    lease = FakeLease()

    result = run_cloud_build_lease_lifecycle(
        binding=binding, invocation=invocation, provider=_adapter(client), lease=lease
    )

    assert result.disposition == "identity-mismatch"
    assert lease.acquire_calls == []
    assert client.submit_calls == []


def test_terminal_result_with_ambiguous_release_remains_owned_for_recovery():
    invocation = _invocation(_configuration())
    client = FakeClient(
        submit=CloudBuildSubmissionOutcome(kind="confirmed", build_id="build-1", observed_at=OBSERVED_AT),
        observations=(
            CloudBuildObservationOutcome(
                kind="failure", tested_sha=SHA, observed_at=OBSERVED_AT, source_complete=True
            ),
        ),
    )
    lease = FakeLease(release_result=False)

    result = run_cloud_build_lease_lifecycle(
        binding=_binding(invocation), invocation=invocation, provider=_adapter(client), lease=lease
    )

    assert result.disposition == "terminal-release-failed"
    assert result.termination_proven is True
    assert result.lease_retained is True
    assert len(lease.release_calls) == 1
