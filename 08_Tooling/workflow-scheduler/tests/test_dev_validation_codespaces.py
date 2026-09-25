from __future__ import annotations

import json
import subprocess
from pathlib import Path

from workflow_scheduler.governance.dev_validation import (
    REPOSITORY,
    VALIDATION_ID,
    build_dev_validation_request,
)
from workflow_scheduler.governance.dev_validation_codespaces import (
    APPROVED_CODESPACE_NAME,
    APPROVED_CODESPACE_PROFILE_ID,
    APPROVED_CODESPACE_SURFACE_ID,
    _RUN_TIMEOUT_SECONDS,
    run_dev_validation_over_codespaces,
    select_codespaces_dev_validation,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    IssueCommentIngressResult,
)

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40
BRANCH = "agent/2931-codespaces-test"


def _ingress(validation_id: str = VALIDATION_ID) -> IssueCommentIngressResult:
    return IssueCommentIngressResult(
        schema_version="1.0",
        status="accepted",
        reason="accepted-dev-validation-envelope",
        repository=REPOSITORY,
        issue_number=2931,
        comment_id=1,
        actor="Blummer92",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-trigger:test",
        run_attempt=1,
        dev_validation_branch_or_none=BRANCH,
        dev_validation_sha_or_none=SHA,
        dev_validation_id_or_none=validation_id,
    )


def _codespace_payload(*, state: str = "Available") -> str:
    return json.dumps(
        {
            "name": APPROVED_CODESPACE_NAME,
            "state": state,
            "owner": {"login": "Blummer92"},
            "repository": {"full_name": REPOSITORY},
        }
    )


def test_missing_read_only_credential_falls_back_without_probe(monkeypatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    calls = []

    def run(argv, *, timeout):
        calls.append(argv)
        raise AssertionError("gh must not run without a credential")

    route, request = select_codespaces_dev_validation(_ingress(), run=run)
    assert request is not None
    assert route["selected"] is False
    assert route["reason_codes"] == ["codespaces-credential-unavailable"]
    assert route["lifecycle_mutation_authorized"] is False
    assert calls == []


def test_unqualified_validation_profile_falls_back_before_codespaces_probe(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    calls = []

    def run(argv, *, timeout):
        calls.append(argv)
        raise AssertionError("unsupported profiles must not probe Codespaces")

    route, request = select_codespaces_dev_validation(
        _ingress("workflow-scheduler"), run=run
    )
    assert request is not None
    assert route["selected"] is False
    assert route["reason_codes"] == ["codespaces-profile-not-qualified"]
    assert calls == []


def test_stopped_codespace_falls_back_without_lifecycle_mutation(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    calls = []

    def run(argv, *, timeout):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout=_codespace_payload(state="Shutdown"), stderr=""
        )

    route, _ = select_codespaces_dev_validation(_ingress(), run=run)
    assert route["selected"] is False
    assert route["reason_codes"] == ["codespaces-not-available"]
    assert route["state"] == "Shutdown"
    assert route["lifecycle_mutation_authorized"] is False
    assert len(calls) == 1
    assert calls[0][:2] == ("gh", "api")
    assert all("start" not in part and "stop" not in part for part in calls[0])


def test_exact_running_codespace_is_selected(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(
            argv, 0, stdout=_codespace_payload(), stderr=""
        )

    route, request = select_codespaces_dev_validation(_ingress(), run=run)
    assert request is not None
    assert route["selected"] is True
    assert route["reason_codes"] == ["codespaces-capable"]
    assert route["codespace_name"] == APPROVED_CODESPACE_NAME
    assert route["credential_permission"] == "codespaces:read"
    assert route["lifecycle_mutation_authorized"] is False


def test_codespace_identity_mismatch_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")

    def run(argv, *, timeout):
        payload = json.loads(_codespace_payload())
        payload["repository"]["full_name"] = "Blummer92/not-agent-os"
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(payload), stderr=""
        )

    route, _ = select_codespaces_dev_validation(_ingress(), run=run)
    assert route["selected"] is False
    assert route["reason_codes"] == ["codespaces-identity-mismatch"]


def test_successful_codespaces_validation_uses_fixed_ssh_target() -> None:
    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )
    payload = {
        "schema_version": "1.0",
        "status": "success",
        "reason_codes": ["validation-passed"],
        "repository": REPOSITORY,
        "issue_number": 2931,
        "branch": BRANCH,
        "tested_sha": SHA,
        "validation_id": VALIDATION_ID,
        "request_id": request.request_id,
        "exit_code": 0,
        "stdout_tail": "",
        "stderr_tail": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "cleanup_complete": True,
        "workspace_side_effects_performed": True,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "environment_health_evidence_id": "sha256:" + ("b" * 64),
    }
    stdout = (
        "noise\n"
        "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN===\n"
        + json.dumps(payload)
        + "\n===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END===\n"
    )
    calls = []

    def run(argv, *, timeout):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    evidence = run_dev_validation_over_codespaces(request, run=run)
    assert evidence["status"] == "success"
    assert evidence["cleanup_complete"] is True
    assert evidence["execution_surface_id"] == APPROVED_CODESPACE_SURFACE_ID
    assert len(calls) == 1
    argv = calls[0]
    assert argv[:5] == (
        "gh",
        "codespace",
        "ssh",
        "-c",
        APPROVED_CODESPACE_NAME,
    )
    assert argv[5:8] == ("--", "python3", "-c")
    assert "start" not in argv
    assert "stop" not in argv
    assert "delete" not in argv
    assert "export" not in argv


def test_codespaces_ssh_failure_is_fail_closed_and_bounded() -> None:
    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="x" * 5000
        )

    evidence = run_dev_validation_over_codespaces(request, run=run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "dev-validation-codespaces-ssh-failed"
    ]
    assert evidence["ssh_exit_code"] == 1
    assert len(evidence["ssh_stderr_tail"]) == 4096
    assert evidence["ssh_stderr_truncated"] is True


def test_codespaces_transport_timeout_returns_bounded_evidence() -> None:
    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )

    def run(argv, *, timeout):
        assert timeout == _RUN_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(
            argv,
            timeout,
            output="o" * 5000,
            stderr="e" * 5000,
        )

    evidence = run_dev_validation_over_codespaces(request, run=run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "dev-validation-codespaces-transport-timeout"
    ]
    assert evidence["ssh_exit_code"] is None
    assert evidence["transport_timeout_seconds"] == _RUN_TIMEOUT_SECONDS
    assert len(evidence["ssh_stdout_tail"]) == 4096
    assert evidence["ssh_stdout_truncated"] is True
    assert len(evidence["ssh_stderr_tail"]) == 4096
    assert evidence["ssh_stderr_truncated"] is True


def test_codespaces_result_identity_mismatch_is_rejected() -> None:
    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )
    payload = {
        "schema_version": "1.0",
        "status": "success",
        "reason_codes": ["validation-passed"],
        "repository": REPOSITORY,
        "issue_number": 2931,
        "branch": BRANCH,
        "tested_sha": "b" * 40,
        "validation_id": VALIDATION_ID,
        "request_id": request.request_id,
        "exit_code": 0,
        "stdout_tail": "",
        "stderr_tail": "",
        "cleanup_complete": True,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "environment_health_evidence_id": "sha256:" + ("b" * 64),
    }
    stdout = (
        "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN===\n"
        + json.dumps(payload)
        + "\n===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END===\n"
    )

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    evidence = run_dev_validation_over_codespaces(request, run=run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "dev-validation-codespaces-evidence-identity-mismatch"
    ]


def test_governed_ingress_skips_gce_only_for_selected_codespaces_route() -> None:
    workflow = (
        ROOT / ".github/workflows/agent-os-governed-invocation.yml"
    ).read_text(encoding="utf-8")
    selected_guard = (
        "steps.transport.outputs.accepted == 'true' && "
        "steps.codespaces_diagnostic.outputs.handled != 'true' && "
        "steps.codespaces.outputs.selected != 'true'"
    )
    assert "Attempt read-only Codespaces developer validation" in workflow
    assert "secrets.AGENT_OS_CODESPACES_TOKEN" in workflow
    assert selected_guard in workflow
    assert "Invoke exact governed GCE control path" in workflow
    assert (
        "steps.codespaces.outputs.selected != 'true' }}"
        in workflow
    )
