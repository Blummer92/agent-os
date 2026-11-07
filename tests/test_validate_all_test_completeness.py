"""validate-all.sh: a narrowed test selection fails before any suite runs.

Regression for the #3816 false green: ``pytest.ini`` deselecting the
regression-test file let the runner report EXECUTED_PASS for a suite
whose detecting tests never ran. The completeness pre-flight must fail
the run, record TEST_SELECTION_INCOMPLETE in the manifest, write a
machine-readable receipt, and never execute the narrowed suite.

The fake-python shim answers ``--collect-only`` from the files on disk
and, when ``PYTEST_SHIM_DESELECT`` names a file, omits it from the
actual (unfiltered-flag-free) collection only -- the same shape as a
real ``--deselect`` in addopts.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE_SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-all.sh"
HELPER = Path(__file__).parents[1] / "scripts" / "agent_os_ci_test_completeness.py"


def _write_test(path: Path, *, failing: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assertion = "assert False" if failing else "assert True"
    path.write_text(f"def test_example():\n    {assertion}\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SOURCE_SCRIPT, root / "scripts" / "validate-all.sh")
    shutil.copy2(HELPER, root / "scripts" / "agent_os_ci_test_completeness.py")
    os.chmod(root / "scripts" / "validate-all.sh", 0o755)
    structural = root / "07_Agent_Tests" / "validate-repo-structure.sh"
    structural.parent.mkdir(parents=True)
    structural.write_text('#!/usr/bin/env bash\necho "STRUCTURE_MARKER"\nexit 0\n', encoding="utf-8")
    os.chmod(structural, 0o755)
    _write_test(root / "tests" / "test_report.py", failing=True)
    _write_test(root / "tests" / "test_other.py")
    (root / "pytest.ini").write_text(
        "[pytest]\naddopts =\n    --continue-on-collection-errors\n"
        "    --deselect=tests/test_report.py\n",
        encoding="utf-8",
    )
    shim = root / "fake-python"
    shim.write_text(
        "#!" + sys._base_executable + "\n"
        "import os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if args and args[0] == '-':\n"
        "    sys.argv = args\n"
        "    exec(compile(sys.stdin.read(), '<stdin>', 'exec'))\n"
        "    raise SystemExit(0)\n"
        "if args and args[0].endswith('.py') and pathlib.Path(args[0]).is_file():\n"
        "    import runpy\n"
        "    sys.argv = args\n"
        "    runpy.run_path(args[0], run_name='__main__')\n"
        "    raise SystemExit(0)\n"
        "if len(args) >= 3 and args[:2] == ['-m', 'pytest'] and '--collect-only' in args:\n"
        "    deselect = os.environ.get('PYTEST_SHIM_DESELECT', '')\n"
        "    is_reference = '-o' in args\n"
        "    found = sorted(pathlib.Path('tests').rglob('test_*.py')) + sorted(pathlib.Path('tests').rglob('*_test.py'))\n"
        "    for path in sorted(set(found)):\n"
        "        rel = path.as_posix()\n"
        "        if deselect and rel == deselect and not is_reference:\n"
        "            continue\n"
        "        print(rel + ': 1')\n"
        "    raise SystemExit(0)\n"
        "if args == ['-m', 'pytest', '--version']:\n"
        "    print('pytest 9.0')\n"
        "    raise SystemExit(0)\n"
        "if args == ['-m', 'ruff', 'check', '.']:\n"
        "    print('RUFF_MARKER')\n"
        "    raise SystemExit(0)\n"
        "if len(args) >= 3 and args[:2] == ['-m', 'pytest']:\n"
        "    junit = None\n"
        "    for arg in args:\n"
        "        if arg.startswith('--junitxml='):\n"
        "            junit = arg.split('=', 1)[1]\n"
        "    import shlex as _sh\n"
        "    _env_opts = _sh.split(os.environ.get('PYTEST_ADDOPTS', ''))\n"
        "    _deselected = any(a.endswith('tests/test_report.py') for a in _env_opts)\n"
        "    _count = '0' if _deselected else '1'\n"
        "    if junit:\n"
        "        p = pathlib.Path(junit)\n"
        "        p.parent.mkdir(parents=True, exist_ok=True)\n"
        "        p.write_text('<?xml version=\"1.0\"?><testsuites><testsuite name=\"pytest\" tests=\"' + _count + '\" failures=\"0\" errors=\"0\" skipped=\"0\"><testcase classname=\"m\" name=\"t\"/></testsuite></testsuites>')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    os.chmod(shim, 0o755)
    return root


def run(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.pop("CI_JUNIT_DIR", None)
    merged["PYTHON_BIN"] = str(repo / "fake-python")
    # The shim deselects only when the test asks for it; the repo's own
    # pytest.ini deselect is what the helper must detect from the config.
    merged["PYTEST_SHIM_DESELECT"] = "tests/test_report.py"
    if env:
        merged.update(env)
    return subprocess.run(
        [str(repo / "scripts" / "validate-all.sh"), *args],
        cwd=repo, env=merged, text=True, capture_output=True, check=False, timeout=30,
    )


def test_deselected_suite_fails_before_running(repo: Path, tmp_path: Path) -> None:
    junit_dir = tmp_path / "junit"
    result = run(repo, env={"CI_JUNIT_DIR": str(junit_dir)})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "test selection completeness: root" in result.stdout
    assert "OVERALL STATUS\nFAIL" in result.stdout
    # The narrowed suite never executed: no root JUnit, no EXECUTED_PASS.
    assert not (junit_dir / "root.xml").exists()
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    rows = [
        line.split("\t")
        for line in manifest.splitlines()
        if "test selection completeness: root" in line
    ]
    assert len(rows) == 1
    assert rows[0][1] == "test-completeness-root.json"
    assert rows[0][2] == "yes"
    assert rows[0][3] == "FAIL"
    assert rows[0][4] == "1"
    assert rows[0][5] == "TEST_SELECTION_INCOMPLETE"
    assert "EXECUTED_PASS" not in manifest
    receipt = json.loads(
        (junit_dir / "test-completeness-root.json").read_text(encoding="utf-8")
    )
    assert receipt["schema"] == "agent-os-ci-test-completeness/1"
    assert receipt["verdict"] == "INCOMPLETE"
    assert receipt["missing_files"] == {
        "tests/test_report.py": {"reference": 1, "actual": 0}
    }


def test_complete_selection_passes_and_suite_runs(repo: Path, tmp_path: Path) -> None:
    (repo / "pytest.ini").write_text(
        "[pytest]\naddopts =\n    --continue-on-collection-errors\n",
        encoding="utf-8",
    )
    junit_dir = tmp_path / "junit"
    result = run(repo, env={"CI_JUNIT_DIR": str(junit_dir), "PYTEST_SHIM_DESELECT": ""})
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    rows = [
        line.split("\t")
        for line in manifest.splitlines()
        if "test selection completeness: root" in line
    ]
    assert len(rows) == 1
    assert rows[0][1] == "test-completeness-root.json"
    assert rows[0][2] == "yes"
    assert rows[0][3] == "PASS"
    assert rows[0][5] == "COMPLETE"
    assert any("root" in line and "EXECUTED_PASS" in line for line in manifest.splitlines())
    receipt = json.loads(
        (junit_dir / "test-completeness-root.json").read_text(encoding="utf-8")
    )
    assert receipt["verdict"] == "COMPLETE"


def test_helper_crash_is_collection_error_not_incomplete(repo: Path, tmp_path: Path) -> None:
    """A helper that dies with an exit code the check never returns (3)
    must be classified TEST_COLLECTION_ERROR -- the comparison could
    not be established -- never TEST_SELECTION_INCOMPLETE, and the row
    points at the (absent) receipt."""
    (repo / "scripts" / "agent_os_ci_test_completeness.py").write_text(
        "import sys\nsys.exit(3)\n", encoding="utf-8"
    )
    junit_dir = tmp_path / "junit"
    result = run(repo, env={"CI_JUNIT_DIR": str(junit_dir)})
    assert result.returncode == 1, result.stdout + result.stderr
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    rows = [
        line.split("\t")
        for line in manifest.splitlines()
        if "test selection completeness: root" in line
    ]
    assert len(rows) == 1
    assert rows[0][1] == "test-completeness-root.json"
    assert rows[0][2] == "no"
    assert rows[0][3] == "FAIL"
    assert rows[0][4] == "3"
    assert rows[0][5] == "TEST_COLLECTION_ERROR"
    assert not (junit_dir / "root.xml").exists()


def test_uncaught_helper_exception_exit_one_is_collection_error(
    repo: Path, tmp_path: Path
) -> None:
    """Exit 1 without a fresh receipt is a crash, not proven missing tests."""
    (repo / "scripts" / "agent_os_ci_test_completeness.py").write_text(
        "raise RuntimeError('unhandled collection helper exception')\n",
        encoding="utf-8",
    )
    junit_dir = tmp_path / "junit"
    junit_dir.mkdir()
    (junit_dir / "test-completeness-root.json").write_text(
        '{"schema":"agent-os-ci-test-completeness/1","verdict":"INCOMPLETE"}',
        encoding="utf-8",
    )
    result = run(repo, env={"CI_JUNIT_DIR": str(junit_dir)})
    assert result.returncode == 1, result.stdout + result.stderr
    assert not (junit_dir / "test-completeness-root.json").exists()
    assert not (junit_dir / "root.xml").exists()
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    rows = [
        line.split("\t")
        for line in manifest.splitlines()
        if "test selection completeness: root" in line
    ]
    assert len(rows) == 1
    assert rows[0][2] == "no"
    assert rows[0][4] == "1"
    assert rows[0][5] == "TEST_COLLECTION_ERROR"


def test_success_without_receipt_fails_closed(repo: Path, tmp_path: Path) -> None:
    (repo / "scripts" / "agent_os_ci_test_completeness.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    junit_dir = tmp_path / "junit"
    result = run(repo, env={"CI_JUNIT_DIR": str(junit_dir)})
    assert result.returncode == 1, result.stdout + result.stderr
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    assert "TEST_COLLECTION_ERROR" in manifest
    assert "EXECUTED_PASS" not in manifest
    assert not (junit_dir / "root.xml").exists()


def test_pytest_addopts_env_is_unset_before_suites_run(repo: Path, tmp_path: Path) -> None:
    """PYTEST_ADDOPTS applies to every pytest invocation identically,
    so the runner must unset it before any suite runs: with the env
    var deselecting the regression file and a complete pytest.ini,
    the suite still runs in full (the shim's JUnit reports 1 test,
    the count it writes only when nothing was deselected)."""
    (repo / "pytest.ini").write_text(
        "[pytest]\naddopts =\n    --continue-on-collection-errors\n",
        encoding="utf-8",
    )
    junit_dir = tmp_path / "junit"
    result = run(
        repo,
        env={
            "CI_JUNIT_DIR": str(junit_dir),
            "PYTEST_SHIM_DESELECT": "",
            "PYTEST_ADDOPTS": "--deselect=tests/test_report.py",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'tests="1"' in (junit_dir / "root.xml").read_text(encoding="utf-8")
    receipt = json.loads(
        (junit_dir / "test-completeness-root.json").read_text(encoding="utf-8")
    )
    assert receipt["verdict"] == "COMPLETE"
    assert receipt["actual_count"] == 2
