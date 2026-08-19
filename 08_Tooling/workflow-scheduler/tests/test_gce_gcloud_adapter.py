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
        schema_version="1.1",
        status="accepted",
        reason="accepted-envelope",
        repository="Blummer92/agent-os",
        issue_number=1217,
        comment_id=10,
        actor="Blummer92",
        operation_or_none="resume",
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


DISCOVERY_RESULT = {
    "status": "found",
    "reason_codes": ["found"],
    "repository": "Blummer92/agent-os",
    "issue_number": 1284,
    "matching_descriptor_count": 1,
    "handoff_id": HANDOFF,
    "result_id": "invocation-handoff-discovery:" + "c" * 64,
}


def discovery_ingress(**overrides: object) -> IssueCommentIngressResult:
    values = dict(
        issue_number=1284,
        operation_or_none="discover-handoff",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-discovery-trigger:" + "d" * 64,
    )
    values.update(overrides)
    return ingress(**values)


class FakeDiscoveryAdapter:
    def __init__(self, *, stdout: str | None = None, returncode: int = 0) -> None:
        self.stdout = json.dumps(DISCOVERY_RESULT) if stdout is None else stdout
        self.returncode = returncode
        self.commands: list[str] = []

    def observe_state(self, resource):
        return VmState.RUNNING

    def start(self, resource):
        return True

    def wait_until_running(self, resource):
        return VmState.RUNNING

    def probe_discovery_ready(self, resource):
        self.commands.append("probe")
        return True

    def discover(self, resource, argv):
        return live.GcloudIapAdapter.discover(self, resource, argv)

    def _ssh(self, resource, command):
        self.commands.append(command)

        class Completed:
            pass

        result = Completed()
        result.returncode = self.returncode
        result.stdout = self.stdout
        return result


def test_discovery_probe_targets_the_read_only_entrypoint() -> None:
    adapter = FakeDiscoveryAdapter()
    assert live.GcloudIapAdapter.probe_discovery_ready(adapter, live.RESOURCE) is True
    assert adapter.commands[-1] == (
        "test -x /usr/local/libexec/agent-os-handoff-discovery"
    )


def test_discovery_command_is_the_fixed_entrypoint_with_bounded_arguments() -> None:
    adapter = FakeDiscoveryAdapter()
    evidence = adapter.discover(
        live.RESOURCE,
        (
            "/usr/local/libexec/agent-os-handoff-discovery",
            "--repository",
            "Blummer92/agent-os",
            "--issue-number",
            "1284",
        ),
    )
    assert adapter.commands[-1] == (
        "/usr/local/libexec/agent-os-handoff-discovery "
        "--repository Blummer92/agent-os --issue-number 1284"
    )
    assert evidence.handoff_id == HANDOFF
    assert evidence.status == "found"


@pytest.mark.parametrize(
    "argv",
    [
        ("/usr/local/libexec/agent-os-governed-resume", "--repository", "a/b", "--issue-number", "1"),
        ("/bin/sh", "--repository", "a/b", "--issue-number", "1"),
        ("/usr/local/libexec/agent-os-handoff-discovery", "--store-root", "/etc", "--issue-number", "1"),
        ("/usr/local/libexec/agent-os-handoff-discovery", "--repository", "a/b; rm -rf /", "--issue-number", "1"),
        ("/usr/local/libexec/agent-os-handoff-discovery", "--repository", "a/b", "--issue-number", "0"),
        ("/usr/local/libexec/agent-os-handoff-discovery", "--repository", "a/b", "--issue-number", "1x"),
        ("/usr/local/libexec/agent-os-handoff-discovery", "--repository", "a/b"),
    ],
)
def test_noncanonical_discovery_argv_never_reaches_the_host(argv) -> None:
    adapter = FakeDiscoveryAdapter()
    with pytest.raises(live.GcloudCommandError):
        adapter.discover(live.RESOURCE, argv)
    assert adapter.commands == []


def test_nonjson_discovery_output_fails_closed() -> None:
    adapter = FakeDiscoveryAdapter(stdout="not json")
    with pytest.raises(live.GcloudCommandError):
        adapter.discover(
            live.RESOURCE,
            (
                "/usr/local/libexec/agent-os-handoff-discovery",
                "--repository",
                "Blummer92/agent-os",
                "--issue-number",
                "1284",
            ),
        )


def test_discovery_transport_returns_bounded_nonauthorizing_evidence() -> None:
    evidence = live.execute_discovery_transport(
        discovery_ingress(),
        claims=claims(),
        adapter=FakeDiscoveryAdapter(),
    )
    assert evidence["operation"] == "discover-handoff"
    discovery = evidence["discovery"]
    assert discovery["discovery_status"] == "found"
    assert discovery["handoff_id"] == HANDOFF
    for key in (
        "execution_authorized",
        "scheduler_invoked",
        "lease_acquired",
        "handoff_persisted",
        "checkpoint_store_written",
        "github_writes_authorized",
        "merge_authorized",
        "issue_closure_authorized",
    ):
        assert discovery[key] is False


def test_replayed_discovery_reuses_the_same_request_identity() -> None:
    first = live.execute_discovery_transport(
        discovery_ingress(comment_id=1), claims=claims(), adapter=FakeDiscoveryAdapter()
    )
    second = live.execute_discovery_transport(
        discovery_ingress(comment_id=2), claims=claims(), adapter=FakeDiscoveryAdapter()
    )
    assert first["discovery"]["request_id"] == second["discovery"]["request_id"]
    assert first["discovery"]["handoff_id"] == second["discovery"]["handoff_id"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"operation_or_none": "resume", "handoff_id_or_none": HANDOFF},
        {"handoff_id_or_none": HANDOFF},
        {"status": "ignored"},
        {"run_attempt": 2},
        {"logical_trigger_id_or_none": None},
    ],
)
def test_discovery_transport_rejects_noncanonical_ingress(overrides) -> None:
    with pytest.raises(ValueError):
        live.execute_discovery_transport(
            discovery_ingress(**overrides),
            claims=claims(),
            adapter=FakeDiscoveryAdapter(),
        )


def test_discovery_never_binds_a_governed_invocation_or_reaches_resume() -> None:
    evidence = live.execute_discovery_transport(
        discovery_ingress(), claims=claims(), adapter=FakeDiscoveryAdapter()
    )
    assert "binding" not in evidence
    assert "control" not in evidence


def test_discovery_ingress_can_never_enter_the_resume_transport() -> None:
    with pytest.raises(ValueError, match="resume operation"):
        live.execute_transport(
            discovery_ingress(), claims=claims(), adapter=FakeAdapter()
        )
