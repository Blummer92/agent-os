from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from workflow_scheduler.governance import sudo_admission_inspection as sudo

EXPECTED = "36ccd1715b8b11e30f8d92196b8e7f0791c10547"


def _result(payload: dict[str, object], *, returncode: int = 0):
    stdout = f"noise\n{sudo._FRAME_START}\n{json.dumps(payload)}\n{sudo._FRAME_END}\n"
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


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
        "helper": {"path": sudo.HELPER, "exists": True},
        "trusted_ancestors": [],
        "policy_line_count": 1,
        "execution_authorized": False,
        "side_effects_performed": False,
    }
    value.update(overrides)
    return value


def test_expected_sha_is_read_from_single_fixed_workflow_literal(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(f"env:\n  HOST_RUNTIME_SOURCE_SHA: {EXPECTED}\n", encoding="utf-8")
    assert sudo.expected_runtime_source_sha(workflow) == EXPECTED


def test_duplicate_or_missing_workflow_pin_fails_closed(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text("name: missing\n", encoding="utf-8")
    try:
        sudo.expected_runtime_source_sha(workflow)
    except ValueError as exc:
        assert str(exc) == "runtime-source-sha-unavailable"
    else:
        raise AssertionError("missing pin must fail closed")


def test_exact_current_sha_classification_is_preserved() -> None:
    result = sudo.collect_sudo_admission(lambda command: _result(_payload()), EXPECTED)
    assert result["disposition"] == "current-sha-rule"
    assert result["exact_command_admitted"] is True
    assert result["alternate_command_admitted"] is False
    assert result["execution_authorized"] is False
    assert result["side_effects_performed"] is False


def test_stale_literal_sha_classification_is_preserved() -> None:
    stale = "8ff48b3f59020326dadf255e05d6140d8ea6d9d0"
    result = sudo.collect_sudo_admission(
        lambda command: _result(_payload(disposition="old-sha-rule", authorized_source_sha=stale, exact_command_admitted=False)),
        EXPECTED,
    )
    assert result["disposition"] == "old-sha-rule"
    assert result["authorized_source_sha"] == stale


def test_broad_or_alternate_admission_is_unsafe() -> None:
    result = sudo.collect_sudo_admission(
        lambda command: _result(_payload(disposition="unexpected-broad-privilege", alternate_command_admitted=True, broad_privilege_detected=True)),
        EXPECTED,
    )
    assert result["disposition"] == "unexpected-broad-privilege"
    assert result["broad_privilege_detected"] is True


def test_remote_command_is_fixed_and_has_no_arbitrary_input_surface() -> None:
    command = sudo.command(EXPECTED)
    assert command.startswith("/usr/bin/python3 -c ")
    assert sudo.HELPER in command
    assert "sudo" in command
    assert "--source-sha" in command
    assert "/etc/sudoers" not in command
    assert "cat " not in command


def test_malformed_or_failed_evidence_returns_finite_unavailable() -> None:
    failed = sudo.collect_sudo_admission(lambda command: SimpleNamespace(returncode=1, stdout="", stderr="secret"), EXPECTED)
    assert failed["disposition"] == "inspection-unavailable"
    assert failed["reason_codes"] == ["sudo-inspection-command-failed"]
    assert "stderr" not in failed
