from __future__ import annotations

import shlex

import json
import subprocess
from pathlib import Path

from workflow_scheduler.governance.codespaces_diagnostic import (
    ADOBE_DIAGNOSTIC_ID,
    ADOBE_EXPRESS_URL,
    ADOBE_DISPOSITIONS,
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


import pytest


@pytest.fixture(autouse=True)
def _mock_transport_auth_for_existing_diagnostic_cases(monkeypatch, request):
    # Only legacy SSH/remote-health tests bypass API auth. Auth-specific and
    # integrated tests exercise the real preflight without a global stub.
    if request.node.name.startswith((
        "test_3345_transport_authentication_",
        "test_3345_integrated_auth_",
    )):
        return
    from workflow_scheduler.governance import codespaces_diagnostic
    monkeypatch.setattr(codespaces_diagnostic, "_check_transport_authentication", lambda *args, **kwargs: None)


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

    call_count = 0

    def run(argv, *, timeout):
        nonlocal call_count
        call_count += 1
        calls.append(argv)
        if call_count == 1:
            return subprocess.CompletedProcess(argv, 0, stdout=_codespace_payload(), stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=_diagnostic_stdout(adobe_payload), stderr="")

    route, request = select_codespaces_diagnostic(_adobe_ingress(), run=run)
    assert route["selected"] is True
    assert request is not None
    evidence = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert evidence["disposition"] == "CODESPACES_ADOBE_MINIMUM_PROBE_PASS"
    ssh_argv = calls[-1]
    assert ssh_argv[8] == shlex.quote(_ADOBE_REMOTE_RUNNER_SOURCE)
    assert ADOBE_EXPRESS_URL in _ADOBE_REMOTE_RUNNER_SOURCE
    assert "p.goto(process.argv[2]" in _ADOBE_REMOTE_RUNNER_SOURCE
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



def test_3094_shared_resolver_fail_closed_cases_apply_to_adobe(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    cases = (
        (json.dumps({"total_count": 0, "codespaces": []}), "codespaces-no-qualified-surface"),
        (json.dumps({
            "total_count": 2,
            "codespaces": [
                json.loads(_codespace_payload())["codespaces"][0],
                {
                    "name": "another-agentos-surface",
                    "state": "Available",
                    "owner": {"login": "Blummer92"},
                    "repository": {"full_name": REPOSITORY},
                },
            ],
        }), "codespaces-selection-ambiguous"),
        (_codespace_payload(state="Shutdown"), "codespaces-not-available"),
        ("not-json", "codespaces-read-evidence-invalid"),
    )
    for stdout, reason in cases:
        route, request = select_codespaces_diagnostic(
            _adobe_ingress(),
            run=lambda argv, timeout, stdout=stdout: subprocess.CompletedProcess(
                argv, 0, stdout=stdout, stderr=""
            ),
        )
        assert request is not None
        assert route["handled"] is True
        assert route["selected"] is False
        assert route["reason_codes"] == [reason]


def test_3094_environment_health_mismatch_remains_fail_closed() -> None:
    assert "codespaces-environment-health-invalid" in _ADOBE_REMOTE_RUNNER_SOURCE
    assert 'health_payload.get("profile_id")!=PROFILE_ID' in _ADOBE_REMOTE_RUNNER_SOURCE
    assert 'health_payload.get("execution_surface_id")!=f"codespace:{codespace_name}"' in _ADOBE_REMOTE_RUNNER_SOURCE


def test_3094_existing_canva_remote_runner_is_behaviorally_unchanged() -> None:
    assert 'DIAGNOSTIC_ID="ppux-canva-cdp-readonly"' in _REMOTE_RUNNER_SOURCE
    assert ADOBE_EXPRESS_URL not in _REMOTE_RUNNER_SOURCE
    assert "loopback" in _REMOTE_RUNNER_SOURCE
    assert "cdp" in _REMOTE_RUNNER_SOURCE

def test_3094_adobe_evidence_contract_is_bounded_and_fixed() -> None:
    assert ADOBE_EXPRESS_URL == "https://new.express.adobe.com/"
    assert "ADOBE_URL=\"https://new.express.adobe.com/\"" in _ADOBE_REMOTE_RUNNER_SOURCE
    assert "process.argv[2]" in _ADOBE_REMOTE_RUNNER_SOURCE
    assert "raw html" not in _ADOBE_REMOTE_RUNNER_SOURCE.lower()
    assert len(_ADOBE_REMOTE_RUNNER_SOURCE.encode("utf-8")) < 16000
    assert "cleanup_complete" in _ADOBE_REMOTE_RUNNER_SOURCE
    for forbidden in (
        "--user-data-dir",
        "--remote-debugging-port",
        "--disable-web-security",
        "--use-gl=",
        "--use-angle=",
        "cookies()",
        "localstorage",
        "sessionstorage",
    ):
        assert forbidden not in _ADOBE_REMOTE_RUNNER_SOURCE.lower()



def test_3094_adobe_pass_requires_bounded_normal_surface_evidence() -> None:
    source = _ADOBE_REMOTE_RUNNER_SOURCE
    assert "200<=result[\"http_status\"]<400" in source
    assert "normal_path" in source
    assert "bad_title" in source
    assert "navigationError" in source
    for marker in ("access denied", "captcha", "challenge", "cookie", "consent", "forbidden"):
        assert marker in source


def test_3094_adobe_unsupported_detection_is_bounded_to_url_and_title() -> None:
    source = _ADOBE_REMOTE_RUNNER_SOURCE
    assert '"/unsupported-browser" in final_url.lower()' in source
    assert '"unsupported browser" in title.lower()' in source
    assert '"system is not supported"' in source
    assert '"unsupported system"' in source
    assert '"system not supported"' in source
    assert "document.documentelement" not in source.lower()


def test_3094_graphics_block_requires_reachable_application_response() -> None:
    source = _ADOBE_REMOTE_RUNNER_SOURCE
    assert 'result["network_application_reachability"]=="reachable" and observed.get("webgl") is False' in source


def test_3094_runtime_dependencies_fail_closed_without_installing_anything() -> None:
    source = _ADOBE_REMOTE_RUNNER_SOURCE
    assert 'shutil.which("node")' in source
    assert "require.resolve('playwright')" in source
    assert "adobe-node-runtime-unavailable" in source
    assert "adobe-playwright-runtime-unavailable" in source
    for installer in ("npm install", "npm ci", "npx playwright install", "apt-get", "pip install"):
        assert installer not in source


def test_3094_cleanup_is_observed_not_assumed() -> None:
    source = _ADOBE_REMOTE_RUNNER_SOURCE
    assert "cleanup=false" in source
    assert "await b.close();b=null;cleanup=true" in source
    assert 'result["cleanup_complete"]=observed.get("cleanup") is True' in source
    assert "adobe-browser-cleanup-unconfirmed" in source
    assert 'result["cleanup_complete"]=False' in source
    assert "adobe-browser-probe-timeout" in source


def test_3094_adobe_disposition_vocabulary_is_exact() -> None:
    assert ADOBE_DISPOSITIONS == {
        "CODESPACES_BLOCKED_UNSUPPORTED_PLATFORM",
        "CODESPACES_BLOCKED_GRAPHICS",
        "CODESPACES_ADOBE_MINIMUM_PROBE_PASS",
        "CODESPACES_NETWORK_ONLY",
        "CODESPACES_EXECUTION_PATH_BLOCKED",
        "MANUAL_REVIEW",
    }


def test_3094_existing_canva_behavioral_payload_still_round_trips() -> None:
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
        "environment_health_evidence_id": "sha256:" + ("e" * 64),
        "cleanup_complete": True,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
        "loopback": {"9222": False, "9444": False},
        "cdp": {"browser": None, "target_count": 0, "targets": []},
    }
    evidence = run_codespaces_diagnostic(
        request,
        codespace_name=APPROVED_CODESPACE_NAME,
        run=lambda argv, timeout: subprocess.CompletedProcess(
            argv, 0, stdout=_diagnostic_stdout(payload), stderr=""
        ),
    )
    assert evidence == payload


def _qualification_ingress() -> IssueCommentIngressResult:
    from workflow_scheduler.governance.codespaces_diagnostic import QUALIFICATION_DIAGNOSTIC_ID
    base = _ingress()
    return IssueCommentIngressResult(
        schema_version=base.schema_version,
        status="accepted",
        reason="accepted-codespaces-diagnostic-envelope",
        repository=REPOSITORY,
        issue_number=3463,
        comment_id=base.comment_id,
        actor="Blummer92",
        handoff_id_or_none=None,
        logical_trigger_id_or_none=base.logical_trigger_id_or_none,
        run_attempt=1,
        diagnostic_id_or_none=QUALIFICATION_DIAGNOSTIC_ID,
        diagnostic_request_id_or_none="qualify-3463-1",
    )


def _qualification_payload() -> dict[str, object]:
    from workflow_scheduler.governance.codespaces_diagnostic import QUALIFICATION_DIAGNOSTIC_ID
    return {
        "schema_version": "1.0",
        "status": "success",
        "reason_codes": ["codespaces-environment-qualified"],
        "repository": REPOSITORY,
        "issue_number": 3463,
        "diagnostic_id": QUALIFICATION_DIAGNOSTIC_ID,
        "request_id": "qualify-3463-1",
        "codespace_name": APPROVED_CODESPACE_NAME,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": APPROVED_CODESPACE_SURFACE_ID,
        "environment_health_evidence_id": "sha256:" + "a" * 64,
        "workspace_head": "b" * 40,
        "workspace_branch": None,
        "cleanup_complete": True,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }


def test_3463_qualification_reuses_canonical_resolver_and_fixed_ssh() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        QUALIFICATION_DIAGNOSTIC_ID, _QUALIFICATION_REMOTE_RUNNER_SOURCE,
    )
    import os
    old = os.environ.get("GH_TOKEN")
    os.environ["GH_TOKEN"] = "fixture-not-a-real-token"
    try:
        route, request = select_codespaces_diagnostic(
            _qualification_ingress(),
            run=lambda argv, timeout: subprocess.CompletedProcess(
                argv, 0, stdout=_codespace_payload(), stderr=""
            ),
        )
    finally:
        if old is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = old
    assert route["selected"] is True
    assert request is not None
    assert route["codespace_name"] == APPROVED_CODESPACE_NAME
    payload = _qualification_payload()
    calls = []
    def run(argv, *, timeout):
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if len(calls) == 2:
            return subprocess.CompletedProcess(argv, 0, stdout="Python 3.11.13\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=_diagnostic_stdout(payload), stderr="")
    result = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["status"] == "success"
    assert result["environment_health_evidence_id"].startswith("sha256:")
    assert calls[2][:5] == ("gh", "codespace", "ssh", "-c", APPROVED_CODESPACE_NAME)
    assert shlex.split('python3 -c ' + calls[2][8])[2] == _QUALIFICATION_REMOTE_RUNNER_SOURCE
    assert calls[2][-3] == QUALIFICATION_DIAGNOSTIC_ID
    assert "scripts/agent-os-environment-health.py" in _QUALIFICATION_REMOTE_RUNNER_SOURCE
    assert "CODESPACE_NAME" in _QUALIFICATION_REMOTE_RUNNER_SOURCE
    assert "rm -rf" not in _QUALIFICATION_REMOTE_RUNNER_SOURCE
    assert "pip install" not in _QUALIFICATION_REMOTE_RUNNER_SOURCE


def test_3463_qualification_rejects_mismatched_surface_and_bad_health_receipt() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY,
        issue_number=3463,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID,
        request_id="qualify-3463-1",
    )
    for field, value, reason in (
        ("codespace_name", "old-deleted-codespace", "codespaces-diagnostic-evidence-identity-mismatch"),
        ("environment_health_evidence_id", "not-a-hash", "codespaces-environment-health-evidence-invalid"),
    ):
        payload = _qualification_payload()
        payload[field] = value
        calls = []
        def run(argv, *, timeout):
            calls.append(argv)
            if len(calls) == 1:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            if len(calls) == 2:
                return subprocess.CompletedProcess(
                    argv, 0, stdout="Python 3.11.13\n", stderr=""
                )
            return subprocess.CompletedProcess(
                argv, 0, stdout=_diagnostic_stdout(payload), stderr=""
            )
        result = run_codespaces_diagnostic(
            request,
            codespace_name=APPROVED_CODESPACE_NAME,
            run=run,
        )
        assert result["status"] == "needs-decision"
        assert result["reason_codes"] == [reason]


def test_3463_qualification_runner_is_read_only_and_does_not_embed_target_name() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import _QUALIFICATION_REMOTE_RUNNER_SOURCE
    source = _QUALIFICATION_REMOTE_RUNNER_SOURCE
    assert "animated-computing-machine-pgjg5796p96h69q5" not in source
    assert "gh codespace start" not in source
    assert "gh codespace stop" not in source
    assert "os.environ.get(\"CODESPACE_NAME\")!=codespace_name" in source
    assert 'hp.get("profile_id")!=PROFILE_ID' in source
    assert 'hp.get("execution_surface_id")!=f"codespace:{codespace_name}"' in source


def test_3345_ssh_stage_timeout_is_not_reported_as_health_failure() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
        _SSH_STAGE_TIMEOUT_SECONDS,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3345,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="ssh-stage-1",
    )
    calls = []
    def run(argv, *, timeout):
        calls.append((argv, timeout))
        raise subprocess.TimeoutExpired(argv, timeout)
    result = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["reason_codes"] == ["codespaces-ssh-probe-timeout"]
    assert result["failed_stage"] == "ssh"
    assert calls[0][0] == ("gh", "codespace", "ssh", "-c", APPROVED_CODESPACE_NAME, "--", "true")
    assert calls[0][1] == _SSH_STAGE_TIMEOUT_SECONDS
    assert len(calls) == 1


def test_3345_python_start_probe_failure_is_distinct() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3345,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="ssh-stage-2",
    )
    calls = []
    def run(argv, *, timeout):
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")
    result = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["reason_codes"] == ["codespaces-python-probe-failed"]
    assert result["failed_stage"] == "python"
    assert len(calls) == 2
    assert calls[1][-3:] == ("--", "python3", "-V")


def test_3345_stage_probes_precede_existing_health_runner() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3345,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="ssh-stage-3",
    )
    payload = _qualification_payload()
    payload["issue_number"] = 3345
    payload["request_id"] = "ssh-stage-3"
    calls = []
    def run(argv, *, timeout):
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if len(calls) == 2:
            return subprocess.CompletedProcess(argv, 0, stdout="Python 3.11.13\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=_diagnostic_stdout(payload), stderr="")
    result = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["status"] == "success"
    assert len(calls) == 3
    assert calls[2][8].find("scripts/agent-os-environment-health.py") >= 0


def test_3345_python_probe_wrong_marker_with_exit_zero_fails_closed() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3345,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="ssh-stage-wrong-marker",
    )
    calls = []
    def run(argv, *, timeout):
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="unexpected-marker\n", stderr="")
    result = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["codespaces-python-probe-failed"]
    assert result["failed_stage"] == "python"
    assert result["probe_exit_code"] == 0
    assert len(calls) == 2


def test_3345_python_probe_timeout_fails_before_health_runner() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
        _SSH_STAGE_TIMEOUT_SECONDS,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3345,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="ssh-stage-python-timeout",
    )
    calls = []
    def run(argv, *, timeout):
        calls.append((argv, timeout))
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(argv, timeout)
    result = run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["codespaces-python-probe-timeout"]
    assert result["failed_stage"] == "python"
    assert result["stage_timeout_seconds"] == _SSH_STAGE_TIMEOUT_SECONDS
    assert len(calls) == 2
    assert calls[1][0][-3:] == ("--", "python3", "-V")
    assert calls[1][1] == _SSH_STAGE_TIMEOUT_SECONDS


def test_3345_transport_authentication_preflight_fail_closed() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
        _AUTH_PREFLIGHT_TIMEOUT_SECONDS, _check_transport_authentication,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3345,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="auth-3345",
    )
    cases = (
        (subprocess.CompletedProcess([], 0, stdout="Blummer92\n", stderr=""), None),
        (subprocess.CompletedProcess([], 1, stdout="", stderr="private token text"), "codespaces-transport-auth-failed"),
        (subprocess.CompletedProcess([], 0, stdout="", stderr=""), "codespaces-transport-auth-failed"),
    )
    for completed, expected in cases:
        calls = []
        def run(argv, *, timeout):
            calls.append((argv, timeout))
            return completed
        result = _check_transport_authentication(
            request, codespace_name=APPROVED_CODESPACE_NAME, run=run
        )
        assert calls == [(("gh", "api", "--method", "GET", "/user", "--jq", ".login"), _AUTH_PREFLIGHT_TIMEOUT_SECONDS)]
        if expected is None:
            assert result is None
        else:
            assert result["reason_codes"] == [expected]
            assert "private token text" not in json.dumps(result)


def test_3345_transport_authentication_timeout_is_distinct() -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
        _check_transport_authentication,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3345,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="auth-timeout",
    )
    def run(argv, *, timeout):
        raise subprocess.TimeoutExpired(argv, timeout, stderr=b"secret-not-for-receipt")
    result = _check_transport_authentication(
        request, codespace_name=APPROVED_CODESPACE_NAME, run=run
    )
    assert result["reason_codes"] == ["codespaces-transport-auth-timeout"]
    assert result["failed_stage"] == "api-authentication"
    assert "secret-not-for-receipt" not in json.dumps(result)


def test_3345_integrated_auth_ssh_python_health_and_fail_closed(monkeypatch) -> None:
    """Exercise the real auth preflight without the module-wide isolation stub."""
    from workflow_scheduler.governance import codespaces_diagnostic as diagnostic
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
        _check_transport_authentication,
    )
    monkeypatch.setattr(
        diagnostic, "_check_transport_authentication", _check_transport_authentication
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3345,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="integrated-auth-ssh",
    )
    payload = _qualification_payload()
    payload["issue_number"] = 3345
    payload["request_id"] = "integrated-auth-ssh"

    def execute(*, auth_exit=0, auth_output="Blummer92\n", ssh_exit=0,
                python_marker="Python 3.11.13\n",
                health_payload=None):
        calls = []
        def run(argv, *, timeout):
            calls.append((argv, timeout))
            if len(calls) == 1:
                return subprocess.CompletedProcess(argv, auth_exit, stdout=auth_output, stderr="private credential")
            if len(calls) == 2:
                return subprocess.CompletedProcess(argv, ssh_exit, stdout="", stderr="")
            if len(calls) == 3:
                return subprocess.CompletedProcess(argv, 0, stdout=python_marker, stderr="")
            return subprocess.CompletedProcess(
                argv, 0, stdout=_diagnostic_stdout(health_payload if health_payload is not None else payload),
                stderr=""
            )
        return diagnostic.run_codespaces_diagnostic(
            request, codespace_name=APPROVED_CODESPACE_NAME, run=run
        ), calls

    good, calls = execute()
    assert good["status"] == "success"
    assert len(calls) == 4
    assert calls[0][0] == ("gh", "api", "--method", "GET", "/user", "--jq", ".login")
    assert calls[1][0] == ("gh", "codespace", "ssh", "-c", APPROVED_CODESPACE_NAME, "--", "true")
    assert calls[2][0][-3:] == ("--", "python3", "-V")
    assert "scripts/agent-os-environment-health.py" in calls[3][0][8]
    assert "private credential" not in json.dumps(good)

    failed_auth, calls = execute(auth_exit=1, auth_output="")
    assert failed_auth["reason_codes"] == ["codespaces-transport-auth-failed"]
    assert len(calls) == 1
    assert "private credential" not in json.dumps(failed_auth)

    failed_ssh, calls = execute(ssh_exit=1)
    assert failed_ssh["reason_codes"] == ["codespaces-ssh-probe-failed"]
    assert len(calls) == 2

    failed_python, calls = execute(python_marker="wrong marker\n")
    assert failed_python["reason_codes"] == ["codespaces-python-probe-failed"]
    assert len(calls) == 3

    invalid_health = dict(payload)
    invalid_health["environment_health_evidence_id"] = "invalid"
    failed_health, calls = execute(health_payload=invalid_health)
    assert failed_health["reason_codes"] == ["codespaces-environment-health-evidence-invalid"]
    assert len(calls) == 4


def test_3463_ssh_timeout_records_bounded_duration_without_raw_output() -> None:
    from workflow_scheduler.governance import codespaces_diagnostic
    request = codespaces_diagnostic.CodespacesDiagnosticRequest(
        repository="Blummer92/agent-os", issue_number=3463,
        diagnostic_id="codespaces-environment-qualification-readonly", request_id="timing-test",
    )
    def timeout(argv, *, timeout):
        raise subprocess.TimeoutExpired(argv, timeout, output="private-token", stderr="secret-ssh-debug")
    result = codespaces_diagnostic._qualify_ssh_stages(
        request, codespace_name="animated-computing-machine-pgjg5796p96h69q5", run=timeout,
    )
    assert result["reason_codes"] == ["codespaces-ssh-probe-timeout"]
    assert result["failure_detail"] == "undetermined"
    assert isinstance(result["probe_elapsed_ms"], int)
    assert result["probe_elapsed_ms"] >= 0
    assert "private-token" not in str(result)
    assert "secret-ssh-debug" not in str(result)


def test_3534_python_probe_is_shell_safe_and_version_bounded(monkeypatch) -> None:
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
        _qualify_ssh_stages,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3534,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="python-shell-safe",
    )
    calls = []
    def run(argv, *, timeout):
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="Python 3.11.13\n", stderr="")
    assert _qualify_ssh_stages(request, codespace_name=APPROVED_CODESPACE_NAME, run=run) is None
    assert calls[1] == ("gh", "codespace", "ssh", "-c", APPROVED_CODESPACE_NAME, "--", "python3", "-V")
    assert not any("(" in arg or "'" in arg for arg in calls[1])

    for bad in ("Python 2.7.18\n", "Python 3.11.13 extra\n", "not-python\n"):
        def bad_run(argv, *, timeout):
            if argv[-1] == "true":
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout=bad, stderr="secret=redacted-test-token")
        result = _qualify_ssh_stages(request, codespace_name=APPROVED_CODESPACE_NAME, run=bad_run)
        assert result["reason_codes"] == ["codespaces-python-probe-failed"]
        assert "redacted-test-token" not in json.dumps(result)


def test_3536_fixed_multiline_runner_is_shell_quoted(monkeypatch) -> None:
    import shlex
    from workflow_scheduler.governance import codespaces_diagnostic as diagnostic
    from workflow_scheduler.governance.codespaces_diagnostic import (
        CodespacesDiagnosticRequest, QUALIFICATION_DIAGNOSTIC_ID,
        _QUALIFICATION_REMOTE_RUNNER_SOURCE,
    )
    request = CodespacesDiagnosticRequest(
        repository=REPOSITORY, issue_number=3536,
        diagnostic_id=QUALIFICATION_DIAGNOSTIC_ID, request_id="multiline-shell-quote",
    )
    monkeypatch.setattr(diagnostic, "_check_transport_authentication", lambda *args, **kwargs: None)
    monkeypatch.setattr(diagnostic, "_qualify_ssh_stages", lambda *args, **kwargs: None)
    calls = []
    def run(argv, *, timeout):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="private-token")
    evidence = diagnostic.run_codespaces_diagnostic(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert evidence["reason_codes"] == ["codespaces-diagnostic-ssh-failed"]
    assert calls[0][8] == shlex.quote(_QUALIFICATION_REMOTE_RUNNER_SOURCE)
    assert shlex.split("python3 -c " + calls[0][8])[2] == _QUALIFICATION_REMOTE_RUNNER_SOURCE
    assert calls[0][-4:] == ("3536", QUALIFICATION_DIAGNOSTIC_ID, "multiline-shell-quote", APPROVED_CODESPACE_NAME)
    assert "private-token" not in str(evidence)
