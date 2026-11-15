"""validate-all.sh: suite discovery skips numbered virtual environments.

Standalone fixture (same shim pattern as test_validate_all_zero_collected.py).
`.venv-1`/`.venv-2` style environments must not be selected as pytest suites,
while legitimate suites still run and still fail the aggregate run on a failing
test or a collection error.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE_SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-all.sh"
RUNNER_HELPERS = ("agent_os_ci_test_completeness.py", "agent_os_ci_junit_diff.py")
VENV_SUITES = (".venv-1/lib/site-packages/pkg", ".venv-2/lib/site-packages/pkg")
JUNIT_PASS = (
    '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1" failures="0" '
    'errors="0" skipped="0"><testcase classname="m" name="t"/></testsuite></testsuites>'
)
JUNIT_FAIL = (
    '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1" failures="1" '
    'errors="0" skipped="0"><testcase classname="m" name="t"><failure message="x"/></testcase>'
    "</testsuite></testsuites>"
)


def _write_test(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_example():\n    assert True\n", encoding="utf-8")


def _make_repo(tmp_path: Path, extra_suites: tuple[str, ...] = ()) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SOURCE_SCRIPT, root / "scripts" / "validate-all.sh")
    for helper in RUNNER_HELPERS:
        shutil.copy2(SOURCE_SCRIPT.parent / helper, root / "scripts" / helper)
    os.chmod(root / "scripts" / "validate-all.sh", 0o755)
    structural = root / "07_Agent_Tests" / "validate-repo-structure.sh"
    structural.parent.mkdir(parents=True)
    structural.write_text('#!/usr/bin/env bash\nexit 0\n', encoding="utf-8")
    os.chmod(structural, 0o755)
    for suite in ("", "pkg-good/", *extra_suites):
        _write_test(root / suite / "tests" / "test_x.py")
    for suite in VENV_SUITES:
        _write_test(root / suite / "tests" / "test_x.py")
    shim = root / "fake-python"
    shim.write_text(
        "#!" + sys._base_executable + "\n"
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if args and args[0].endswith('.py') and pathlib.Path(args[0]).is_file():\n"
        "    import runpy\n"
        "    sys.path.insert(0, str(pathlib.Path(args[0]).resolve().parent))\n"
        "    sys.argv = args\n"
        "    runpy.run_path(args[0], run_name='__main__')\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['-m', 'pytest'] and '--collect-only' in args:\n"
        "    cwd = pathlib.Path.cwd().name\n"
        "    if 'collecterr' in cwd:\n"
        "        print('ERROR collecting', file=sys.stderr)\n"
        "        raise SystemExit(2)\n"
        "    print('m.py::t')\n"
        "    raise SystemExit(0)\n"
        "if args == ['-m', 'pytest', '--version']:\n"
        "    print('pytest 9.0')\n"
        "    raise SystemExit(0)\n"
        "if args == ['-m', 'ruff', 'check', '.']:\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['-m', 'pytest']:\n"
        "    junit = next((a.split('=', 1)[1] for a in args if a.startswith('--junitxml=')), None)\n"
        "    failing = 'failing' in pathlib.Path.cwd().name\n"
        "    if junit:\n"
        "        p = pathlib.Path(junit)\n"
        "        p.parent.mkdir(parents=True, exist_ok=True)\n"
        f"        p.write_text({JUNIT_FAIL!r} if failing else {JUNIT_PASS!r})\n"
        "    raise SystemExit(1 if failing else 0)\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    os.chmod(shim, 0o755)
    return root


def _run(root: Path, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    junit_dir = tmp_path / "junit"
    env = os.environ.copy()
    env["PYTHON_BIN"] = str(root / "fake-python")
    env["CI_JUNIT_DIR"] = str(junit_dir)
    result = subprocess.run(
        [str(root / "scripts" / "validate-all.sh")], cwd=root, env=env, text=True,
        capture_output=True, check=False, timeout=60,
    )
    manifest = junit_dir / "manifest.tsv"
    lines = manifest.read_text(encoding="utf-8").splitlines() if manifest.exists() else []
    return result, lines


def test_numbered_venvs_are_not_selected_but_project_suites_are(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    result, lines = _run(root, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = "\n".join(lines)
    assert ".venv-1" not in manifest and ".venv-2" not in manifest
    assert any(line.startswith("root\t") for line in lines)
    assert any(line.startswith("pkg-good\t") for line in lines)


def test_failing_project_suite_still_fails_aggregate(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, extra_suites=("pkg-failing/",))
    result, lines = _run(root, tmp_path)
    assert result.returncode != 0
    assert not any(".venv-" in line for line in lines)
    assert any(line.startswith("pkg-failing\t") and "FAIL" in line for line in lines)


def test_collection_error_is_not_success(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, extra_suites=("pkg-collecterr/",))
    result, lines = _run(root, tmp_path)
    assert result.returncode != 0
    assert not any(".venv-" in line for line in lines)
    assert any(
        "pkg-collecterr" in line and line.split("\t")[3] == "FAIL" and line.endswith("TEST_COLLECTION_ERROR")
        for line in lines
    )
