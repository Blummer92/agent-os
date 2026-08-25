from __future__ import annotations

import json

import pytest

import workflow_scheduler.governance.gce_gcloud_adapter as live
from workflow_scheduler.governance.gce_control_path import VmState
from workflow_scheduler.governance.github_issue_comment_ingress import (
    IssueCommentIngressResult,
    admit_issue_comment_event,
)


def _event(body: str) -> dict[str, object]:
    return {
        "action": "created",
        "repository": {"full_name": "Blummer92/agent-os"},
        "issue": {"number": 1398},
        "comment": {"id": 1, "body": body, "user": {"login": "Blummer92"}},
        "sender": {"login": "Blummer92"},
    }


def _ingress() -> IssueCommentIngressResult:
    return admit_issue_comment_event(
        _event("/agent-os inspect-runtime"),
        expected_repository="Blummer92/agent-os",
        allowed_actor="Blummer92",
        run_attempt=1,
    )


def _claims() -> dict[str, str]:
    return {
        "repository": "Blummer92/agent-os",
        "repository_owner": "Blummer92",
        "workflow_ref": live.WORKFLOW_REF,
        "ref": "refs/heads/main",
        "aud": live.WIF_PROVIDER,
    }


def test_exact_trigger_only_is_accepted_and_non_authorizing() -> None:
    accepted = _ingress()
    assert accepted.reason == "accepted-runtime-inspection-envelope"
    assert accepted.handoff_id_or_none is None
    assert accepted.execution_authorized is False
    assert accepted.scheduler_invoked is False
    for body in (
        "/agent-os inspect-runtime ",
        " /agent-os inspect-runtime",
        "/agent-os inspect-runtime whoami",
        "/agent-os inspect-runtime; id",
    ):
        rejected = admit_issue_comment_event(
            _event(body),
            expected_repository="Blummer92/agent-os",
            allowed_actor="Blummer92",
            run_attempt=1,
        )
        assert (rejected.status, rejected.reason) == ("ignored", "malformed-trigger")


class InspectionAdapter:
    def __init__(self, state: VmState = VmState.RUNNING) -> None:
        self.state = state
        self.calls: list[str] = []

    def observe_state(self, resource):
        self.calls.append("observe")
        return self.state

    def inspect_runtime(self, resource):
        self.calls.append("inspect")
        return {
            "schema_version": "1.0",
            "status": "observed",
            "reason_codes": ["runtime-context-observed"],
            "project": live.PROJECT,
            "zone": live.ZONE,
            "instance": live.INSTANCE,
            "interpreter": live.HOST_PYTHON,
            "effective_identity": {},
            "python_context": {},
            "package_resolution": {},
            "filesystem_visibility": [],
            "import_probe": {"exit_code": 1, "stderr": "bounded", "stderr_truncated": False},
            "execution_authorized": False,
            "scheduler_invoked": False,
            "discovery_invoked": False,
            "resume_invoked": False,
            "side_effects_performed": False,
        }


def test_inspection_never_starts_vm_or_reaches_scheduler_discovery_resume() -> None:
    adapter = InspectionAdapter()
    result = live.execute_transport(_ingress(), claims=_claims(), adapter=adapter)
    assert adapter.calls == ["observe", "inspect"]
    evidence = result["runtime_inspection"]
    assert evidence["scheduler_invoked"] is False
    assert evidence["discovery_invoked"] is False
    assert evidence["resume_invoked"] is False
    assert evidence["side_effects_performed"] is False


def test_stopped_vm_is_not_started_by_diagnostic_mode() -> None:
    adapter = InspectionAdapter(VmState.STOPPED)
    result = live.execute_transport(_ingress(), claims=_claims(), adapter=adapter)
    assert adapter.calls == ["observe"]
    assert result["runtime_inspection"]["reason_codes"] == ["host-not-running"]


def test_fixed_command_uses_iap_and_has_no_comment_or_handoff_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = InspectionAdapter().inspect_runtime(live.RESOURCE)
    calls: list[tuple[str, ...]] = []

    def fake_run(argv, *, timeout=60):
        calls.append(tuple(argv))

        class Result:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)
    command = calls[0]
    assert "--tunnel-through-iap" in command
    assert command[-1] == live.RUNTIME_INSPECTION_COMMAND
    assert command[-1].startswith("/usr/bin/python3 -c ")
    assert "/agent-os" not in command[-1]
    assert "executor-handoff:" not in command[-1]


def test_adapter_rejects_unbounded_probe_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = InspectionAdapter().inspect_runtime(live.RESOURCE)
    payload["import_probe"]["stderr"] = "x" * (live.MAX_DIAGNOSTIC_STDERR + 1)

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    with pytest.raises(live.GcloudCommandError, match="stderr exceeded bound"):
        live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)
