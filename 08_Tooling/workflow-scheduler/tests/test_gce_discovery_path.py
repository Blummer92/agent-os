"""Focused tests for the #1284 read-only handoff-discovery transport."""

from __future__ import annotations

import pytest

from workflow_scheduler.governance.gce_control_path import (
    FIXED_DISCOVERY_ENTRYPOINT,
    FIXED_ENTRYPOINT,
    ControlPathReason,
    ControlPathStatus,
    GceResourceTuple,
    HostDiscoveryEvidence,
    OidcTrustPolicy,
    VmState,
    fixed_discovery_argv,
    run_gce_discovery_path,
)

REPOSITORY = "Blummer92/agent-os"
ISSUE = 1284
HANDOFF = "executor-handoff:" + "a" * 64
RESOURCE = GceResourceTuple(
    project="agent-os-502614", zone="us-central1-a", instance="agent-os-test"
)
POLICY = OidcTrustPolicy(
    repository=REPOSITORY,
    repository_owner="Blummer92",
    workflow_ref="Blummer92/agent-os/.github/workflows/x.yml@refs/heads/main",
    ref="refs/heads/main",
    audience="//iam.googleapis.com/projects/1/x",
)
CLAIMS = {
    "repository": POLICY.repository,
    "repository_owner": POLICY.repository_owner,
    "workflow_ref": POLICY.workflow_ref,
    "ref": POLICY.ref,
    "aud": POLICY.audience,
}


def evidence(**overrides: object) -> HostDiscoveryEvidence:
    values: dict[str, object] = {
        "invoked": True,
        "status": "found",
        "reason_codes": ("found",),
        "repository": REPOSITORY,
        "issue_number": ISSUE,
        "matching_descriptor_count": 1,
        "handoff_id": HANDOFF,
        "result_id": "invocation-handoff-discovery:" + "c" * 64,
    }
    values.update(overrides)
    return HostDiscoveryEvidence(**values)


_DEFAULT = object()


class FakeAdapter:
    def __init__(
        self,
        *,
        result: object = _DEFAULT,
        state: VmState = VmState.RUNNING,
        ready: bool = True,
    ) -> None:
        self.result = evidence() if result is _DEFAULT else result
        self.state = state
        self.ready = ready
        self.calls: list[str] = []
        self.argv: tuple[str, ...] | None = None

    def observe_state(self, resource):
        self.calls.append("observe")
        return self.state

    def start(self, resource):
        self.calls.append("start")
        return True

    def wait_until_running(self, resource):
        self.calls.append("wait")
        return VmState.RUNNING

    def probe_discovery_ready(self, resource):
        self.calls.append("probe-discovery")
        return self.ready

    def discover(self, resource, argv):
        self.calls.append("discover")
        self.argv = argv
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def run(adapter: FakeAdapter, *, repository: str = REPOSITORY, issue: int = ISSUE):
    return run_gce_discovery_path(
        request_id="gce-discovery-request:test",
        claims=CLAIMS,
        trust_policy=POLICY,
        resource=RESOURCE,
        expected_resource=RESOURCE,
        repository=repository,
        issue_number=issue,
        adapter=adapter,
    )


def assert_no_execution_authority(result) -> None:
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.lease_acquired is False
    assert result.handoff_persisted is False
    assert result.checkpoint_store_written is False
    assert result.retry_attempted is False
    assert result.arbitrary_command_authorized is False
    assert result.github_writes_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False


def test_unique_descriptor_returns_the_existing_handoff_without_execution() -> None:
    adapter = FakeAdapter()
    result = run(adapter)
    assert result.status is ControlPathStatus.ACCEPTED
    assert result.reason_codes == (ControlPathReason.DISCOVERY_COMPLETED,)
    assert result.discovery_status == "found"
    assert result.handoff_id == HANDOFF
    assert result.matching_descriptor_count == 1
    assert_no_execution_authority(result)


def test_discovery_uses_its_own_fixed_entrypoint_and_bounded_argv() -> None:
    adapter = FakeAdapter()
    run(adapter)
    assert adapter.argv == (
        FIXED_DISCOVERY_ENTRYPOINT,
        "--repository",
        REPOSITORY,
        "--issue-number",
        str(ISSUE),
    )
    assert FIXED_DISCOVERY_ENTRYPOINT != FIXED_ENTRYPOINT
    assert FIXED_ENTRYPOINT not in adapter.argv


def test_zero_matches_is_accepted_not_found_with_no_handoff() -> None:
    result = run(
        FakeAdapter(
            result=evidence(
                status="not-found",
                reason_codes=("no-matching-descriptor",),
                matching_descriptor_count=0,
                handoff_id=None,
            )
        )
    )
    assert result.status is ControlPathStatus.ACCEPTED
    assert result.discovery_status == "not-found"
    assert result.handoff_id is None
    assert_no_execution_authority(result)


def test_multiple_matches_are_needs_decision_and_expose_no_handoff() -> None:
    result = run(
        FakeAdapter(
            result=evidence(
                status="needs-decision",
                reason_codes=("multiple-matching-descriptors",),
                matching_descriptor_count=4,
                handoff_id=None,
            )
        )
    )
    assert result.status is ControlPathStatus.NEEDS_DECISION
    assert result.discovery_status == "needs-decision"
    assert result.matching_descriptor_count == 4
    assert result.handoff_id is None


def test_corrupt_or_unavailable_store_is_needs_decision() -> None:
    result = run(
        FakeAdapter(
            result=evidence(
                status="needs-decision",
                reason_codes=("descriptor-integrity-unverified",),
                matching_descriptor_count=None,
                handoff_id=None,
                result_id=None,
            )
        )
    )
    assert result.status is ControlPathStatus.NEEDS_DECISION
    assert result.discovery_reason_codes == ("descriptor-integrity-unverified",)
    assert result.handoff_id is None


def test_unusable_host_evidence_fails_closed() -> None:
    for broken in (RuntimeError("ssh failed"), "not-evidence", None):
        adapter = FakeAdapter(result=broken)
        result = run(adapter)
        assert result.status is ControlPathStatus.NEEDS_DECISION
        assert result.reason_codes == (
            ControlPathReason.DISCOVERY_EVIDENCE_UNAVAILABLE,
        )
        assert result.handoff_id is None


def test_host_answer_about_a_different_issue_is_rejected() -> None:
    result = run(FakeAdapter(result=evidence(issue_number=999)))
    assert result.status is ControlPathStatus.NEEDS_DECISION
    assert result.reason_codes == (ControlPathReason.DISCOVERY_EVIDENCE_UNAVAILABLE,)
    assert result.handoff_id is None


def test_host_answer_about_a_different_repository_is_rejected() -> None:
    result = run(FakeAdapter(result=evidence(repository="someone/else")))
    assert result.status is ControlPathStatus.NEEDS_DECISION
    assert result.handoff_id is None


def test_rejected_claims_block_before_the_adapter_is_touched() -> None:
    adapter = FakeAdapter()
    result = run_gce_discovery_path(
        request_id="req",
        claims={"repository": "other/repo"},
        trust_policy=POLICY,
        resource=RESOURCE,
        expected_resource=RESOURCE,
        repository=REPOSITORY,
        issue_number=ISSUE,
        adapter=adapter,
    )
    assert result.status is ControlPathStatus.BLOCKED
    assert result.reason_codes == (ControlPathReason.CLAIMS_REJECTED,)
    assert adapter.calls == []


def test_resource_mismatch_blocks_before_the_adapter_is_touched() -> None:
    adapter = FakeAdapter()
    result = run_gce_discovery_path(
        request_id="req",
        claims=CLAIMS,
        trust_policy=POLICY,
        resource=GceResourceTuple(project="p", zone="z", instance="other"),
        expected_resource=RESOURCE,
        repository=REPOSITORY,
        issue_number=ISSUE,
        adapter=adapter,
    )
    assert result.status is ControlPathStatus.BLOCKED
    assert result.reason_codes == (ControlPathReason.RESOURCE_MISMATCH,)
    assert adapter.calls == []


@pytest.mark.parametrize(
    "repository,issue",
    [
        ("not-a-repository", ISSUE),
        ("Blummer92/agent-os; rm -rf /", ISSUE),
        (REPOSITORY, 0),
        (REPOSITORY, -1),
    ],
)
def test_noncanonical_identity_blocks_before_the_adapter(repository, issue) -> None:
    adapter = FakeAdapter()
    result = run(adapter, repository=repository, issue=issue)
    assert result.status is ControlPathStatus.BLOCKED
    assert result.reason_codes == (ControlPathReason.DISCOVERY_IDENTITY_INVALID,)
    assert adapter.calls == []


def test_stopped_host_is_started_once_and_never_stopped() -> None:
    adapter = FakeAdapter(state=VmState.STOPPED)
    result = run(adapter)
    assert result.start_issued is True
    assert result.side_effects_performed == ("vm-start", "discovery-invocation")
    assert adapter.calls.count("start") == 1
    assert not hasattr(adapter, "stop_called")
    assert result.status is ControlPathStatus.ACCEPTED


def test_unready_host_blocks_without_invoking_discovery() -> None:
    adapter = FakeAdapter(ready=False)
    result = run(adapter)
    assert result.status is ControlPathStatus.BLOCKED
    assert result.reason_codes == (ControlPathReason.HOST_NOT_READY,)
    assert "discover" not in adapter.calls
    assert result.host_invoked is False


def test_transitional_host_blocks_without_invoking_discovery() -> None:
    adapter = FakeAdapter(state=VmState.STOPPING)
    result = run(adapter)
    assert result.status is ControlPathStatus.BLOCKED
    assert result.reason_codes == (ControlPathReason.VM_TRANSITIONAL,)
    assert "discover" not in adapter.calls


def test_replayed_discovery_is_deterministic_and_creates_no_second_authority() -> None:
    first = run(FakeAdapter())
    second = run(FakeAdapter())
    assert first.result_id == second.result_id
    assert first.handoff_id == second.handoff_id == HANDOFF
    assert first.to_dict() == second.to_dict()
    assert_no_execution_authority(first)
    assert_no_execution_authority(second)


def test_result_never_claims_authority_even_when_found() -> None:
    payload = run(FakeAdapter()).to_dict()
    for key in (
        "execution_authorized",
        "scheduler_invoked",
        "lease_acquired",
        "handoff_persisted",
        "checkpoint_store_written",
        "retry_attempted",
        "arbitrary_command_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "issue_closure_authorized",
    ):
        assert payload[key] is False


def test_found_evidence_requires_exactly_one_canonical_descriptor() -> None:
    with pytest.raises(ValueError):
        evidence(matching_descriptor_count=2)
    with pytest.raises(ValueError):
        evidence(handoff_id=None)
    with pytest.raises(ValueError):
        evidence(handoff_id="executor-handoff:not-hex")
    with pytest.raises(ValueError):
        evidence(result_id=None)


def test_non_found_evidence_cannot_carry_a_handoff() -> None:
    with pytest.raises(ValueError):
        evidence(status="not-found", matching_descriptor_count=0)
    with pytest.raises(ValueError):
        evidence(status="needs-decision", matching_descriptor_count=3)


def test_unknown_discovery_status_is_rejected() -> None:
    with pytest.raises(ValueError):
        evidence(status="latest")


@pytest.mark.parametrize(
    "repository,issue",
    [("bad", 1), (REPOSITORY, 0), (REPOSITORY, "1")],
)
def test_fixed_discovery_argv_rejects_noncanonical_identity(repository, issue) -> None:
    with pytest.raises(ValueError):
        fixed_discovery_argv(repository, issue)
