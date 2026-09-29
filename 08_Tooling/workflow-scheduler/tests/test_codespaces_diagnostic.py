from __future__ import annotations

import json
import subprocess
from pathlib import Path

from workflow_scheduler.governance.codespaces_diagnostic import (
    ADOBE_DIAGNOSTIC_ID,
    ADOBE_EXPRESS_URL,
    DIAGNOSTIC_ID,
    _ADOBE_REMOTE_RUNNER_SOURCE,
    _REMOTE_RUNNER_SOURCE,
    _RUN_TIMEOUT_SECONDS,
    _attach_invocation_metadata,
    run_codespaces_diagnostic,
    select_codespaces_diagnostic,
)
from workflow_scheduler.governance.dev_validation import REPOSITORY
from workflow_scheduler.governance.dev_validation_codespaces import (
    APPROVED_CODESPACE_PROFILE_ID,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    IssueCommentIngressResult,
)


REQUEST_ID = "canva-cdp-1"
APPROVED_CODESPACE_NAME = "fluffy-current-agentos-7x9q"
APPROVED_CODESPACE_SURFACE_ID = f"codespace:{APPROVED_CODESPACE_NAME}"
ROOT = Path(__file__).resolve().parents[3]


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
    item = {
        "name": APPROVED_CODESPACE_NAME,
        "state": state,
        "owner": {"login": "Blummer92"},
        "repository": {"full_name": REPOSITORY},
    }
    return json.dumps({"total_count": 1, "codespaces": [item]})


def test_2965_diagnostic_delegates_to_the_shared_current_surface_resolver(monkeypatch) -> None:
    # One decision owner: the diagnostic route must reach the same selection as
    # dev-validation for the same live evidence, including stale-literal masking.
    from workflow_scheduler.governance import codespaces_diagnostic, dev_validation_codespaces

    assert codespaces_diagnostic.resolve_current_codespace is dev_validation_codespaces.resolve_current_codespace
    assert not hasattr(dev_validation_codespaces, "APPROVED_CODESPACE_NAME")
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    stale = {
        "name": "literate-system-j4j4pr9g4q7h45q",
        "state": "Shutdown",
        "owner": {"login": "Blummer92"},
        "repository": {"full_name": REPOSITORY},
    }
    current = json.loads(_codespace_payload())["codespaces"][0]
    stdout = json.dumps({"total_count": 2, "codespaces": [stale, current]})

    route, _ = select_codespaces_diagnostic(
        _ingress(),
        run=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=""),
    )
    assert route["selected"] is True
    assert route["codespace_name"] == APPROVED_CODESPACE_NAME


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

    evidence = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
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

    evidence = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
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
        codespace_name=APPROVED_CODESPACE_NAME,
        run=lambda argv, timeout: subprocess.CompletedProcess(
            argv, 0, stdout=stdout, stderr=""
        ),
    )
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "codespaces-diagnostic-evidence-identity-mismatch"
    ]


def test_workflow_handles_diagnostic_without_gce_fallback() -> None:
    workflow = (
        ROOT / ".github/workflows/agent-os-governed-invocation.yml"
    ).read_text(encoding="utf-8")
    assert "Attempt bounded read-only Codespaces diagnostic" in workflow
    assert "workflow_scheduler.governance.codespaces_diagnostic" in workflow
    assert "steps.codespaces_diagnostic.outputs.handled != 'true'" in workflow
    assert "codespaces-diagnostic-route.json" in workflow
    assert "Diagnostic status:" in workflow
    assert "actions/upload-artifact@v7" in workflow


def test_invocation_metadata_binds_result_to_workflow_artifact(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "36180000000")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    evidence = _attach_invocation_metadata(
        {"status": "success"},
        started_at="2026-09-25T19:30:00Z",
    )
    assert evidence["started_at"] == "2026-09-25T19:30:00Z"
    assert isinstance(evidence["finished_at"], str)
    assert evidence["finished_at"].endswith("Z")
    assert evidence["workflow_run_id"] == 36180000000
    assert evidence["workflow_run_attempt"] == 1
    assert evidence["workflow_name"] == "Agent OS Governed Invocation Ingress"
    assert (
        evidence["workflow_job_name"]
        == "Validate and transport bounded Agent OS invocation"
    )
    assert evidence["artifact_name"] == "agent-os-ingress-36180000000-1"


def test_invocation_metadata_fails_closed_when_not_in_actions(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    evidence = _attach_invocation_metadata(
        {"status": "needs-decision"},
        started_at="2026-09-25T19:30:00Z",
    )
    assert evidence["workflow_run_id"] is None
    assert evidence["workflow_run_attempt"] is None
    assert evidence["artifact_name"] is None



def _adobe_ingress() -> IssueCommentIngressResult:
    base = _ingress()
    return IssueCommentIngressResult(
        schema_version=base.schema_version,
        status=base.status,
        reason=base.reason,
        repository=base.repository,
        issue_number=3094,
        comment_id=base.comment_id,
        actor=base.actor,
        handoff_id_or_none=None,
        logical_trigger_id_or_none=base.logical_trigger_id_or_none,
        run_attempt=1,
        diagnostic_id_or_none=ADOBE_DIAGNOSTIC_ID,
        diagnostic_request_id_or_none="adobe-minimum-1",
    )


def _diagnostic_stdout(payload: dict[str, object]) -> str:
    return (
        "===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-BEGIN===\n"
        + json.dumps(payload)
        + "\n===AGENT-OS-CODESPACES-DIAGNOSTIC-JSON-END===\n"
    )


def _adobe_payload(*, disposition: str, final_url: str, title: str, unsupported: bool = False) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": "success",
        "reason_codes": ["adobe-minimum-probe-passed"],
        "disposition": disposition,
        "repository": REPOSITORY,
        "issue_number": 3094,
        "diagnostic_id": ADOBE_DIAGNOSTIC_ID,
        "request_id": "adobe-minimum-1",
        "codespace_name": APPROVED_CODESPACE_NAME,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "environment_health_evidence_id": "sha256:" + ("c" * 64),
        "workspace_head": "d" * 40,
        "workspace_branch": "agent/3094-adobe-minimum-probe",
        "os_distribution": "Ubuntu 24.04",
        "kernel": "6.8.0",
        "cpu_architecture": "x86_64",
        "cpu_count": 4,
        "ram_bytes": 8589934592,
        "available_disk_bytes": 10737418240,
        "browser_executable": "google-chrome",
        "browser_version": "Google Chrome 153.0.0.0",
        "display_mode": "headless",
        "graphics_renderer": "ANGLE",
        "webgl": "yes",
        "webgl2": "yes",
        "requested_url": ADOBE_EXPRESS_URL,
        "final_url": final_url,
        "network_application_reachability": "reachable",
        "page_title": title,
        "browser_process_exit_classification": "exit-0",
        "redirect_classification": "same-adobe",
        "unsupported_browser_detected": unsupported,
        "unsupported_system_detected": False,
        "normal_login_or_application_surface_detected": not unsupported,
        "fatal_browser_error": None,
        "fatal_renderer_error": None,
        "cleanup_complete": True,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }


def test_3094_adobe_and_existing_canva_diagnostics_select_distinct_fixed_runners(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    calls = []
    adobe_payload = _adobe_payload(
        disposition="CODESPACES_ADOBE_MINIMUM_PROBE_PASS",
        final_url="https://new.express.adobe.com/",
        title="Adobe Express",
    )

    def run(argv, *, timeout):
        calls.append(argv)
        if argv[:3] == ("gh", "api", "-H"):
            return subprocess.CompletedProcess(argv, 0, stdout=_codespace_payload(), stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=_diagnostic_stdout(adobe_payload), stderr="")

    route, request = select_codespaces_diagnostic(_adobe_ingress(), run=run)
    assert route["selected"] is True
    assert request is not None
    evidence = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert evidence["disposition"] == "CODESPACES_ADOBE_MINIMUM_PROBE_PASS"
    ssh_argv = calls[-1]
    assert ssh_argv[8] == _ADOBE_REMOTE_RUNNER_SOURCE
    assert ADOBE_EXPRESS_URL in _ADOBE_REMOTE_RUNNER_SOURCE
    assert "process.argv[2]" in _ADOBE_REMOTE_RUNNER_SOURCE
    assert "userAgent" not in _ADOBE_REMOTE_RUNNER_SOURCE
    assert "--disable-web-security" not in _ADOBE_REMOTE_RUNNER_SOURCE
    assert _REMOTE_RUNNER_SOURCE != _ADOBE_REMOTE_RUNNER_SOURCE


def test_3094_unsupported_adobe_surface_preserves_bounded_disposition() -> None:
    _, request = select_codespaces_diagnostic(
        _adobe_ingress(),
        run=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, stdout=_codespace_payload(), stderr=""),
    )
    assert request is not None
    payload = _adobe_payload(
        disposition="CODESPACES_BLOCKED_UNSUPPORTED_PLATFORM",
        final_url="https://new.express.adobe.com/unsupported-browser",
        title="Unsupported browser",
        unsupported=True,
    )
    payload["reason_codes"] = ["adobe-unsupported-platform-observed"]
    evidence = run_codespaces_diagnostic(
        request,
        codespace_name=APPROVED_CODESPACE_NAME,
        run=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, stdout=_diagnostic_stdout(payload), stderr=""),
    )
    assert evidence["disposition"] == "CODESPACES_BLOCKED_UNSUPPORTED_PLATFORM"
    assert evidence["unsupported_browser_detected"] is True
    assert evidence["cleanup_complete"] is True


def test_3094_adobe_result_identity_url_cleanup_and_secret_material_fail_closed() -> None:
    _, request = select_codespaces_diagnostic(
        _adobe_ingress(),
        run=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, stdout=_codespace_payload(), stderr=""),
    )
    assert request is not None
    for patch in (
        {"requested_url": "https://example.invalid/"},
        {"diagnostic_id": DIAGNOSTIC_ID},
        {"cleanup_complete": False},
    ):
        payload = {**_adobe_payload(
            disposition="CODESPACES_ADOBE_MINIMUM_PROBE_PASS",
            final_url=ADOBE_EXPRESS_URL,
            title="Adobe Express",
        ), **patch}
        evidence = run_codespaces_diagnostic(
            request,
            codespace_name=APPROVED_CODESPACE_NAME,
            run=lambda argv, timeout, payload=payload: subprocess.CompletedProcess(argv, 0, stdout=_diagnostic_stdout(payload), stderr=""),
        )
        assert evidence["status"] == "needs-decision"

    source = _ADOBE_REMOTE_RUNNER_SOURCE.lower()
    assert "raw html" not in source
    assert "document.documentelement" not in source
    assert "localstorage" not in source
    assert "sessionstorage" not in source
    assert "cookies()" not in source

    sensitive = _adobe_payload(
        disposition="CODESPACES_ADOBE_MINIMUM_PROBE_PASS",
        final_url=ADOBE_EXPRESS_URL,
        title="Adobe Express",
    )
    sensitive["cookie"] = "session=secret"
    evidence = run_codespaces_diagnostic(
        request,
        codespace_name=APPROVED_CODESPACE_NAME,
        run=lambda argv, timeout: subprocess.CompletedProcess(
            argv, 0, stdout=_diagnostic_stdout(sensitive), stderr=""
        ),
    )
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "codespaces-diagnostic-sensitive-evidence-rejected"
    ]


def test_3094_adobe_evidence_contract_is_bounded_and_fixed() -> None:
    assert ADOBE_EXPRESS_URL == "https://new.express.adobe.com/"
    assert "ADOBE_URL=\"https://new.express.adobe.com/\"" in _ADOBE_REMOTE_RUNNER_SOURCE
    assert "process.argv[2]" in _ADOBE_REMOTE_RUNNER_SOURCE
    assert "raw html" not in _ADOBE_REMOTE_RUNNER_SOURCE.lower()
    assert len(_ADOBE_REMOTE_RUNNER_SOURCE.encode("utf-8")) < 16000
    assert "cleanup_complete" in _ADOBE_REMOTE_RUNNER_SOURCE
