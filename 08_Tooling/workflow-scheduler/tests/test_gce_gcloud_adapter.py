from __future__ import annotations

import json
from pathlib import Path

import pytest

import workflow_scheduler.governance.gce_gcloud_adapter as live
from workflow_scheduler.governance.gce_control_path import HostInvocationEvidence, VmState
from workflow_scheduler.governance.github_issue_comment_ingress import IssueCommentIngressResult

HANDOFF = "executor-handoff:" + "a" * 64


def ingress(**overrides: object) -> IssueCommentIngressResult:
    values = dict(
        schema_version="1.0",
        status="accepted",
        reason="accepted-envelope",
        repository="Blummer92/agent-os",
        issue_number=1217,
        comment_id=10,
        actor="Blummer92",
        handoff_id_or_none=HANDOFF,
        logical_trigger_id_or_none="issue-comment-trigger:" + "b" * 64,
        run_attempt=1,
    )
    values.update(overrides)
    return IssueCommentIngressResult(**values)


class FakeAdapter:
    def __init__(self, *, state=VmState.RUNNING, clean_terminal=False):
        self.state = state
        self.clean_terminal = clean_terminal
        self.calls: list[str] = []

    def observe_state(self, resource):
        self.calls.append("observe")
        return self.state

    def start(self, resource):
        self.calls.append("start")
        return True

    def wait_until_running(self, resource):
        self.calls.append("wait")
        return VmState.RUNNING

    def probe_ready(self, resource):
        self.calls.append("probe")
        return True

    def invoke(self, resource, argv):
        self.calls.append("invoke")
        assert argv == (
            "/usr/local/libexec/agent-os-governed-resume",
            "--handoff-id",
            HANDOFF,
        )
        if self.clean_terminal:
            return HostInvocationEvidence(
                invoked=True,
                accepted=True,
                scheduler_invocation_id="scheduler:1",
                execution_id="execution:1",
                terminal_status="succeeded",
                termination_confirmed=True,
                lease_released=True,
                cleanup_complete=True,
            )
        return HostInvocationEvidence(
            invoked=True,
            accepted=True,
            scheduler_invocation_id="scheduler:1",
            execution_id="execution:1",
            terminal_status="termination-uncertain",
        )

    def stop(self, resource):
        self.calls.append("stop")
        raise AssertionError("first activation must never stop the VM")


def claims(**overrides: str) -> dict[str, str]:
    values = {
        "repository": "Blummer92/agent-os",
        "repository_owner": "Blummer92",
        "workflow_ref": live.WORKFLOW_REF,
        "ref": "refs/heads/main",
        "aud": live.WIF_PROVIDER,
    }
    values.update(overrides)
    return values


def test_live_binding_invokes_once_and_withholds_shutdown() -> None:
    adapter = FakeAdapter()
    result = live.execute_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.calls == ["observe", "probe", "invoke"]
    assert result["control"]["host_accepted"] is True
    assert result["control"]["shutdown_issued"] is False
    assert result["control"]["retry_attempted"] is False


def test_clean_terminal_evidence_still_never_calls_stop_in_first_activation() -> None:
    adapter = FakeAdapter(clean_terminal=True)
    result = live.execute_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.calls == ["observe", "probe", "invoke"]
    assert result["control"]["status"] == "accepted"
    assert result["control"]["shutdown_eligible"] is True
    assert result["control"]["shutdown_issued"] is False
    assert "shutdown-withheld" in result["control"]["reason_codes"]


def test_stopped_vm_starts_once_before_invocation() -> None:
    adapter = FakeAdapter(state=VmState.STOPPED)
    live.execute_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.calls == ["observe", "start", "wait", "probe", "invoke"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("repository", "other/repo"),
        ("repository_owner", "other"),
        ("workflow_ref", "other.yml@refs/heads/main"),
        ("ref", "refs/heads/other"),
        ("aud", "other-audience"),
    ],
)
def test_wrong_claim_blocks_before_adapter(key: str, value: str) -> None:
    adapter = FakeAdapter()
    result = live.execute_transport(ingress(), claims=claims(**{key: value}), adapter=adapter)
    assert result["control"]["reason_codes"] == ["claims-rejected"]
    assert adapter.calls == []


def test_workflow_rerun_cannot_create_control_binding() -> None:
    with pytest.raises(ValueError, match="workflow reruns"):
        live.execute_transport(ingress(run_attempt=2), claims=claims(), adapter=FakeAdapter())


def test_adapter_has_no_stop_command_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, *, timeout=60):
        calls.append(tuple(argv))
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    adapter = live.GcloudIapAdapter()
    assert adapter.stop(live.RESOURCE) is False
    assert calls == []


def test_probe_command_is_fixed_and_iap_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, *, timeout=60):
        calls.append(tuple(argv))
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    assert live.GcloudIapAdapter().probe_ready(live.RESOURCE) is True
    command = calls[0]
    assert "--tunnel-through-iap" in command
    assert command[-1] == "test -x /usr/local/libexec/agent-os-governed-resume"


def test_invoke_rejects_noncanonical_argv_without_gcloud() -> None:
    adapter = live.GcloudIapAdapter()
    with pytest.raises(live.GcloudCommandError, match="non-canonical"):
        adapter.invoke(live.RESOURCE, ("sh", "-c", "whoami"))


def test_invoke_rejects_handoff_shell_injection_without_gcloud() -> None:
    adapter = live.GcloudIapAdapter()
    with pytest.raises(live.GcloudCommandError, match="handoff"):
        adapter.invoke(
            live.RESOURCE,
            (
                "/usr/local/libexec/agent-os-governed-resume",
                "--handoff-id",
                HANDOFF + ";whoami",
            ),
        )


def test_transport_file_drops_authority_fields(tmp_path: Path) -> None:
    payload = ingress().to_dict()
    path = tmp_path / "transport.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = live._ingress_from_file(path)
    assert loaded.execution_authorized is False
    assert loaded.scheduler_invoked is False
    assert loaded.side_effects_performed is False


def test_frozen_resource_and_provider_are_exact() -> None:
    assert live.RESOURCE.project == "agent-os-502614"
    assert live.RESOURCE.zone == "us-central1-a"
    assert live.RESOURCE.instance == "agent-os-test"
    assert "966859826758" in live.WIF_PROVIDER
    assert "agent-os-github/providers/agent-os-main" in live.WIF_PROVIDER


class DiscoveryAdapter(FakeAdapter):
    def probe_discovery_ready(self, resource):
        self.calls.append("probe-discovery")
        return True

    def discover(self, resource, *, repository, issue_number):
        self.calls.append("discover")
        return {
            "status": "found",
            "reason_codes": ["found"],
            "repository": repository,
            "issue_number": issue_number,
            "matching_descriptor_count": 1,
            "handoff_id": HANDOFF,
            "result_id": "invocation-handoff-discovery:test",
            "execution_authorized": False,
            "scheduler_invoked": False,
            "side_effects_performed": False,
        }


def discovery_ingress() -> IssueCommentIngressResult:
    return ingress(
        reason="accepted-discovery-envelope",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-trigger:" + "c" * 64,
    )


def test_discovery_uses_fixed_host_path_and_never_invokes_scheduler_path() -> None:
    adapter = DiscoveryAdapter()
    result = live.execute_transport(
        discovery_ingress(),
        claims=claims(),
        adapter=adapter,
    )
    assert adapter.calls == ["observe", "probe-discovery", "discover"]
    assert result["discovery"]["status"] == "found"
    assert result["discovery"]["handoff_id"] == HANDOFF
    assert result["discovery"]["execution_authorized"] is False
    assert result["discovery"]["scheduler_invoked"] is False


def test_discovery_wrong_claims_fail_before_host_access() -> None:
    adapter = DiscoveryAdapter()
    result = live.execute_transport(
        discovery_ingress(),
        claims=claims(repository="other/repo"),
        adapter=adapter,
    )
    assert adapter.calls == []
    assert result["discovery"]["status"] == "blocked"
    assert result["discovery"]["handoff_id"] is None
