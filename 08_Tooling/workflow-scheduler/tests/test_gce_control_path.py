from __future__ import annotations

import ast
from pathlib import Path

import pytest

from workflow_scheduler.governance.gce_control_path import (
    FIXED_ENTRYPOINT,
    ControlPathReason,
    ControlPathStatus,
    GceResourceTuple,
    HostInvocationEvidence,
    OidcTrustPolicy,
    VmState,
    fixed_host_argv,
    run_gce_control_path,
)

RESOURCE = GceResourceTuple(
    project="agent-os-502614",
    zone="us-central1-a",
    instance="agent-os-test",
)
HANDOFF = "executor-handoff:" + "a" * 64
POLICY = OidcTrustPolicy(
    repository="Blummer92/agent-os",
    repository_owner="Blummer92",
    workflow_ref=(
        "Blummer92/agent-os/.github/workflows/"
        "agent-os-governed-invocation.yml@refs/heads/main"
    ),
    ref="refs/heads/main",
    audience=(
        "//iam.googleapis.com/projects/966859826758/locations/global/"
        "workloadIdentityPools/agent-os-github/providers/agent-os-main"
    ),
)
CLAIMS = {
    "repository": POLICY.repository,
    "repository_owner": POLICY.repository_owner,
    "workflow_ref": POLICY.workflow_ref,
    "ref": POLICY.ref,
    "aud": POLICY.audience,
}


class Adapter:
    def __init__(
        self,
        *,
        state=VmState.RUNNING,
        start_ok=True,
        running=VmState.RUNNING,
        ready=True,
        evidence=None,
        stop_ok=True,
    ):
        self.state = state
        self.start_ok = start_ok
        self.running = running
        self.ready = ready
        self.evidence = evidence or HostInvocationEvidence(
            invoked=True,
            accepted=True,
            scheduler_invocation_id="scheduler-invocation:1",
            execution_id="execution:1",
            terminal_status="succeeded",
            termination_confirmed=True,
            lease_released=True,
            cleanup_complete=True,
            evidence_refs=("evidence:1",),
        )
        self.stop_ok = stop_ok
        self.calls = []
        self.argv = None

    def observe_state(self, resource):
        self.calls.append("observe")
        return self.state

    def start(self, resource):
        self.calls.append("start")
        return self.start_ok

    def wait_until_running(self, resource):
        self.calls.append("wait")
        return self.running

    def probe_ready(self, resource):
        self.calls.append("probe")
        return self.ready

    def invoke(self, resource, argv):
        self.calls.append("invoke")
        self.argv = argv
        return self.evidence

    def stop(self, resource):
        self.calls.append("stop")
        return self.stop_ok


def run(adapter=None, **kwargs):
    return run_gce_control_path(
        request_id="control-request:1",
        claims=kwargs.get("claims", CLAIMS),
        trust_policy=POLICY,
        resource=kwargs.get("resource", RESOURCE),
        expected_resource=RESOURCE,
        handoff_id=kwargs.get("handoff_id", HANDOFF),
        adapter=adapter or Adapter(),
    )


def test_valid_running_host_invokes_fixed_entrypoint_and_stops_cleanly():
    adapter = Adapter()
    result = run(adapter)
    assert result.status is ControlPathStatus.ACCEPTED
    assert result.reason_codes == (ControlPathReason.ACCEPTED,)
    assert adapter.calls == ["observe", "probe", "invoke", "stop"]
    assert adapter.argv == (FIXED_ENTRYPOINT, "--handoff-id", HANDOFF)
    assert result.side_effects_performed == ("host-invocation", "vm-stop")
    assert result.shutdown_eligible is True and result.shutdown_issued is True


def test_stopped_host_starts_once_then_invokes():
    adapter = Adapter(state=VmState.STOPPED)
    result = run(adapter)
    assert result.status is ControlPathStatus.ACCEPTED
    assert adapter.calls == ["observe", "start", "wait", "probe", "invoke", "stop"]
    assert result.start_issued is True


@pytest.mark.parametrize(
    "claim", ["repository", "repository_owner", "workflow_ref", "ref", "aud"]
)
def test_wrong_oidc_claim_blocks_before_adapter(claim):
    claims = dict(CLAIMS)
    claims[claim] = "wrong"
    adapter = Adapter()
    result = run(adapter, claims=claims)
    assert result.status is ControlPathStatus.BLOCKED
    assert result.reason_codes == (ControlPathReason.CLAIMS_REJECTED,)
    assert adapter.calls == []


def test_wrong_resource_blocks_before_adapter():
    adapter = Adapter()
    other = GceResourceTuple(
        project=RESOURCE.project,
        zone=RESOURCE.zone,
        instance="other",
    )
    result = run(adapter, resource=other)
    assert result.reason_codes == (ControlPathReason.RESOURCE_MISMATCH,)
    assert adapter.calls == []


@pytest.mark.parametrize(
    "handoff",
    [
        "",
        "executor-handoff:abc",
        "executor-handoff:" + "A" * 64,
        HANDOFF + ";id",
    ],
)
def test_malformed_handoff_blocks_before_adapter(handoff):
    adapter = Adapter()
    result = run(adapter, handoff_id=handoff)
    assert result.reason_codes == (ControlPathReason.HANDOFF_INVALID,)
    assert adapter.calls == []


def test_fixed_argv_rejects_shell_or_extra_text():
    with pytest.raises(ValueError):
        fixed_host_argv(HANDOFF + " && whoami")
    assert fixed_host_argv(HANDOFF) == (FIXED_ENTRYPOINT, "--handoff-id", HANDOFF)


@pytest.mark.parametrize(
    "state",
    [
        VmState.STAGING,
        VmState.STOPPING,
        VmState.SUSPENDING,
        VmState.UNKNOWN,
        VmState.UNREACHABLE,
    ],
)
def test_transitional_or_unreachable_host_blocks_without_start_or_invoke(state):
    adapter = Adapter(state=state)
    result = run(adapter)
    assert result.reason_codes == (ControlPathReason.VM_TRANSITIONAL,)
    assert adapter.calls == ["observe"]


def test_start_failure_blocks_without_retry_or_invoke():
    adapter = Adapter(state=VmState.STOPPED, start_ok=False)
    result = run(adapter)
    assert result.reason_codes == (ControlPathReason.VM_START_FAILED,)
    assert adapter.calls == ["observe", "start"]
    assert result.retry_attempted is False


def test_start_that_never_reaches_running_blocks():
    adapter = Adapter(state=VmState.STOPPED, running=VmState.STAGING)
    result = run(adapter)
    assert result.reason_codes == (ControlPathReason.VM_START_FAILED,)
    assert adapter.calls == ["observe", "start", "wait"]


def test_not_ready_blocks_without_invocation():
    adapter = Adapter(ready=False)
    result = run(adapter)
    assert result.reason_codes == (ControlPathReason.HOST_NOT_READY,)
    assert adapter.calls == ["observe", "probe"]


@pytest.mark.parametrize(
    "status", ["termination-uncertain", "cleanup-failed", "release-failed"]
)
def test_uncertain_terminal_evidence_withholds_shutdown(status):
    evidence = HostInvocationEvidence(
        invoked=True,
        accepted=True,
        terminal_status=status,
    )
    adapter = Adapter(evidence=evidence)
    result = run(adapter)
    assert ControlPathReason.SHUTDOWN_WITHHELD in result.reason_codes
    assert "stop" not in adapter.calls
    assert result.shutdown_eligible is False


def test_retained_lease_withholds_shutdown():
    evidence = HostInvocationEvidence(
        invoked=True,
        accepted=True,
        terminal_status="succeeded",
        termination_confirmed=True,
        lease_released=False,
        cleanup_complete=True,
        retained_lease=True,
    )
    adapter = Adapter(evidence=evidence)
    result = run(adapter)
    assert ControlPathReason.SHUTDOWN_WITHHELD in result.reason_codes
    assert "stop" not in adapter.calls


def test_quarantine_withholds_shutdown():
    evidence = HostInvocationEvidence(
        invoked=True,
        accepted=True,
        terminal_status="quarantined",
        quarantined=True,
    )
    adapter = Adapter(evidence=evidence)
    result = run(adapter)
    assert ControlPathReason.SHUTDOWN_WITHHELD in result.reason_codes
    assert "stop" not in adapter.calls


def test_validation_failure_with_clean_terminal_evidence_can_stop():
    evidence = HostInvocationEvidence(
        invoked=True,
        accepted=True,
        terminal_status="validation-failed",
        termination_confirmed=True,
        lease_released=True,
        cleanup_complete=True,
    )
    adapter = Adapter(evidence=evidence)
    result = run(adapter)
    assert result.shutdown_eligible is True
    assert result.shutdown_issued is True


def test_blocked_before_execution_can_stop_only_with_explicit_clean_evidence():
    evidence = HostInvocationEvidence(
        invoked=True,
        accepted=False,
        terminal_status="blocked-before-execution",
        termination_confirmed=True,
        lease_released=True,
        cleanup_complete=True,
    )
    adapter = Adapter(evidence=evidence)
    result = run(adapter)
    assert result.status is ControlPathStatus.BLOCKED
    assert ControlPathReason.HOST_INVOCATION_BLOCKED in result.reason_codes
    assert result.shutdown_issued is True


def test_shutdown_failure_becomes_needs_decision():
    adapter = Adapter(stop_ok=False)
    result = run(adapter)
    assert result.status is ControlPathStatus.NEEDS_DECISION
    assert ControlPathReason.SHUTDOWN_FAILED in result.reason_codes
    assert result.shutdown_issued is False


def test_result_is_non_authorizing_transport_evidence():
    result = run(Adapter())
    assert result.retry_attempted is False
    assert result.arbitrary_command_authorized is False
    assert result.scheduler_authorized_by_transport is False
    assert result.lease_authorized_by_transport is False
    assert result.github_writes_authorized is False
    assert result.merge_authorized is False


def test_module_has_no_direct_external_side_effect_imports_or_calls():
    import workflow_scheduler.governance.gce_control_path as module

    path = Path(module.__file__)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_imports = (
        "subprocess",
        "requests",
        "urllib",
        "socket",
        "google",
        "github",
        "boto",
    )
    assert not any(
        any(token in name.lower() for token in forbidden_imports)
        for name in imported
    )
    for forbidden_call in (
        "subprocess.",
        "os.system(",
        "run_single_issue_pilot(",
        ".acquire(",
        ".release(",
    ):
        assert forbidden_call not in source
