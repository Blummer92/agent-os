from dataclasses import replace

import pytest

from scripts.agent_os_cloud_build_provider.cancellation import (
    CancellationEligibility,
    CloudBuildCancellationEvidence,
    CloudBuildCancellationOutcome,
    SupersededBuildCancellation,
    evaluate_cancellation,
)
from scripts.agent_os_cloud_build_provider.models import ProviderObservationStatus


SHA_A = "a" * 40
SHA_B = "b" * 40


def evidence(**overrides):
    values = dict(
        repository_matches=True,
        pr_matches=True,
        obsolete_sha=SHA_A,
        current_head_sha=SHA_B,
        supersession_proven=True,
        lane_plan_dispatch_match=True,
        invocation_id_known=True,
        build_id="build-1232",
        project_id="agent-os-502614",
        location="global",
        observation_status=ProviderObservationStatus.WORKING,
        execution_lease_match=True,
        final_head_aggregate_preserved=True,
    )
    values.update(overrides)
    return CloudBuildCancellationEvidence(**values)


class FakeClient:
    def __init__(self):
        self.calls = []

    def cancel(self, request):
        self.calls.append(request)
        return CloudBuildCancellationOutcome(accepted=True)


def test_current_head_still_obsolete_sha_is_not_superseded():
    assert evaluate_cancellation(evidence(current_head_sha=SHA_A)).outcome is CancellationEligibility.NOT_SUPERSEDED


def test_exact_working_superseded_build_is_eligible():
    assert evaluate_cancellation(evidence()).outcome is CancellationEligibility.CANCEL_ELIGIBLE


def test_insufficient_supersession_proof_fails_closed():
    assert evaluate_cancellation(evidence(supersession_proven=False)).outcome is CancellationEligibility.NOT_SUPERSEDED


@pytest.mark.parametrize("field", [
    "repository_matches", "pr_matches", "lane_plan_dispatch_match",
    "invocation_id_known", "execution_lease_match", "final_head_aggregate_preserved",
])
def test_identity_mismatch_fails_closed(field):
    assert evaluate_cancellation(replace(evidence(), **{field: False})).outcome is CancellationEligibility.IDENTITY_MISMATCH


@pytest.mark.parametrize("field", ["build_id", "project_id", "location"])
def test_missing_provider_identity_fails_closed(field):
    assert evaluate_cancellation(replace(evidence(), **{field: None})).outcome is CancellationEligibility.IDENTITY_MISMATCH


@pytest.mark.parametrize("status", [s for s in ProviderObservationStatus if s is not ProviderObservationStatus.WORKING])
def test_every_non_working_status_is_non_cancellable(status):
    assert evaluate_cancellation(evidence(observation_status=status)).outcome is CancellationEligibility.NOT_RUNNING


def test_ambiguity_fails_closed():
    assert evaluate_cancellation(evidence(identity_ambiguous=True)).outcome is CancellationEligibility.AMBIGUOUS


def test_prior_accepted_request_is_not_repeated():
    assert evaluate_cancellation(evidence(prior_request_accepted=True)).outcome is CancellationEligibility.CANCELLATION_ALREADY_REQUESTED


def test_request_calls_client_at_most_once():
    client = FakeClient()
    operation = SupersededBuildCancellation(client=client)
    first = operation.request(evidence(), invocation_id="cloud-build-invocation:1232")
    second = operation.request(evidence(), invocation_id="cloud-build-invocation:1232")
    assert first == CloudBuildCancellationOutcome(accepted=True)
    assert second is None
    assert len(client.calls) == 1


def test_accepted_request_does_not_claim_terminal_state():
    outcome = SupersededBuildCancellation(client=FakeClient()).request(evidence(), invocation_id="cloud-build-invocation:1232")
    assert outcome.accepted is True
    assert not hasattr(outcome, "terminal_status")


def test_ineligible_evidence_makes_zero_cancel_calls():
    client = FakeClient()
    operation = SupersededBuildCancellation(client=client)
    assert operation.request(evidence(observation_status=ProviderObservationStatus.SUCCESS), invocation_id="cloud-build-invocation:1232") is None
    assert client.calls == []


def test_contract_contains_no_retry_or_lease_release_authority():
    client = FakeClient()
    operation = SupersededBuildCancellation(client=client)
    assert not hasattr(operation, "retry")
    assert not hasattr(operation, "release_lease")
