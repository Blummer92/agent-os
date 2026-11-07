from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from workflow_scheduler.governance.dev_validation import (
    REPOSITORY,
    VALIDATION_ID,
    build_dev_validation_request,
)
from workflow_scheduler.governance.dev_validation_codespaces import (
    APPROVED_CODESPACE_PROFILE_ID,
    _REMOTE_RUNNER_SOURCE,
    _RUN_TIMEOUT_SECONDS,
    resolve_current_codespace,
    run_dev_validation_over_codespaces,
    select_codespaces_dev_validation,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    IssueCommentIngressResult,
)

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40
BRANCH = "agent/2931-codespaces-test"
# #2965: the historical literal identity that was compiled into the provider.
STALE_NAME = "literate-system-j4j4pr9g4q7h45q"
CURRENT_NAME = "fluffy-current-agentos-7x9q"
CURRENT_SURFACE_ID = f"codespace:{CURRENT_NAME}"


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


def _codespace(name: str = CURRENT_NAME, *, state: str = "Available", **overrides) -> dict:
    item = {
        "name": name,
        "state": state,
        "owner": {"login": "Blummer92"},
        "repository": {"full_name": REPOSITORY},
    }
    item.update(overrides)
    return item


def _codespace_payload(*items: dict, total_count: int | None = None) -> str:
    listed = list(items) if items else [_codespace()]
    return json.dumps(
        {
            "total_count": len(listed) if total_count is None else total_count,
            "codespaces": listed,
        }
    )


def _listing_run(stdout: str, calls: list | None = None):
    def run(argv, *, timeout):
        if calls is not None:
            calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    return run


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
            argv, 0, stdout=_codespace_payload(_codespace(state="Shutdown")), stderr=""
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
    assert route["codespace_name"] == CURRENT_NAME
    assert route["execution_surface_id"] == CURRENT_SURFACE_ID
    assert route["credential_permission"] == "codespaces:read"
    assert route["lifecycle_mutation_authorized"] is False


def test_codespace_identity_mismatch_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    stdout = _codespace_payload(
        _codespace(repository={"full_name": "Blummer92/not-agent-os"}),
        _codespace("someone-else", owner={"login": "not-the-owner"}),
    )

    route, _ = select_codespaces_dev_validation(_ingress(), run=_listing_run(stdout))
    assert route["selected"] is False
    assert route["reason_codes"] == ["codespaces-no-qualified-surface"]
    assert route["codespace_name"] is None


def test_2965_stale_historical_codespace_does_not_mask_current_surface(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    calls: list = []
    stdout = _codespace_payload(
        _codespace(STALE_NAME, state="Shutdown"), _codespace(CURRENT_NAME)
    )

    route, _ = select_codespaces_dev_validation(_ingress(), run=_listing_run(stdout, calls))
    assert route["selected"] is True
    assert route["codespace_name"] == CURRENT_NAME
    assert route["execution_surface_id"] == CURRENT_SURFACE_ID
    assert calls == [
        (
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"/repos/{REPOSITORY}/codespaces?per_page=100",
        )
    ]


def test_2965_zero_qualified_surfaces_fall_back(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    stdout = json.dumps({"total_count": 0, "codespaces": []})

    selection = resolve_current_codespace(_listing_run(stdout))
    assert selection.selected is False
    assert selection.reason == "codespaces-no-qualified-surface"
    assert selection.codespace_name is None


def test_2965_multiple_available_surfaces_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    stdout = _codespace_payload(_codespace(CURRENT_NAME), _codespace("another-agentos-surface"))

    selection = resolve_current_codespace(_listing_run(stdout))
    assert selection.selected is False
    assert selection.reason == "codespaces-selection-ambiguous"
    assert selection.codespace_name is None


def test_2965_current_qualified_surface_shutdown_preserves_2935_fallback(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    stdout = _codespace_payload(_codespace(CURRENT_NAME, state="Shutdown"))

    selection = resolve_current_codespace(_listing_run(stdout))
    assert selection.selected is False
    assert selection.reason == "codespaces-not-available"
    assert selection.codespace_name == CURRENT_NAME
    assert selection.state == "Shutdown"


def test_2965_truncated_or_malformed_listing_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    for stdout in (
        _codespace_payload(_codespace(), total_count=101),
        json.dumps({"codespaces": [_codespace()]}),
        json.dumps({"total_count": 1, "codespaces": ["not-an-object"]}),
        json.dumps(_codespace()),
        "not json",
    ):
        selection = resolve_current_codespace(_listing_run(stdout))
        assert selection.selected is False
        assert selection.reason == "codespaces-read-evidence-invalid"


def test_2965_unsafe_codespace_name_is_never_selected(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    stdout = _codespace_payload(_codespace("bad name; rm -rf /"))

    selection = resolve_current_codespace(_listing_run(stdout))
    assert selection.selected is False
    assert selection.reason == "codespaces-no-qualified-surface"


def test_2965_execution_requires_a_resolved_codespace_name() -> None:
    import pytest

    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )
    for name in (None, "", "bad name"):
        with pytest.raises(ValueError):
            run_dev_validation_over_codespaces(request, codespace_name=name)


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
        "execution_surface_id": CURRENT_SURFACE_ID,
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

    evidence = run_dev_validation_over_codespaces(request, codespace_name=CURRENT_NAME, run=run)
    assert evidence["status"] == "success"
    assert evidence["cleanup_complete"] is True
    assert evidence["execution_surface_id"] == CURRENT_SURFACE_ID
    assert len(calls) == 1
    argv = calls[0]
    assert argv[:5] == (
        "gh",
        "codespace",
        "ssh",
        "-c",
        CURRENT_NAME,
    )
    assert argv[5] == "--"
    # #3333/#3617: the multiline runner must cross the SSH shell boundary as
    # one safely quoted command, not as separate argv elements the remote
    # shell re-splits (run 41633810143). This replaces the old
    # argv[5:8] == ("--", "python3", "-c") and argv[-1] == name shape, which
    # was the defect.
    assert len(argv) == 7
    remote_command = argv[6]
    assert "\n" in remote_command  # the source is multiline, yet one shell word
    assert shlex.split(remote_command) == [
        "python3",
        "-c",
        _REMOTE_RUNNER_SOURCE,
        REPOSITORY,
        "2931",
        BRANCH,
        SHA,
        VALIDATION_ID,
        request.request_id,
        CURRENT_NAME,
    ]
    split_command = shlex.split(remote_command)
    assert "start" not in split_command
    assert "stop" not in split_command
    assert "delete" not in split_command
    assert "export" not in split_command


def test_ssh_remote_command_executes_through_posix_shell(monkeypatch) -> None:
    # #3333/#3617: exercise the implementation's exact quoting through a real
    # POSIX shell. A sentinel program proves the shell delivers the -c
    # program intact instead of parsing its lines as shell commands.
    sentinel = (
        "import sys\n"
        "sys.stdout.write('SSH_BOUNDARY_OK')\n"
    )
    monkeypatch.setattr(
        "workflow_scheduler.governance.dev_validation_codespaces._REMOTE_RUNNER_SOURCE",
        sentinel,
    )
    captured: dict[str, str] = {}

    def run(argv, *, timeout):
        captured["command"] = argv[6]
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )
    run_dev_validation_over_codespaces(request, codespace_name=CURRENT_NAME, run=run)
    completed = subprocess.run(
        ("sh", "-c", captured["command"]), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    assert "SSH_BOUNDARY_OK" in completed.stdout
    assert "command not found" not in completed.stderr
    assert "SyntaxError" not in completed.stderr


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

    evidence = run_dev_validation_over_codespaces(request, codespace_name=CURRENT_NAME, run=run)
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

    evidence = run_dev_validation_over_codespaces(request, codespace_name=CURRENT_NAME, run=run)
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
        "execution_surface_id": CURRENT_SURFACE_ID,
        "environment_health_evidence_id": "sha256:" + ("b" * 64),
    }
    stdout = (
        "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN===\n"
        + json.dumps(payload)
        + "\n===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END===\n"
    )

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    evidence = run_dev_validation_over_codespaces(request, codespace_name=CURRENT_NAME, run=run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "dev-validation-codespaces-evidence-identity-mismatch"
    ]


def test_codespaces_identity_mismatch_preserves_remote_reason() -> None:
    # #3333/run 41659878211: a remote pre-surface failure (here the
    # environment-health gate) carries execution_surface_id None, so the
    # fixed-field check fails. The rejection must stay fail-closed, but
    # the remote reason and the differing field must survive in the
    # receipt instead of being replaced by the generic reason alone.
    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )
    payload = {
        "schema_version": "1.0",
        "status": "needs-decision",
        "reason_codes": ["codespaces-environment-health-invalid"],
        "repository": REPOSITORY,
        "issue_number": 2931,
        "branch": BRANCH,
        "tested_sha": SHA,
        "validation_id": VALIDATION_ID,
        "request_id": request.request_id,
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "cleanup_complete": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
        "codespaces_profile_id": APPROVED_CODESPACE_PROFILE_ID,
        "execution_surface_id": None,
        "environment_health_evidence_id": None,
    }
    stdout = (
        "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN===\n"
        + json.dumps(payload)
        + "\n===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END===\n"
    )

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    evidence = run_dev_validation_over_codespaces(request, codespace_name=CURRENT_NAME, run=run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "dev-validation-codespaces-evidence-identity-mismatch"
    ]
    assert evidence["remote_reason_codes"] == ["codespaces-environment-health-invalid"]
    assert evidence["identity_mismatch_fields"] == ["execution_surface_id"]
    assert evidence["stdout_tail"] == ""
    assert evidence["stderr_tail"] == ""
    assert evidence["exit_code"] is None

    # Copilot review #5754864655: malformed remote reason lists are wholly
    # untrusted, not partially filtered into plausible diagnostics.
    for malformed_reasons in (
        ["apparently-valid", 7],
        ["codespaces-environment-health-invalid", ""],
        [None],
        "codespaces-environment-health-invalid",
    ):
        payload["reason_codes"] = malformed_reasons
        stdout = (
            "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN===\n"
            + json.dumps(payload)
            + "\n===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END===\n"
        )
        rejected = run_dev_validation_over_codespaces(
            request, codespace_name=CURRENT_NAME, run=run
        )
        assert rejected["status"] == "needs-decision"
        assert rejected["reason_codes"] == [
            "dev-validation-codespaces-evidence-identity-mismatch"
        ]
        assert rejected["remote_reason_codes"] == []
        assert rejected["identity_mismatch_fields"] == ["execution_surface_id"]


def test_codespaces_identity_mismatch_lists_each_differing_field() -> None:
    # A success-shaped payload with one wrong fixed field still rejects,
    # and names exactly that field plus the remote reason it carried.
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
        "execution_surface_id": CURRENT_SURFACE_ID,
        "environment_health_evidence_id": "sha256:" + ("b" * 64),
    }
    stdout = (
        "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN===\n"
        + json.dumps(payload)
        + "\n===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END===\n"
    )

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    evidence = run_dev_validation_over_codespaces(request, codespace_name=CURRENT_NAME, run=run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == [
        "dev-validation-codespaces-evidence-identity-mismatch"
    ]
    assert evidence["remote_reason_codes"] == ["validation-passed"]
    assert evidence["identity_mismatch_fields"] == ["tested_sha"]


def test_prestart_timeout_preserves_failure_evidence_without_fallback(
    monkeypatch, tmp_path,
) -> None:
    from dataclasses import asdict
    from workflow_scheduler.governance import dev_validation_codespaces as provider

    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )
    monkeypatch.setattr(
        provider, "select_codespaces_dev_validation",
        lambda ingress: (
            provider._route(
                True, "codespaces-capable", state="Available", codespace_name=CURRENT_NAME
            ),
            request,
        ),
    )
    monkeypatch.setattr(
        provider, "run_dev_validation_over_codespaces",
        lambda unused, *, codespace_name: {
            **provider._failure(request, "dev-validation-codespaces-ssh-failed", codespace_name),
            "ssh_exit_code": 1,
            "ssh_stderr_tail": (
                "error connecting to codespace: timed out while waiting "
                "for the codespace to start"
            ),
        },
    )
    transport = tmp_path / "transport.json"
    transport.write_text(json.dumps(asdict(_ingress())), encoding="utf-8")
    route_path = tmp_path / "route.json"
    result_path = tmp_path / "result.json"
    assert provider.main([
        "--transport", str(transport),
        "--route-output", str(route_path),
        "--result-output", str(result_path),
    ]) == 0
    route = json.loads(route_path.read_text(encoding="utf-8"))
    assert route["selected"] is True
    result = json.loads(result_path.read_text(encoding="utf-8"))["dev_validation"]
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["dev-validation-codespaces-ssh-failed"]
    assert result["tested_sha"] == SHA
    assert result["validation_id"] == VALIDATION_ID
    assert result["ssh_exit_code"] == 1
    assert result["cleanup_complete"] is False


def test_codespaces_api_read_failure_classification_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    cases = (
        ("HTTP 403: Resource not accessible by integration", "codespaces-read-permission-denied"),
        ("HTTP 429: Too Many Requests", "codespaces-read-rate-limited"),
        ("HTTP 401: Bad credentials", "codespaces-read-unavailable"),
        ("secret=redacted-test-token", "codespaces-read-unavailable"),
    )
    for stderr, expected in cases:
        def run(argv, *, timeout):
            assert argv[:2] == ("gh", "api")
            assert timeout == 30
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=stderr)

        selection = resolve_current_codespace(run)
        assert selection.selected is False
        assert selection.reason == expected
        assert "redacted-test-token" not in selection.reason


def test_codespaces_api_read_timeout_and_transport_error_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")

    def timeout_run(argv, *, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)

    def missing_cli_run(argv, *, timeout):
        raise FileNotFoundError("gh unavailable")

    assert resolve_current_codespace(timeout_run).reason == "codespaces-read-timeout"
    assert resolve_current_codespace(missing_cli_run).reason == "codespaces-read-transport-error"


def test_3333_noninteractive_ssh_identity_policy_preserves_remote_gates() -> None:
    """Execute the actual fixed remote program, not a duplicate policy model.

    Force the next workspace gate to fail so neither pytest nor a worktree can
    run; this proves an absent CODESPACE_NAME only advances to the next gate.
    """
    import os

    request = build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=2931,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=VALIDATION_ID,
    )
    # Preserve the real runner and real request-identity derivation, replacing
    # only the local workspace existence probe to avoid host-dependent results.
    remote_program = (
        "import os\n"
        "os.path.isdir = lambda unused: False\n"
        + _REMOTE_RUNNER_SOURCE
    )
    for identity, expected in (
        (None, "codespaces-workspace-unavailable"),
        (CURRENT_NAME, "codespaces-workspace-unavailable"),
        ("", "codespaces-surface-identity-mismatch"),
        ("another-codespace", "codespaces-surface-identity-mismatch"),
    ):
        env = dict(os.environ)
        env.pop("CODESPACE_NAME", None)
        if identity is not None:
            env["CODESPACE_NAME"] = identity
        completed = subprocess.run(
            (
                "python3", "-c", remote_program,
                REPOSITORY, "2931", BRANCH, SHA, VALIDATION_ID,
                request.request_id, CURRENT_NAME,
            ),
            env=env, capture_output=True, text=True, timeout=10,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.count(
            "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN==="
        ) == 1
        payload = json.loads(
            completed.stdout.split(
                "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-BEGIN===", 1
            )[1].split(
                "===AGENT-OS-CODESPACES-DEV-VALIDATION-JSON-END===", 1
            )[0].strip()
        )
        assert payload["reason_codes"] == [expected]
        assert payload["status"] == "needs-decision"
        assert payload["exit_code"] is None
        assert payload["cleanup_complete"] is False
        assert payload["workspace_side_effects_performed"] is False
        assert payload["execution_authorized"] is False
        assert payload["merge_authorized"] is False
        assert payload["environment_health_evidence_id"] is None

    # An absent environment variable must not bypass request authentication.
    env = dict(os.environ)
    env.pop("CODESPACE_NAME", None)
    invalid = subprocess.run(
        (
            "python3", "-c", remote_program,
            REPOSITORY, "2931", BRANCH, SHA, VALIDATION_ID,
            "forged-request", CURRENT_NAME,
        ),
        env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert invalid.returncode == 0
    assert '"invalid-codespaces-host-identity"' in invalid.stdout
    assert '"codespaces-workspace-unavailable"' not in invalid.stdout


def test_transport_loss_cannot_claim_no_workspace_effects():
    request = build_dev_validation_request(repository=REPOSITORY, issue_number=2931,
        branch=BRANCH, source_sha=SHA, validation_id=VALIDATION_ID)
    def timeout_run(argv, *, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)
    def failed_run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="connection lost")
    def malformed_run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout="unframed", stderr="")
    for runner in (timeout_run, failed_run, malformed_run):
        result = run_dev_validation_over_codespaces(request, codespace_name=CURRENT_NAME, run=runner)
        assert result["status"] == "needs-decision"
        assert result["workspace_side_effects_performed"] is None
        assert result["cleanup_complete"] is False
