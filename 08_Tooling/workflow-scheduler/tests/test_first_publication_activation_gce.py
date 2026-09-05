from __future__ import annotations

import dataclasses
import subprocess

import pytest

from workflow_scheduler.governance.gce_gcloud_adapter import (
    ACTIVATION_PROBE_COMMAND,
    RESOURCE,
    WIF_PROVIDER,
    WORKFLOW_REF,
    GcloudCommandError,
    GcloudIapAdapter,
    _activation_command,
    execute_transport,
)
from workflow_scheduler.governance.gce_control_path import VmState
from workflow_scheduler.governance.github_issue_comment_ingress import IssueCommentIngressResult

CAPSULE = "pre-publication-evidence:" + "a" * 64
HANDOFF = "executor-handoff:" + "b" * 64


def ingress(**overrides: object) -> IssueCommentIngressResult:
    value = IssueCommentIngressResult(
        schema_version="1.0",
        status="accepted",
        reason="accepted-first-publication-activation-envelope",
        repository="Blummer92/agent-os",
        issue_number=1239,
        comment_id=1,
        actor="Blummer92",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-trigger:" + "c" * 64,
        run_attempt=1,
        source_capsule_id_or_none=CAPSULE,
    )
    return dataclasses.replace(value, **overrides) if overrides else value


def claims() -> dict[str, object]:
    return {
        "repository": "Blummer92/agent-os",
        "repository_owner": "Blummer92",
        "workflow_ref": WORKFLOW_REF,
        "ref": "refs/heads/main",
        "aud": WIF_PROVIDER,
    }


class Adapter:
    def __init__(self, state: VmState = VmState.RUNNING, *, activation_ready: bool = True) -> None:
        self.state = state
        self.activation_ready = activation_ready
        self.activated: list[str] = []
        self.probed: list[bool] = []

    def observe_state(self, resource):
        assert resource == RESOURCE
        return self.state

    def probe_activation_ready(self, resource):
        assert resource == RESOURCE
        self.probed.append(self.activation_ready)
        return self.activation_ready

    def activate_first_publication(self, resource, *, source_capsule_id):
        assert resource == RESOURCE
        self.activated.append(source_capsule_id)
        return {
            "schema_version": "1.0",
            "source_capsule_id": source_capsule_id,
            "handoff_id": HANDOFF,
            "publication_invoked": True,
            "scheduler_invoked": False,
            "execution_lease_acquired": False,
            "resume_invoked": False,
        }


def test_activation_uses_exact_capsule_once_and_never_resumes() -> None:
    adapter = Adapter()
    result = execute_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.activated == [CAPSULE]
    assert adapter.probed == [True]
    evidence = result["first_publication_activation"]
    assert evidence["source_capsule_id"] == CAPSULE
    assert evidence["handoff_id"] == HANDOFF
    assert evidence["scheduler_invoked"] is False
    assert evidence["execution_lease_acquired"] is False
    assert evidence["resume_invoked"] is False


def test_activation_stops_when_the_activation_module_is_unavailable() -> None:
    adapter = Adapter(activation_ready=False)
    result = execute_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.probed == [False]
    assert adapter.activated == []
    evidence = result["first_publication_activation"]
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == ["activation-entrypoint-unavailable"]


def test_activation_refuses_a_carried_handoff_identity() -> None:
    adapter = Adapter()
    with pytest.raises(ValueError):
        execute_transport(ingress(handoff_id_or_none=HANDOFF), claims=claims(), adapter=adapter)
    assert adapter.activated == []


def test_workflow_rerun_never_executes_activation() -> None:
    adapter = Adapter()
    with pytest.raises(ValueError):
        execute_transport(ingress(run_attempt=2), claims=claims(), adapter=adapter)
    assert adapter.activated == []


def test_activation_command_rejects_a_non_canonical_capsule() -> None:
    assert _activation_command(CAPSULE).endswith(f"--source-capsule-id {CAPSULE}")
    for bad in ("pre-publication-evidence:abc", CAPSULE + " --publish", "executor-handoff:" + "a" * 64):
        with pytest.raises(GcloudCommandError):
            _activation_command(bad)


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=("gcloud",), returncode=0, stdout=stdout, stderr="")


def test_adapter_rejects_activation_evidence_that_crosses_the_execution_boundary() -> None:
    adapter = GcloudIapAdapter()
    payloads = [
        '{"source_capsule_id":"' + CAPSULE + '","scheduler_invoked":true,"execution_lease_acquired":false,"resume_invoked":false}',
        '{"source_capsule_id":"' + CAPSULE + '","scheduler_invoked":false,"execution_lease_acquired":true,"resume_invoked":false}',
        '{"source_capsule_id":"' + CAPSULE + '","scheduler_invoked":false,"execution_lease_acquired":false,"resume_invoked":true}',
        '{"source_capsule_id":"pre-publication-evidence:' + "d" * 64 + '","scheduler_invoked":false,"execution_lease_acquired":false,"resume_invoked":false}',
        "not json",
    ]
    for payload in payloads:
        adapter._ssh = lambda resource, command, _p=payload: _completed(_p)  # type: ignore[method-assign]
        with pytest.raises(GcloudCommandError):
            adapter.activate_first_publication(RESOURCE, source_capsule_id=CAPSULE)


def test_activation_probe_command_only_imports_the_fixed_module() -> None:
    assert ACTIVATION_PROBE_COMMAND == (
        "/usr/bin/python3 -c 'import agent_os_execution_service.first_publication_activation_entrypoint'"
    )


def test_activation_does_not_start_stopped_vm() -> None:
    adapter = Adapter(VmState.STOPPED)
    result = execute_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.activated == []
    evidence = result["first_publication_activation"]
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == ["host-not-running"]
    assert evidence["scheduler_invoked"] is False


def test_activation_rejects_oidc_claim_drift_before_host_call() -> None:
    adapter = Adapter()
    bad = claims(); bad["ref"] = "refs/heads/other"
    result = execute_transport(ingress(), claims=bad, adapter=adapter)
    assert adapter.activated == []
    assert result["first_publication_activation"]["reason_codes"] == ["claims-rejected"]
