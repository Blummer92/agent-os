"""validate-all.sh: pytest exit 5 is ZERO_COLLECTED, not a pass.

Standalone fixture (same shim pattern as test_validate_all_junit.py, plus a
'zero' suite whose pytest invocation exits 5 with a tests=0 JUnit file).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE_SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-all.sh"


def _write_test(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_example():\n    assert True\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SOURCE_SCRIPT, root / "scripts" / "validate-all.sh")
    os.chmod(root / "scripts" / "validate-all.sh", 0o755)
    structural = root / "07_Agent_Tests" / "validate-repo-structure.sh"
    structural.parent.mkdir(parents=True)
    structural.write_text('#!/usr/bin/env bash\necho "STRUCTURE_MARKER"\nexit 0\n', encoding="utf-8")
    os.chmod(structural, 0o755)
    _write_test(root / "tests" / "test_root.py")
    _write_test(root / "pkg-zero" / "tests" / "test_zero.py")
    shim = root / "fake-python"
    shim.write_text(
        "#!" + sys._base_executable + "\n"
        "import os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
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
        "    if 'zero' in pathlib.Path.cwd().name:\n"
        "        if junit:\n"
        "            p = pathlib.Path(junit)\n"
        "            p.parent.mkdir(parents=True, exist_ok=True)\n"
        "            p.write_text('<?xml version=\"1.0\"?><testsuites><testsuite name=\"pytest\" tests=\"0\" failures=\"0\" errors=\"0\" skipped=\"0\"></testsuite></testsuites>')\n"
        "        raise SystemExit(5)\n"
        "    if junit:\n"
        "        p = pathlib.Path(junit)\n"
        "        p.parent.mkdir(parents=True, exist_ok=True)\n"
        "        p.write_text('<?xml version=\"1.0\"?><testsuites><testsuite name=\"pytest\" tests=\"1\" failures=\"0\" errors=\"0\" skipped=\"0\"><testcase classname=\"m\" name=\"t\"/></testsuite></testsuites>')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    os.chmod(shim, 0o755)
    return root


def test_zero_collected_suite_is_not_green(repo: Path, tmp_path: Path) -> None:
    junit_dir = tmp_path / "junit"
    env = os.environ.copy()
    env["PYTHON_BIN"] = str(repo / "fake-python")
    env["CI_JUNIT_DIR"] = str(junit_dir)
    result = subprocess.run([str(repo / "scripts" / "validate-all.sh")], cwd=repo, env=env, text=True, capture_output=True, check=False, timeout=30)
    assert result.returncode != 0
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    assert any("pkg-zero" in line and "ZERO_COLLECTED" in line for line in manifest.splitlines())
    assert any("root" in line and "EXECUTED_PASS" in line for line in manifest.splitlines())
