"""Unit tests for the governed orchestrator -> Codespace command transport (#3333).

All external effects (Codespace listing, command execution) are injected as
fakes. No test touches the network, subprocess, or a real Codespace.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_execution_interface.codespaces_orchestrator_transport import (
    CodespaceCandidate,
    TransportReason,
    TransportRequest,
    TransportResult,
    TransportStatus,
    resolve_current_codespace,
    run_codespace_transport,
    transport_request_id,
    validate_argv,
)

REPO = "Blummer92/agent-os"
BASE_SHA = "c1101391123c48ff28e91dc8ba0aa31b88598ef2"


def _candidate(name="happy-codespace", state="Available"):
    return CodespaceCandidate(
        name=name,
        state=state,
        repository_full_name=REPO,
        owner_login="Blummer92",
    )


def _request(**overrides):
    args = {
        "repository": REPO,
        "issue_identity": "3333",
        "admission_id": "admission-1",
        "argv": ("git", "status", "--short"),
    }
    args.update(overrides)
    return TransportRequest(**args)


def _ok_run(argv, timeout_seconds):
    assert argv[:5] == ("gh", "codespace", "ssh", "-c", "happy-codespace")
    assert argv[5] == "--"
    return 0, "stdout-ok", ""


def _list_one():
    return (_candidate(),)


# --- resolution ------------------------------------------------------------


def test_resolve_exactly_one_qualified():
    codespace, reason = resolve_current_codespace((_candidate(),))
    assert reason is TransportReason.OK
    assert codespace is not None and codespace.name == "happy-codespace"


def test_resolve_zero_qualified_fails_closed():
    codespace, reason = resolve_current_codespace(())
    assert codespace is None
    assert reason is TransportReason.NO_QUALIFIED_CODESPACE


def test_resolve_filters_unavailable_and_foreign():
    candidates = (
        _candidate("stale-one", state="Stopped"),
        CodespaceCandidate(
            name="foreign-repo",
            state="Available",
            repository_full_name="someone-else/other",
            owner_login="someone-else",
        ),
        _candidate(),
    )
    codespace, reason = resolve_current_codespace(candidates)
    assert reason is TransportReason.OK
    assert codespace is not None and codespace.name == "happy-codespace"


def test_resolve_multiple_qualified_fails_closed():
    candidates = (_candidate("one"), _candidate("two"))
    codespace, reason = resolve_current_codespace(candidates)
    assert codespace is None
    assert reason is TransportReason.MULTIPLE_QUALIFIED_CODESPACES


def test_candidate_rejects_bad_identity():
    with pytest.raises(ValueError):
        CodespaceCandidate(
            name="not a name!",
            state="Available",
            repository_full_name=REPO,
            owner_login="Blummer92",
        )


# --- argv guardrails --------------------------------------------------------


def test_benign_argv_accepted():
    assert validate_argv(("git", "status", "--short")) is None
    assert validate_argv(("python", "-m", "pytest", "tests/x")) is None
    assert validate_argv(("git", "worktree", "add", "--detach", "/tmp/w", "abc123")) is None


def test_git_push_rejected():
    assert validate_argv(("git", "push", "origin", "main")) is TransportReason.FORBIDDEN_COMMAND
    assert validate_argv(("git", "-c", "x=y", "push")) is TransportReason.FORBIDDEN_COMMAND


def test_gh_payload_rejected():
    assert validate_argv(("gh", "api", "repos/x", "--method", "GET")) is TransportReason.FORBIDDEN_COMMAND
    assert validate_argv(("gh", "pr", "create")) is TransportReason.FORBIDDEN_COMMAND
    assert validate_argv(("gh", "auth", "status")) is TransportReason.FORBIDDEN_COMMAND


def test_empty_and_nul_argv_rejected():
    assert validate_argv(()) is TransportReason.INVALID_REQUEST
    assert validate_argv(("git", "")) is TransportReason.INVALID_REQUEST
    assert validate_argv(("git", "a\x00b")) is TransportReason.INVALID_REQUEST


def test_request_rejects_non_tuple_argv():
    with pytest.raises(ValueError):
        _request(argv="git status")


def test_request_rejects_bad_sha_and_timeout():
    with pytest.raises(ValueError):
        _request(base_sha_or_none="not-a-sha")
    with pytest.raises(ValueError):
        _request(timeout_seconds=0)
    with pytest.raises(ValueError):
        _request(timeout_seconds=99999)


def test_request_rejects_wrong_repository():
    with pytest.raises(ValueError):
        _request(repository="someone-else/other")


def test_request_id_is_deterministic_and_verified():
    first = _request()
    second = _request()
    assert first.request_id == second.request_id == transport_request_id(first)
    assert len(first.request_id) == 64
    with pytest.raises(ValueError):
        _request(request_id="0" * 64)


# --- transport execution ----------------------------------------------------


def test_successful_transport_returns_structured_evidence():
    result = run_codespace_transport(
        _request(base_sha_or_none=BASE_SHA, workdir_or_none="/workspaces/agent-os"),
        list_candidates=_list_one,
        run=_ok_run,
    )
    assert result.status is TransportStatus.COMPLETED
    assert result.reason_codes == (TransportReason.OK,)
    assert result.codespace_name_or_none == "happy-codespace"
    assert result.exit_status_or_none == 0
    assert result.stdout_tail == "stdout-ok"
    assert result.stdout_truncated is False
    assert result.duration_ms >= 0
    assert result.issue_identity == "3333"
    assert result.base_sha_or_none == BASE_SHA
    assert result.workdir_or_none == "/workspaces/agent-os"
    assert result.side_effect_classification == "repository-execution-only"
    # Authority can never be granted by the transport.
    assert result.github_writes_authorized is False
    assert result.execution_authorized is False
    assert result.publication_authorized is False
    assert result.merge_authorized is False
    payload = result.to_dict()
    assert payload["status"] == "completed"
    assert payload["reason_codes"] == ["ok"]


def test_forbidden_command_rejected_before_transport():
    calls = []

    def _run(argv, timeout_seconds):
        calls.append(argv)
        return 0, "", ""

    result = run_codespace_transport(
        _request(argv=("git", "push", "origin", "main")),
        list_candidates=_list_one,
        run=_run,
    )
    assert result.status is TransportStatus.REJECTED
    assert result.reason_codes == (TransportReason.FORBIDDEN_COMMAND,)
    assert calls == []
    assert result.exit_status_or_none is None


def test_no_qualified_codespace_fails_closed():
    result = run_codespace_transport(
        _request(), list_candidates=lambda: (), run=_ok_run
    )
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.NO_QUALIFIED_CODESPACE,)
    assert result.codespace_name_or_none is None


def test_explicit_codespace_mismatch_fails_closed():
    result = run_codespace_transport(
        _request(codespace_name_or_none="other-codespace"),
        list_candidates=_list_one,
        run=_ok_run,
    )
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.CODESPACE_IDENTITY_MISMATCH,)


def test_explicit_codespace_match_succeeds():
    result = run_codespace_transport(
        _request(codespace_name_or_none="happy-codespace"),
        list_candidates=_list_one,
        run=_ok_run,
    )
    assert result.status is TransportStatus.COMPLETED


def test_lister_exception_becomes_transport_error():
    def _boom():
        raise RuntimeError("network down")

    result = run_codespace_transport(_request(), list_candidates=_boom, run=_ok_run)
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.TRANSPORT_ERROR,)


def test_run_exception_becomes_transport_error():
    def _boom(argv, timeout_seconds):
        raise OSError("ssh failed")

    result = run_codespace_transport(
        _request(), list_candidates=_list_one, run=_boom
    )
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.TRANSPORT_ERROR,)


def test_timeout_becomes_reason_coded_failure():
    import subprocess

    def _timeout(argv, timeout_seconds):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout_seconds)

    result = run_codespace_transport(
        _request(), list_candidates=_list_one, run=_timeout
    )
    assert result.status is TransportStatus.FAILED
    assert result.reason_codes == (TransportReason.TRANSPORT_TIMEOUT,)


def test_output_is_bounded_with_truncation_flags():
    big = "x" * 9000

    def _big(argv, timeout_seconds):
        return 1, big, big

    result = run_codespace_transport(
        _request(), list_candidates=_list_one, run=_big
    )
    assert result.status is TransportStatus.COMPLETED
    assert result.exit_status_or_none == 1
    assert len(result.stdout_tail) == 4096
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_nonzero_exit_is_completed_with_evidence_not_failure():
    def _fail(argv, timeout_seconds):
        return 2, "", "boom"

    result = run_codespace_transport(
        _request(), list_candidates=_list_one, run=_fail
    )
    # A remote command failure is command evidence, not a transport failure.
    assert result.status is TransportStatus.COMPLETED
    assert result.reason_codes == (TransportReason.OK,)
    assert result.exit_status_or_none == 2
    assert result.stderr_tail == "boom"


def test_ssh_argv_shape_has_no_shell():
    seen = []

    def _capture(argv, timeout_seconds):
        seen.append(argv)
        return 0, "", ""

    run_codespace_transport(
        _request(argv=("python", "-m", "pytest", "tests/x")),
        list_candidates=_list_one,
        run=_capture,
    )
    assert seen[0] == (
        "gh",
        "codespace",
        "ssh",
        "-c",
        "happy-codespace",
        "--",
        "python",
        "-m",
        "pytest",
        "tests/x",
    )


def test_result_rejects_bad_authority_override():
    with pytest.raises(ValueError):
        TransportResult(
            request_id="r",
            status=TransportStatus.COMPLETED,
            reason_codes=(TransportReason.OK,),
            codespace_name_or_none="happy-codespace",
            argv=("git", "status"),
            workdir_or_none=None,
            exit_status_or_none=0,
            stdout_tail="",
            stderr_tail="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=0,
            issue_identity="3333",
            base_sha_or_none=None,
            side_effect_classification="something-else",
        )
