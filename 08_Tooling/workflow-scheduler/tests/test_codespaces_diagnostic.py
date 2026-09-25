from __future__ import annotations

import json
import subprocess

from workflow_scheduler.governance.codespaces_diagnostic import (
    DIAGNOSTIC_ID,
    _RUN_TIMEOUT_SECONDS,
    run_codespaces_diagnostic,
    select_codespaces_diagnostic,
)
from workflow_scheduler.governance.dev_validation import REPOSITORY
from workflow_scheduler.governance.dev_validation_codespaces import (
    APPROVED_CODESPACE_NAME,
    APPROVED_CODESPACE_PROFILE_ID,
    APPROVED_CODESPACE_SURFACE_ID,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    IssueCommentIngressResult,
)


REQUEST_ID = "canva-cdp-1"


def _ingress() -> IssueCommentIngressResult:
    return IssueCommentIngressResult(
        schema_version="1.0",
        status="accepted",
        reason="accepted-codespaces-diagnostic-envelope",
        repository=REPOSITORY,
        issue_number=2455,
        comment_id=1,
        actor="Blummer92",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-trigger:test",
        run_attempt=1,
        diagnostic_id_or_none=DIAGNOSTIC_ID,
        diagnostic_request_id_or_none=REQUEST_ID,
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


def test_non_diagnostic_ingress_is_not_handled() -> None:
    ingress = _ingress()
    ingress = IssueCommentIngressResult(
        schema_version=ingress.schema_version,
        status="accepted",
        reason="accepted-discovery-envelope",
        repository=ingress.repository,
        issue_number=ingress.issue_number,
        comment_id=ingress.comment_id,
        actor=ingress.actor,
        handoff_id_or_none=None,
        logical_trigger_id_or_none=ingress.logical_trigger_id_or_none,
        run_attempt=1,
    )
    route, request = select_codespaces_diagnostic(ingress)
    assert route["handled"] is False
    assert route["selected"] is False
    assert route["reason_codes"] == ["not-codespaces-diagnostic"]
    assert request is None


def test_missing_credential_is_handled_without_gce_fallback(monkeypatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    calls = []

    def run(argv, *, timeout):
        calls.append(argv)
        raise AssertionError("gh must not run without a credential")

    route, request = select_codespaces_diagnostic(_ingress(), run=run)
    assert request is not None
    assert route["handled"] is True
    assert route["selected"] is False
    assert route["reason_codes"] == ["codespaces-credential-unavailable"]
    assert route["lifecycle_mutation_authorized"] is False
    assert calls == []


def test_available_approved_codespace_is_selected(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(
            argv, 0, stdout=_codespace_payload(), stderr=""
        )

    route, request = select_codespaces_diagnostic(_ingress(), run=run)
    assert request is not None
    assert route["handled"] is True
    assert route["selected"] is True
    assert route["reason_codes"] == ["codespaces-capable"]
    assert route["execution_surface_id"] == APPROVED_CODESPACE_SURFACE_ID
    assert route["credential_permission"] == "codespaces:read"


def test_unavailable_codespace_is_handled_without_lifecycle_mutation(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(
            argv, 0, stdout=_codespace_payload(state="Shutdown"), stderr=""
        )

    route, _ = select_codespaces_diagnostic(_ingress(), run=run)
    assert route["handled"] is True
    assert route["selected"] is False
    assert route["reason_codes"] == ["codespaces-not-available"]
    assert route["state"] == "Shutdown"
    assert route["lifecycle_mutation_authorized"] is False


def test_successful_diagnostic_uses_fixed_ssh_target_and_no_caller_shell() -> None:
    _, request = select_codespaces_diagnostic(
        _ingress(),
        run=lambda argv, timeout: subprocess.CompletedProcess(
            argv, 0, stdout=_codespace_payload(), stderr=""
        ),
    )
    assert request is not None

    payload = {
        "schema_version": "1.0",
        "status": "success",
        "reason_codes": ["diagnostic-observed"],
        "repository": REPOSITORY,
        "issue_number": 2455,
        "diagnostic_id": DIAGNOSTIC_ID,
        "request_id": REQUEST_ID,
        "codespace_name": APPROVED_CODESPACE_NAME,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "environment_health_evidence_id": "sha256:" + ("a" * 64),
        "workspace_head": "b" * 40,
        "workspace_branch": "agent/2307-yarn-signing-recovery-20260925",
        "chrome_process_count": 8,
        "loopback": {"9222": True, "9444": True},
        "cdp": {
            "browser": {
                "product": "Chrome/153.0.8010.12",
                "protocol_version": "1.3",
                "headless": False,
            },
            "target_count": 2,
            "targets": [],
        },
        "cleanup_complete": True,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    stdout = (
        "noise\n"
        "===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-BEGIN===\n"
        + json.dumps(payload)
        + "\n===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-END===\n"
    )
    calls = []

    def run(argv, *, timeout):
        calls.append((argv, timeout))
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    evidence = run_codespaces_diagnostic(request, run=run)
    assert evidence["status"] == "success"
    assert evidence["workspace_side_effects_performed"] is False
    assert evidence["external_side_effects_performed"] is False
    argv, timeout = calls[0]
    assert timeout == _RUN_TIMEOUT_SECONDS
    assert argv[:5] == (
        "gh",
        "codespace",
        "ssh",
        "-c",
        APPROVED_CODESPACE_NAME,
    )
    assert argv[5:8] == ("--", "python3", "-c")
    assert argv[-4:] == (
        "2455",
        DIAGNOSTIC_ID,
        REQUEST_ID,
        APPROVED_CODESPACE_NAME,
    )
    joined = " ".join(argv)
    for forbidden in ("--command", "rm -rf", "http://example", "https://example"):
        assert forbidden not in joined


def test_transport_timeout_returns_bounded_failure_evidence() -> None:
    _, request = select_codespaces_diagnostic(
        _ingress(),
        run=lambda argv, timeout: subprocess.CompletedProcess(
            argv, 0, stdout=_codespace_payload(), stderr=""
        ),
    )
    assert request is not None

    def run(argv, *, timeout):
        raise subprocess.TimeoutExpired(
            argv,
            timeout,
            output="o" * 5000,
            stderr="e" * 5000,
        )

    evidence = run_codespaces_diagnostic(request, run=run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == ["codespaces-diagnostic-transport-timeout"]
    assert evidence["cleanup_complete"] is True
    assert len(evidence["ssh_stdout_tail"]) == 4096
    assert evidence["ssh_stdout_truncated"] is True
    assert len(evidence["ssh_stderr_tail"]) == 4096
    assert evidence["ssh_stderr_truncated"] is True


def test_result_identity_mismatch_is_rejected() -> None:
    _, request = select_codespaces_diagnostic(
        _ingress(),
        run=lambda argv, timeout: subprocess.CompletedProcess(
            argv, 0, stdout=_codespace_payload(), stderr=""
        ),
    )
    assert request is not None

    payload = {
        "schema_version": "1.0",
        "status": "success",
        "reason_codes": ["diagnostic-observed"],
        "repository": REPOSITORY,
        "issue_number": 2455,
        "diagnostic_id": DIAGNOSTIC_ID,
        "request_id": "wrong-request",
        "codespace_name": APPROVED_CODESPACE_NAME,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "environment_health_evidence_id": "sha256:" + ("a" * 64),
        "cleanup_complete": True,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }
    stdout = (
        "===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-BEGIN===\n"
        + json.dumps(payload)
        + "\n===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-END===\n"
    )

    evidence = run_codespaces_diagnostic(
        request,
        run=lambda argv, timeout: subprocess.CompletedProcess(
            argv, 0, stdout=stdout, stderr=""
        ),
    )
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "codespaces-diagnostic-evidence-identity-mismatch"
    ]
