from __future__ import annotations

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


def test_pytest_argv_gets_unique_junit_and_npm_does_not(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(argv, cwd, check, env):
        calls.append((tuple(argv), Path(cwd)))
        for arg in argv:
            if isinstance(arg, str) and arg.startswith("--junitxml="):
                junit_path = Path(arg.split("=", 1)[1])
                junit_path.parent.mkdir(parents=True, exist_ok=True)
                junit_path.write_text(
                    '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1" '
                    'failures="0" errors="0" skipped="0"><testcase classname="m" name="t"/></testsuite></testsuites>',
                    encoding="utf-8",
                )
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_current_head", lambda: "a" * 40)
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    module.execute_focused(
        _plan(["python -m pytest tests/agent_os_issue_acceptance", "cd 08_Tooling/instructional-materials-coach/capture && npm test"], "a" * 40),
        expected_head_sha="a" * 40,
    )
    pytest_argv = calls[0][0]
    assert any(arg.startswith("--junitxml=") for arg in pytest_argv)
    assert not any("--junitxml" in arg for arg in calls[1][0])
    manifest = (tmp_path / "manifest.tsv").read_text(encoding="utf-8")
    assert "EXECUTED_PASS" in manifest
    assert "NODE_REPORTER_NOT_AVAILABLE" in manifest
    xml_files = list(tmp_path.glob("*.xml"))
    assert len(xml_files) == 1  # only the pytest command, never npm


def test_failed_pytest_writes_manifest_then_still_raises(monkeypatch, tmp_path: Path) -> None:
    def fake_run(argv, cwd, check, env):
        if check:
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_current_head", lambda: "a" * 40)
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    with pytest.raises(subprocess.CalledProcessError):
        module.execute_focused(
            _plan(["python -m pytest tests/agent_os_issue_acceptance"], "a" * 40),
            expected_head_sha="a" * 40,
        )
    manifest = (tmp_path / "manifest.tsv").read_text(encoding="utf-8")
    assert "EXECUTED_FAIL" in manifest


def test_junit_path_is_unique_per_command_index() -> None:
    p0 = module._junit_path_for_command("python -m pytest tests/a", Path("/tmp/j"), 0)
    p1 = module._junit_path_for_command("python -m pytest tests/a", Path("/tmp/j"), 1)
    assert p0 != p1
    assert p0.suffix == ".xml"
    assert ".." not in p0.name and "/" not in p0.name
