from __future__ import annotations

import hashlib
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


def test_oversized_probe_stderr_is_truncated_and_flagged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = InspectionAdapter().inspect_runtime(live.RESOURCE)
    payload["import_probe"]["stderr"] = "x" * (live.MAX_DIAGNOSTIC_STDERR + 500)
    payload["import_probe"]["stderr_truncated"] = False

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["status"] == "observed"
    assert "ssh_exit_code" not in result
    assert len(result["import_probe"]["stderr"]) == live.MAX_DIAGNOSTIC_STDERR
    assert result["import_probe"]["stderr_truncated"] is True


def test_command_failure_returns_bounded_result_with_exit_code_and_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "Traceback (most recent call last):\nImportError: no module\n"

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["inspection-command-failed"]
    assert result["ssh_exit_code"] == 1
    assert "ImportError" in result["ssh_stderr"]
    assert result["ssh_stderr_truncated"] is False
    assert result["project"] == live.PROJECT
    assert result["zone"] == live.ZONE
    assert result["instance"] == live.INSTANCE
    assert result["interpreter"] == live.HOST_PYTHON
    assert result["execution_authorized"] is False
    assert result["scheduler_invoked"] is False
    assert result["discovery_invoked"] is False
    assert result["resume_invoked"] is False
    assert result["side_effects_performed"] is False


def test_command_failure_ssh_stderr_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "z" * (live.MAX_DIAGNOSTIC_STDERR + 999)

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert len(result["ssh_stderr"]) == live.MAX_DIAGNOSTIC_STDERR
    assert result["ssh_stderr_truncated"] is True


def test_empty_stdout_returns_bounded_not_json_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["inspection-evidence-not-json"]
    assert result["ssh_exit_code"] == 0
    evidence = result["stdout_evidence"]
    assert evidence["length"] == 0
    assert evidence["empty"] is True
    assert evidence["json_object_span_present"] is False
    assert evidence["leading_text_before_json"] is False
    assert evidence["trailing_text_after_json"] is False
    assert evidence["prefix"] == ""
    assert evidence["prefix_truncated"] is False
    assert evidence["suffix"] == ""
    assert evidence["suffix_truncated"] is False
    assert evidence["sha256"] == hashlib.sha256(b"").hexdigest()


def test_non_json_stdout_returns_bounded_not_json_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = "not json at all"

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = "not json at all"
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["reason_codes"] == ["inspection-evidence-not-json"]
    evidence = result["stdout_evidence"]
    assert evidence["length"] == len(stdout)
    assert evidence["empty"] is False
    assert evidence["json_object_span_present"] is False
    assert evidence["prefix"] == stdout
    assert evidence["prefix_truncated"] is False
    assert evidence["suffix"] == ""
    assert evidence["suffix_truncated"] is False
    assert evidence["sha256"] == hashlib.sha256(stdout.encode()).hexdigest()


def test_banner_then_json_stdout_remains_fail_closed_with_bounded_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_payload = InspectionAdapter().inspect_runtime(live.RESOURCE)
    stdout = "Warning: MOTD banner line before the real output\n" + json.dumps(valid_payload)

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = "Warning: MOTD banner line before the real output\n" + json.dumps(valid_payload)
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["inspection-evidence-not-json"]
    evidence = result["stdout_evidence"]
    assert evidence["json_object_span_present"] is True
    assert evidence["leading_text_before_json"] is True
    assert evidence["trailing_text_after_json"] is False
    assert "Warning: MOTD banner line" in evidence["prefix"]
    assert evidence["sha256"] == hashlib.sha256(stdout.encode()).hexdigest()
    # The embedded valid payload must never be silently accepted as authoritative.
    assert "status" not in result or result["status"] == "needs-decision"
    assert "effective_identity" not in result


def test_json_then_trailing_junk_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_payload = InspectionAdapter().inspect_runtime(live.RESOURCE)
    stdout = json.dumps(valid_payload) + "\ntrailing junk after the real output"

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = json.dumps(valid_payload) + "\ntrailing junk after the real output"
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["reason_codes"] == ["inspection-evidence-not-json"]
    evidence = result["stdout_evidence"]
    assert evidence["json_object_span_present"] is True
    assert evidence["leading_text_before_json"] is False
    assert evidence["trailing_text_after_json"] is True
    assert "trailing junk" in evidence["suffix"] or "trailing junk" in evidence["prefix"]


def test_very_large_stdout_is_tightly_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = "x" * 5000

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = "x" * 5000
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    evidence = result["stdout_evidence"]
    assert evidence["length"] == 5000
    assert len(evidence["prefix"]) == live._STDOUT_EVIDENCE_PREFIX_CAP
    assert len(evidence["suffix"]) == live._STDOUT_EVIDENCE_SUFFIX_CAP
    assert evidence["prefix_truncated"] is True
    assert evidence["suffix_truncated"] is True
    assert evidence["sha256"] == hashlib.sha256(stdout.encode()).hexdigest()
    # Total emitted raw content stays tightly bounded regardless of source size.
    assert len(evidence["prefix"]) + len(evidence["suffix"]) <= 2 * live._STDOUT_EVIDENCE_PREFIX_CAP


def test_content_beyond_the_bound_is_never_emitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "SECRET-TOKEN-abc123"
    stdout = ("A" * 250) + secret + ("B" * 250)

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = ("A" * 250) + secret + ("B" * 250)
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert secret not in json.dumps(result)


def test_unprintable_stdout_bytes_are_sanitized_in_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = "before\x00\x01\x02control-bytes-after"

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = "before\x00\x01\x02control-bytes-after"
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    evidence = result["stdout_evidence"]
    assert "\x00" not in evidence["prefix"]
    assert "\x01" not in evidence["prefix"]
    assert "\x02" not in evidence["prefix"]
    assert "before" in evidence["prefix"]
    assert "control-bytes-after" in evidence["prefix"]
    # sha256 still fingerprints the real, unsanitized stdout.
    assert evidence["sha256"] == hashlib.sha256(stdout.encode()).hexdigest()


def test_non_object_payload_returns_bounded_malformed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = json.dumps(["not", "an", "object"])
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["reason_codes"] == ["inspection-evidence-malformed"]


def test_fixed_contract_violation_returns_bounded_result_without_leaking_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = InspectionAdapter().inspect_runtime(live.RESOURCE)
    payload["project"] = "some-other-project"
    payload["python_context"] = {"secret": "leaked-if-echoed"}

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["reason_codes"] == ["inspection-contract-violation"]
    assert "python_context" not in result
    assert "secret" not in json.dumps(result)


def test_malformed_import_probe_shape_returns_bounded_contract_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = InspectionAdapter().inspect_runtime(live.RESOURCE)
    payload["import_probe"] = "not-an-object"

    def fake_run(argv, *, timeout=60):
        class Result:
            returncode = 0
            stdout = json.dumps(payload)
            stderr = ""

        return Result()

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.GcloudIapAdapter().inspect_runtime(live.RESOURCE)

    assert result["reason_codes"] == ["inspection-contract-violation"]


def test_execute_transport_returns_bounded_result_without_raising_on_crash() -> None:
    class CrashingAdapter:
        def observe_state(self, resource):
            return VmState.RUNNING

        def inspect_runtime(self, resource):
            return live._inspection_failure(
                "needs-decision", "inspection-command-failed", exit_code=1, stderr="boom"
            )

    result = live.execute_transport(_ingress(), claims=_claims(), adapter=CrashingAdapter())
    evidence = result["runtime_inspection"]
    assert evidence["reason_codes"] == ["inspection-command-failed"]
    assert evidence["execution_authorized"] is False
    assert evidence["scheduler_invoked"] is False
    assert evidence["discovery_invoked"] is False
    assert evidence["resume_invoked"] is False
    assert evidence["side_effects_performed"] is False
