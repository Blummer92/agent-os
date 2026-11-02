from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import agent_os_ci_validation as module
from scripts.agent_os_remote_validation import ValidationPlan


def _plan(commands, head: str) -> ValidationPlan:
    return ValidationPlan(
        selector_version="1.0.0",
        repository="Blummer92/agent-os",
        pull_request=1,
        base_sha="b" * 40,
        head_sha=head,
        profile="focused",
        commands=tuple(commands),
        command_set_digest="x",
        reason_codes=(),
        remote_build_required=False,
    )


def _xml(tests=1, failures=0):
    return (
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="{tests}" '
        f'failures="{failures}" errors="0" skipped="0"><testcase classname="m" name="t"/></testsuite></testsuites>'
    )


def test_continues_after_failure_and_receipt_covers_all_commands(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_run(argv, cwd, check, env):
        calls.append(str(argv))
        if len(calls) == 2:
            raise subprocess.CalledProcessError(1, argv)
        for arg in argv:
            if isinstance(arg, str) and arg.startswith("--junitxml="):
                p = Path(arg.split("=", 1)[1])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(_xml(), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_current_head", lambda: "a" * 40)
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    plan = _plan(
        [
            "python -m pytest tests/agent_os_issue_acceptance",
            "python -m pytest tests/agent_os_issue_acceptance",
            "cd 08_Tooling/instructional-materials-coach/capture && npm test",
        ],
        "a" * 40,
    )
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        module.execute_focused(plan, expected_head_sha="a" * 40)
    assert exc_info.value.returncode == 1
    assert len(calls) == 3, "a failed command must not hide later selected commands"
    receipt = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert receipt["selected_count"] == 3
    assert receipt["executed_count"] == 3
    assert receipt["head_sha"] == "a" * 40
    assert receipt["commands"][0]["classification"] == "EXECUTED_PASS"
    assert receipt["commands"][0]["junit_sha256"] is not None
    assert receipt["commands"][0]["junit_counts"]["tests"] == 1
    assert receipt["commands"][1]["classification"] == "EXECUTED_FAIL"
    assert receipt["commands"][1]["exit_code"] == 1
    assert receipt["commands"][2]["language"] == "npm"
    assert receipt["commands"][2]["classification"] == "NODE_REPORTER_NOT_AVAILABLE"
    tsv = (tmp_path / "manifest.tsv").read_text(encoding="utf-8")
    assert "EXECUTED_FAIL" in tsv and "NODE_REPORTER_NOT_AVAILABLE" in tsv


def test_pytest_exit_five_is_zero_collected_not_pass_or_generic_fail(monkeypatch, tmp_path: Path) -> None:
    def fake_run(argv, cwd, check, env):
        for arg in argv:
            if isinstance(arg, str) and arg.startswith("--junitxml="):
                p = Path(arg.split("=", 1)[1])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(_xml(tests=0), encoding="utf-8")
        raise subprocess.CalledProcessError(5, argv)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_current_head", lambda: "a" * 40)
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        module.execute_focused(
            _plan(["python -m pytest tests/agent_os_issue_acceptance"], "a" * 40),
            expected_head_sha="a" * 40,
        )
    assert exc_info.value.returncode == 5
    receipt = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert receipt["commands"][0]["classification"] == "ZERO_COLLECTED"
    assert receipt["commands"][0]["exit_code"] == 5


def test_nonzero_exit_without_junit_is_executed_fail_with_missing_report(monkeypatch, tmp_path: Path) -> None:
    """QA-A D1, adjudicated: a nonzero exit with no JUnit report stays
    EXECUTED_FAIL (the command did run and its exit code is recorded);
    the missing report is carried by junit_sha256=None / junit_counts=None,
    which downstream ingestion must check before treating the failure as
    node-level evidence. Only exit 0 with a missing report is
    NOT_EXECUTED_SETUP_FAILURE."""

    def fake_run(argv, cwd, check, env):
        raise subprocess.CalledProcessError(2, argv)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_current_head", lambda: "a" * 40)
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    with pytest.raises(subprocess.CalledProcessError):
        module.execute_focused(
            _plan(["python -m pytest tests/agent_os_issue_acceptance"], "a" * 40),
            expected_head_sha="a" * 40,
        )
    receipt = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert receipt["commands"][0]["classification"] == "EXECUTED_FAIL"
    assert receipt["commands"][0]["exit_code"] == 2
    assert receipt["commands"][0]["junit_sha256"] is None
    assert receipt["commands"][0]["junit_counts"] is None


def test_unresolvable_command_is_recorded_not_dropped(monkeypatch, tmp_path: Path) -> None:
    def fake_run(argv, cwd, check, env):
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_current_head", lambda: "a" * 40)
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        module.execute_focused(
            _plan(["python -m pytest tests/agent_os_issue_acceptance", "totally-unknown-command"], "a" * 40),
            expected_head_sha="a" * 40,
        )
    receipt = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert receipt["commands"][1]["classification"] == "NOT_EXECUTED"
    assert receipt["commands"][1]["exit_code"] is None

def test_review_3762_malformed_xml_keeps_full_command_receipts(monkeypatch, tmp_path: Path) -> None:
    """An invalid XML report is evidence-invalid, not a receipt-writer crash."""
    calls = []

    def fake_run(argv, cwd, check, env):
        calls.append(tuple(argv))
        for arg in argv:
            if isinstance(arg, str) and arg.startswith("--junitxml="):
                Path(arg.split("=", 1)[1]).write_bytes(b"<broken")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_current_head", lambda: "a" * 40)
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    module.execute_focused(
        _plan(["python -m pytest tests/agent_os_issue_acceptance",
               "python -m pytest tests/agent_os_issue_acceptance"], "a" * 40),
        expected_head_sha="a" * 40,
    )
    receipt = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert receipt["selected_count"] == 2
    assert len(receipt["commands"]) == 2
    assert all(item["junit_counts"] is None for item in receipt["commands"])
