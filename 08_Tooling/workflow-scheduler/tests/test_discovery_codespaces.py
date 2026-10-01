from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from workflow_scheduler.governance.dev_validation import REPOSITORY
from workflow_scheduler.governance.discovery_codespaces import (
    DiscoveryRequest,
    _REMOTE_DISCOVERY_SOURCE,
    run_discovery_over_codespaces,
    select_codespaces_discovery,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    IssueCommentIngressResult,
)

APPROVED_CODESPACE_NAME = "fluffy-current-agentos-7x9q"

FRAME_START = "===AGENT-OS-CODESPACES-DISCOVERY-JSON-BEGIN==="
FRAME_END = "===AGENT-OS-CODESPACES-DISCOVERY-JSON-END==="


def _ingress(reason: str = "accepted-discovery-envelope") -> IssueCommentIngressResult:
    return IssueCommentIngressResult(
        schema_version="1.0",
        status="accepted",
        reason=reason,
        repository=REPOSITORY,
        issue_number=2931,
        comment_id=1,
        actor="Blummer92",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-trigger:test",
        run_attempt=1,
    )


def _codespace_payload(*, state: str = "Available") -> str:
    item = {
        "name": APPROVED_CODESPACE_NAME,
        "state": state,
        "owner": {"login": "Blummer92"},
        "repository": {"full_name": REPOSITORY},
    }
    return json.dumps({"total_count": 1, "codespaces": [item]})


def _listing_run(stdout: str):
    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    return run


def _discovery_payload(**overrides) -> dict:
    payload = {
        "schema_version": "1.0",
        "status": "not-found",
        "reason_codes": ["no-matching-descriptor"],
        "repository": REPOSITORY,
        "issue_number": 2931,
        "matching_descriptor_count": 0,
        "handoff_id": None,
        "result_id": "discovery-result-1",
        "execution_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
        "codespaces_profile_id": "agent-os-codespaces-v1",
        "execution_surface_id": f"codespace:{APPROVED_CODESPACE_NAME}",
    }
    payload.update(overrides)
    return payload


def _framed(payload: dict) -> str:
    return f"prefix-noise\n{FRAME_START}{json.dumps(payload)}{FRAME_END}\ntrailing-noise\n"


def test_non_discovery_envelope_not_selected() -> None:
    route, request = select_codespaces_discovery(_ingress("accepted-dev-validation-envelope"))
    assert route["selected"] is False
    assert route["reason_codes"] == ["not-discovery-envelope"]
    assert request is None


def test_missing_credential_fails_closed_without_probe(monkeypatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    calls = []

    def run(argv, *, timeout):
        calls.append(argv)
        raise AssertionError("gh must not run without a credential")

    route, request = select_codespaces_discovery(_ingress(), run=run)
    assert route["selected"] is False
    assert route["reason_codes"] == ["codespaces-credential-unavailable"]
    assert request is not None
    assert calls == []


def test_current_available_codespace_selected(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    route, request = select_codespaces_discovery(_ingress(), run=_listing_run(_codespace_payload()))
    assert route["selected"] is True
    assert route["codespace_name"] == APPROVED_CODESPACE_NAME
    assert route["execution_surface_id"] == f"codespace:{APPROVED_CODESPACE_NAME}"
    assert request == DiscoveryRequest(repository=REPOSITORY, issue_number=2931)


def test_zero_codespaces_not_selected(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    empty = json.dumps({"total_count": 0, "codespaces": []})
    route, _ = select_codespaces_discovery(_ingress(), run=_listing_run(empty))
    assert route["selected"] is False


def test_run_returns_bound_discovery_evidence() -> None:
    request = DiscoveryRequest(repository=REPOSITORY, issue_number=2931)

    def run(argv, *, timeout):
        assert argv[0:4] == ("gh", "codespace", "ssh", "-c")
        assert argv[4] == APPROVED_CODESPACE_NAME
        assert argv[5] == "--"
        assert argv[6] == "python3"
        assert argv[7] == "-c"
        assert argv[8] == _REMOTE_DISCOVERY_SOURCE
        assert argv[9] == REPOSITORY
        assert argv[10] == "2931"
        return subprocess.CompletedProcess(argv, 0, stdout=_framed(_discovery_payload()), stderr="")

    result = run_discovery_over_codespaces(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    discovery = result["discovery"]
    assert result["codespaces_capable"] is True
    assert discovery["status"] == "not-found"
    assert discovery["execution_surface_id"] == f"codespace:{APPROVED_CODESPACE_NAME}"
    assert discovery["execution_authorized"] is False
    assert discovery["scheduler_invoked"] is False
    assert discovery["side_effects_performed"] is False


def test_run_ssh_failure_fails_closed() -> None:
    request = DiscoveryRequest(repository=REPOSITORY, issue_number=2931)

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    result = run_discovery_over_codespaces(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    discovery = result["discovery"]
    assert discovery["status"] == "needs-decision"
    assert discovery["reason_codes"] == ["discovery-codespaces-ssh-failed"]


def test_run_invalid_frame_fails_closed() -> None:
    request = DiscoveryRequest(repository=REPOSITORY, issue_number=2931)

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout="no frame here", stderr="")

    result = run_discovery_over_codespaces(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["discovery"]["reason_codes"] == ["discovery-codespaces-frame-invalid"]


def test_run_identity_mismatch_fails_closed() -> None:
    request = DiscoveryRequest(repository=REPOSITORY, issue_number=2931)
    payload = _discovery_payload(issue_number=9999)

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=_framed(payload), stderr="")

    result = run_discovery_over_codespaces(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["discovery"]["reason_codes"] == ["discovery-codespaces-identity-mismatch"]


def test_run_repo_unavailable_marks_surface_incapable() -> None:
    request = DiscoveryRequest(repository=REPOSITORY, issue_number=2931)
    payload = _discovery_payload(
        status="needs-decision",
        reason_codes=["codespaces-discovery-repo-unavailable"],
    )

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=_framed(payload), stderr="")

    result = run_discovery_over_codespaces(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["codespaces_capable"] is False
    assert result["discovery"]["reason_codes"] == ["codespaces-discovery-repo-unavailable"]


def test_run_store_unavailable_marks_surface_incapable() -> None:
    request = DiscoveryRequest(repository=REPOSITORY, issue_number=2931)
    payload = _discovery_payload(
        status="needs-decision",
        reason_codes=["codespaces-discovery-store-unavailable"],
    )

    def run(argv, *, timeout):
        return subprocess.CompletedProcess(argv, 0, stdout=_framed(payload), stderr="")

    result = run_discovery_over_codespaces(request, codespace_name=APPROVED_CODESPACE_NAME, run=run)
    assert result["codespaces_capable"] is False
    assert result["discovery"]["reason_codes"] == ["codespaces-discovery-store-unavailable"]


def test_remote_source_rejects_missing_store() -> None:
    # The remote runner fails closed when the host-local checkpoint store is
    # absent instead of returning a misleading not-found. Runs from the repo
    # worktree so the repository resolves via git, with a bogus store root.
    import subprocess as sp

    repo_root = Path(__file__).resolve().parents[3]
    completed = sp.run(
        ["python3", "-c", _REMOTE_DISCOVERY_SOURCE, REPOSITORY, "2931", "some-codespace"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(repo_root),
        env={"AGENT_OS_CHECKPOINT_STORE_ROOT": "/nonexistent-store-root-2931"},
    )
    assert completed.returncode == 0
    start = completed.stdout.find(FRAME_START)
    end = completed.stdout.find(FRAME_END)
    payload = json.loads(completed.stdout[start + len(FRAME_START) : end])
    assert payload["reason_codes"] == ["codespaces-discovery-store-unavailable"]


def test_run_rejects_unresolved_codespace_name() -> None:
    request = DiscoveryRequest(repository=REPOSITORY, issue_number=2931)
    with pytest.raises(ValueError):
        run_discovery_over_codespaces(request, codespace_name="../evil")


def test_remote_source_rejects_non_canonical_identity() -> None:
    # The remote runner validates its own argv: run it locally with a bad repo.
    import subprocess as sp

    completed = sp.run(
        ["python3", "-c", _REMOTE_DISCOVERY_SOURCE, "evil/repo", "2931", "some-codespace"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0
    start = completed.stdout.find(FRAME_START)
    end = completed.stdout.find(FRAME_END)
    payload = json.loads(completed.stdout[start + len(FRAME_START) : end])
    assert payload["reason_codes"] == ["codespaces-discovery-identity-rejected"]
