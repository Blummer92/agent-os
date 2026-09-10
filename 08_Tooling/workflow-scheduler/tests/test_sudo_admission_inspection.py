from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflow_scheduler.governance import sudo_admission_inspection as sudo

EXPECTED = "36ccd1715b8b11e30f8d92196b8e7f0791c10547"
STALE = "8ff48b3f59020326dadf255e05d6140d8ea6d9d0"


def _meta(path: str, **overrides):
    value = {"path": path, "exists": True, "symlink": False, "uid": 0, "gid": 0, "mode": "0755"}
    value.update(overrides)
    return value


def _payload(**overrides):
    value = {
        "status": "observed",
        "disposition": "current-sha-rule",
        "expected_source_sha": EXPECTED,
        "authorized_source_sha": EXPECTED,
        "authorized_source_sha_count": 1,
        "exact_command_admitted": True,
        "alternate_command_admitted": False,
        "broad_privilege_detected": False,
        "effective_principal": "sa_agent_os",
        "helper": _meta(sudo.HELPER),
        "trusted_ancestors": [_meta(path) for path in ("/", "/usr", "/usr/local", "/usr/local/libexec")],
        "policy_line_count": 1,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "discovery_invoked": False,
        "resume_invoked": False,
        "side_effects_performed": False,
    }
    value.update(overrides)
    return value


def _result(payload: object, *, returncode: int = 0):
    stdout = f"noise\n{sudo._FRAME_START}\n{json.dumps(payload)}\n{sudo._FRAME_END}\n"
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def test_expected_sha_is_read_from_exactly_one_workflow_literal(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(f"env:\n  HOST_RUNTIME_SOURCE_SHA: {EXPECTED}\n", encoding="utf-8")
    assert sudo.expected_runtime_source_sha(workflow) == EXPECTED


@pytest.mark.parametrize(
    "text",
    (
        "name: missing\n",
        f"env:\n  HOST_RUNTIME_SOURCE_SHA: {EXPECTED}\n  HOST_RUNTIME_SOURCE_SHA: {EXPECTED}\n",
        f"env:\n  HOST_RUNTIME_SOURCE_SHA: {EXPECTED}\n  HOST_RUNTIME_SOURCE_SHA: {STALE}\n",
    ),
)
def test_missing_or_duplicate_workflow_pin_fails_closed(tmp_path: Path, text: str) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="runtime-source-sha-unavailable"):
        sudo.expected_runtime_source_sha(workflow)


def test_valid_projected_evidence_is_bounded_and_preserves_non_authority() -> None:
    payload = _payload(secret="must-not-escape", unrelated={"huge": "x" * 1000})
    result = sudo.collect_sudo_admission(lambda command: _result(payload), EXPECTED)
    assert result["disposition"] == "current-sha-rule"
    assert result["authorized_source_sha"] == EXPECTED
    assert result["execution_authorized"] is False
    assert result["scheduler_invoked"] is False
    assert result["discovery_invoked"] is False
    assert result["resume_invoked"] is False
    assert result["side_effects_performed"] is False
    assert "secret" not in result
    assert "unrelated" not in result


def test_stale_literal_sha_classification_is_preserved() -> None:
    result = sudo.collect_sudo_admission(
        lambda command: _result(
            _payload(
                disposition="old-sha-rule",
                authorized_source_sha=STALE,
                exact_command_admitted=False,
            )
        ),
        EXPECTED,
    )
    assert result["disposition"] == "old-sha-rule"
    assert result["authorized_source_sha"] == STALE


@pytest.mark.parametrize("disposition", ("wrong-principal", "helper-bootstrap-drift", "other-bounded-sudo-defect"))
def test_finite_refusal_dispositions_are_preserved(disposition: str) -> None:
    result = sudo.collect_sudo_admission(lambda command: _result(_payload(disposition=disposition)), EXPECTED)
    assert result["disposition"] == disposition
    assert result["execution_authorized"] is False


def test_missing_rule_is_finite_and_fail_closed() -> None:
    result = sudo.collect_sudo_admission(
        lambda command: _result(
            _payload(
                disposition="missing-rule",
                authorized_source_sha=None,
                authorized_source_sha_count=0,
                exact_command_admitted=False,
            )
        ),
        EXPECTED,
    )
    assert result["disposition"] == "missing-rule"


def test_broad_or_alternate_admission_is_unsafe() -> None:
    result = sudo.collect_sudo_admission(
        lambda command: _result(
            _payload(
                disposition="unexpected-broad-privilege",
                alternate_command_admitted=True,
                broad_privilege_detected=True,
            )
        ),
        EXPECTED,
    )
    assert result["disposition"] == "unexpected-broad-privilege"
    assert result["broad_privilege_detected"] is True


def test_remote_command_is_fixed_and_contains_required_classifier_checks() -> None:
    command = sudo.command(EXPECTED)
    assert command.startswith("/usr/bin/python3 -c ")
    assert sudo.HELPER in command
    assert "sudo" in command
    assert "--source-sha" in command
    assert "NOPASSWD: ALL" in command
    assert "wrong-principal" in command
    assert "helper-bootstrap-drift" in command
    assert "unexpected-broad-privilege" in command
    assert "/etc/sudoers" not in command
    assert "cat " not in command


def test_malformed_failed_or_oversized_evidence_returns_finite_unavailable() -> None:
    failed = sudo.collect_sudo_admission(lambda command: SimpleNamespace(returncode=1, stdout="", stderr="secret"), EXPECTED)
    assert failed["reason_codes"] == ["sudo-inspection-command-failed"]
    assert "stderr" not in failed

    malformed = sudo.collect_sudo_admission(
        lambda command: SimpleNamespace(returncode=0, stdout="not framed", stderr=""), EXPECTED
    )
    assert malformed["reason_codes"] == ["sudo-inspection-frame-invalid"]

    oversized = _payload(effective_principal="a" * 129)
    invalid = sudo.collect_sudo_admission(lambda command: _result(oversized), EXPECTED)
    assert invalid["reason_codes"] == ["sudo-inspection-contract-violation"]


def test_contradictory_remote_claims_fail_closed() -> None:
    contradictory = _payload(disposition="current-sha-rule", exact_command_admitted=False)
    result = sudo.collect_sudo_admission(lambda command: _result(contradictory), EXPECTED)
    assert result["disposition"] == "inspection-unavailable"
    assert result["reason_codes"] == ["sudo-inspection-contract-violation"]
