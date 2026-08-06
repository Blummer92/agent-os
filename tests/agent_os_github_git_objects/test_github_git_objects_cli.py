from __future__ import annotations

import json

import pytest

from scripts.agent_os_github_git_objects import cli
from scripts.agent_os_github_git_objects.models import AtomicCommitReason
from tests.agent_os_github_git_objects.test_atomic_commit import (
    FakeTransport,
    HEAD,
    PRODUCTION_BLOB,
    PRODUCTION_PATH,
    REPOSITORY,
    TEST_BLOB,
    TEST_PATH,
)


def manifest() -> dict:
    return {
        "repository": REPOSITORY,
        "branch": "agent/917-two-phase-planning-binding",
        "expected_head_sha": HEAD,
        "allowed_paths": [PRODUCTION_PATH, TEST_PATH],
        "entries": [
            {"path": PRODUCTION_PATH, "mode": "100644", "type": "blob", "sha": PRODUCTION_BLOB},
            {"path": TEST_PATH, "mode": "100644", "type": "blob", "sha": TEST_BLOB},
        ],
        "message": "[Standards] Add explicit issue planning context",
        "invocation_id": "issue-917-publication",
        "prior_fingerprints": [],
    }


def test_manifest_and_confirmation_are_closed_schema() -> None:
    request = cli.request_from_payload(manifest())
    assert request.repository == REPOSITORY
    with pytest.raises(ValueError, match="unsupported"):
        cli.request_from_payload({**manifest(), "endpoint": "/anything"})
    malformed = manifest()
    malformed["entries"] = [{**malformed["entries"][0], "url": "https://example.test"}]
    with pytest.raises(ValueError, match="unsupported"):
        cli.request_from_payload(malformed)

    confirmation = {
        "invocation_id": "issue-917-publication",
        "operation_fingerprint": "a" * 64,
        "repository": REPOSITORY,
        "branch": "agent/917-two-phase-planning-binding",
        "expected_head_sha": HEAD,
        "confirmed": True,
    }
    assert cli.confirmation_from_payload(confirmation).confirmed is True
    with pytest.raises(ValueError, match="unsupported"):
        cli.confirmation_from_payload({**confirmation, "force": True})


def test_plan_cli_emits_stable_json_and_performs_reads_only(tmp_path, monkeypatch, capsys) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest()), encoding="utf-8")
    transport = FakeTransport()
    monkeypatch.setattr(cli, "_transport_from_environment", lambda: transport)

    assert cli.main(["plan", "--manifest", str(manifest_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == AtomicCommitReason.PLAN_READY.value
    assert output["status"] == "planned"
    assert not any(call[0].startswith("create_") or call[0] == "update_ref" for call in transport.calls)


def test_execute_cli_requires_matching_confirmation(tmp_path, monkeypatch, capsys) -> None:
    manifest_path = tmp_path / "manifest.json"
    confirmation_path = tmp_path / "confirmation.json"
    manifest_path.write_text(json.dumps(manifest()), encoding="utf-8")

    planning_transport = FakeTransport()
    request = cli.request_from_payload(manifest())
    from scripts.agent_os_github_git_objects.atomic_commit import prepare_atomic_commit_from_blobs

    plan, _result = prepare_atomic_commit_from_blobs(request, planning_transport)
    assert plan is not None
    confirmation_path.write_text(
        json.dumps(
            {
                "invocation_id": request.invocation_id,
                "operation_fingerprint": plan.operation_fingerprint,
                "repository": request.repository,
                "branch": request.branch,
                "expected_head_sha": request.expected_head_sha,
                "confirmed": True,
            }
        ),
        encoding="utf-8",
    )

    execution_transport = FakeTransport()
    monkeypatch.setattr(cli, "_transport_from_environment", lambda: execution_transport)
    assert (
        cli.main(
            [
                "execute",
                "--manifest",
                str(manifest_path),
                "--confirmation-file",
                str(confirmation_path),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ref-updated"
    assert output["force_used"] is False


def test_execute_cli_rejects_mismatched_confirmation(tmp_path, monkeypatch, capsys) -> None:
    manifest_path = tmp_path / "manifest.json"
    confirmation_path = tmp_path / "confirmation.json"
    manifest_path.write_text(json.dumps(manifest()), encoding="utf-8")
    confirmation_path.write_text(
        json.dumps(
            {
                "invocation_id": "issue-917-publication",
                "operation_fingerprint": "a" * 64,
                "repository": REPOSITORY,
                "branch": "agent/917-two-phase-planning-binding",
                "expected_head_sha": HEAD,
                "confirmed": True,
            }
        ),
        encoding="utf-8",
    )
    transport = FakeTransport()
    monkeypatch.setattr(cli, "_transport_from_environment", lambda: transport)
    assert (
        cli.main(
            [
                "execute",
                "--manifest",
                str(manifest_path),
                "--confirmation-file",
                str(confirmation_path),
            ]
        )
        != 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["reason"] == AtomicCommitReason.CONFIRMATION_MISMATCHED.value
    assert not any(call[0].startswith("create_") or call[0] == "update_ref" for call in transport.calls)


def test_cli_does_not_expose_force_endpoint_or_auth_setup_flags() -> None:
    help_text = cli.build_parser().format_help()
    assert "--force" not in help_text
    assert "endpoint" not in help_text
    assert "auth" not in help_text.casefold()


def test_cli_diagnostic_redacts_tokens() -> None:
    value = cli._sanitize_diagnostic(
        "token=super-secret ghp_1234567890 github_pat_abcdefghij Bearer abc.def"
    )
    assert "super-secret" not in value
    assert "ghp_1234567890" not in value
    assert "github_pat_abcdefghij" not in value
    assert "Bearer abc.def" not in value
    assert "[redacted]" in value
