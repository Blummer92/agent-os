from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-all.sh"
TIMING_LINE = re.compile(r"^- .+ \| (?:[0-9]+\.[0-9]{3} s|unavailable)$", re.MULTILINE)


def _make_repo(tmp_path: Path, *, structure_exit: int = 0) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "07_Agent_Tests").mkdir()
    (repo / "tests").mkdir()
    shutil.copy2(SCRIPT, repo / "scripts" / "validate-all.sh")
    (repo / "07_Agent_Tests" / "validate-repo-structure.sh").write_text(
        f"#!/usr/bin/env bash\nexit {structure_exit}\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_sample.py").write_text(
        "def test_sample():\n    assert True\n",
        encoding="utf-8",
    )
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHON_BIN"] = shutil.which("python") or shutil.which("python3") or "python3"
    return subprocess.run(
        ["bash", "scripts/validate-all.sh", *args],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_validate_all_reports_structure_suite_and_total_timings(tmp_path: Path) -> None:
    """Issue #1359: successful aggregate execution emits observational timings."""
    repo = _make_repo(tmp_path)

    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "TIMING RESULTS\n" in result.stdout
    assert re.search(r"^- structural validation \| [0-9]+\.[0-9]{3} s$", result.stdout, re.MULTILINE)
    assert re.search(r"^- root \| [0-9]+\.[0-9]{3} s$", result.stdout, re.MULTILINE)
    assert re.search(r"^- aggregate total \| [0-9]+\.[0-9]{3} s$", result.stdout, re.MULTILINE)
    assert len(TIMING_LINE.findall(result.stdout)) == 3
    assert "OVERALL STATUS\nPASS\n\nEXIT CODE\n0\n" in result.stdout


def test_validate_all_timing_does_not_change_failure_exit_semantics(tmp_path: Path) -> None:
    """Issue #1359: timing never converts an existing failed check into success."""
    repo = _make_repo(tmp_path, structure_exit=7)

    result = _run(repo)

    assert result.returncode == 1
    assert "- FAIL | structural validation | exit 7 | bash 07_Agent_Tests/validate-repo-structure.sh" in result.stdout
    assert "- structural validation | exit 7 | bash 07_Agent_Tests/validate-repo-structure.sh" in result.stdout
    assert re.search(r"^- structural validation \| [0-9]+\.[0-9]{3} s$", result.stdout, re.MULTILINE)
    assert re.search(r"^- root \| [0-9]+\.[0-9]{3} s$", result.stdout, re.MULTILINE)
    assert re.search(r"^- aggregate total \| [0-9]+\.[0-9]{3} s$", result.stdout, re.MULTILINE)
    assert "OVERALL STATUS\nFAIL\n\nEXIT CODE\n1\n" in result.stdout


def test_validate_all_focused_check_uses_same_timing_boundary(tmp_path: Path) -> None:
    """Issue #1359: an existing focused check gains timing without changing its command."""
    repo = _make_repo(tmp_path)

    result = _run(repo, "--focused", "tests/test_sample.py", "--focused-maxfail", "1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "python" in result.stdout
    assert "- PASS | focused: tests/test_sample.py | exit 0 |" in result.stdout
    assert "- focused: tests/test_sample.py |" in result.stdout
    assert len(TIMING_LINE.findall(result.stdout)) == 4


def test_validate_all_excludes_transient_tmp_test_trees(tmp_path: Path) -> None:
    """Issue #1915: repository-local .tmp suites are not canonical aggregate suites."""
    repo = _make_repo(tmp_path)
    package_tests = repo / "package" / "tests"
    package_tests.mkdir(parents=True)
    (package_tests / "test_package.py").write_text(
        "def test_package():\n    assert True\n",
        encoding="utf-8",
    )
    transient_tests = repo / ".tmp" / "isolation-copy" / "package" / "tests"
    transient_tests.mkdir(parents=True)
    (transient_tests / "test_transient_failure.py").write_text(
        "def test_transient_failure():\n    assert False, 'transient suite must not run'\n",
        encoding="utf-8",
    )

    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "- PASS | package | exit 0 |" in result.stdout
    assert ".tmp/isolation-copy/package" not in result.stdout
    assert "transient suite must not run" not in result.stdout
    assert "OVERALL STATUS\nPASS\n\nEXIT CODE\n0\n" in result.stdout


def test_validate_all_focused_behavior_ignores_tmp_aggregate_exclusion(tmp_path: Path) -> None:
    """Issue #1915: aggregate .tmp exclusion does not alter focused validation."""
    repo = _make_repo(tmp_path)

    result = _run(repo, "--focused", "tests/test_sample.py", "--focused-maxfail", "1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "- PASS | focused: tests/test_sample.py | exit 0 |" in result.stdout
