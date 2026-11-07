from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SOURCE_SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-all.sh"
HELPER_SCRIPT = Path(__file__).parents[1] / "scripts" / "agent_os_ci_test_completeness.py"


def _write_test(path: Path, *, failing: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assertion = "assert False" if failing else "assert True"
    path.write_text(f"def test_example():\n    {assertion}\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SOURCE_SCRIPT, root / "scripts" / "validate-all.sh")
    shutil.copy2(HELPER_SCRIPT, root / "scripts" / "agent_os_ci_test_completeness.py")
    os.chmod(root / "scripts" / "validate-all.sh", 0o755)
    structural = root / "07_Agent_Tests" / "validate-repo-structure.sh"
    structural.parent.mkdir(parents=True)
    structural.write_text('#!/usr/bin/env bash\necho "STRUCTURE_MARKER"\nexit 0\n', encoding="utf-8")
    os.chmod(structural, 0o755)
    _write_test(root / "tests" / "test_root.py")
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
        "    target = args[2]\n"
        "    cwd_name = pathlib.Path.cwd().name\n"
        "    # 'setupfail'/'fail' in the suite cwd simulates a pytest invocation\n"
        "    # that never produces XML, or a failing suite that retains XML.\n"
        "    if 'setupfail' in cwd_name:\n"
        "        raise SystemExit(2)\n"
        "    if 'fail' in cwd_name:\n"
        "        failed = 1\n"
        "    if junit:\n"
        "        p = pathlib.Path(junit)\n"
        "        p.parent.mkdir(parents=True, exist_ok=True)\n"
        "        failed = 1 if 'fail' in cwd_name else 0\n"
        "        p.write_text(f'<?xml version=\"1.0\"?><testsuites><testsuite name=\"pytest\" tests=\"1\" failures=\"{failed}\" errors=\"0\" skipped=\"0\"><testcase classname=\"m\" name=\"t\"/></testsuite></testsuites>')\n"
        "    if 'fail' in cwd_name:\n"
        "        raise SystemExit(1)\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    os.chmod(shim, 0o755)
    return root


def run(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    # This harness models local defaults unless a test explicitly requests CI JUnit.
    merged.pop("CI_JUNIT_DIR", None)
    merged["PYTHON_BIN"] = str(repo / "fake-python")
    if env:
        merged.update(env)
    return subprocess.run(
        [str(repo / "scripts" / "validate-all.sh"), *args],
        cwd=repo, env=merged, text=True, capture_output=True, check=False, timeout=30,
    )


def test_default_local_run_has_no_junit_or_manifest(repo: Path, tmp_path: Path) -> None:
    junit_dir = tmp_path / "junit"
    result = run(repo)
    assert result.returncode == 0
    assert "--junitxml=" not in result.stdout
    assert not junit_dir.exists()


def test_ci_junit_dir_produces_unique_xml_and_manifest(repo: Path, tmp_path: Path) -> None:
    _write_test(repo / "pkg-a" / "tests" / "test_a.py")
    _write_test(repo / "pkg-b" / "tests" / "test_b.py")
    junit_dir = tmp_path / "junit"
    result = run(repo, env={"CI_JUNIT_DIR": str(junit_dir), "VALIDATE_ALL_MAX_PARALLEL": "2"})
    assert result.returncode == 0, result.stderr + result.stdout
    xml_files = sorted(p.name for p in junit_dir.glob("*.xml"))
    assert len(xml_files) == len(set(xml_files)) == 3  # pkg-a, pkg-b, root
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    assert "EXECUTED_PASS" in manifest
    assert "root" in manifest and "pkg-a" in manifest and "pkg-b" in manifest
    assert "Ruff" not in manifest and "structural" not in manifest


def test_failing_suite_retains_xml_and_manifest_marks_executed_fail(repo: Path, tmp_path: Path) -> None:
    _write_test(repo / "pkg-fail" / "tests" / "test_fail.py", failing=True)
    junit_dir = tmp_path / "junit"
    result = run(repo, env={"CI_JUNIT_DIR": str(junit_dir)})
    assert result.returncode == 1
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    assert "EXECUTED_FAIL" in manifest
    assert any("pkg-fail" in line and "EXECUTED_FAIL" in line for line in manifest.splitlines())


def test_setup_failure_produces_no_xml_and_is_not_a_green_suite(repo: Path, tmp_path: Path) -> None:
    _write_test(repo / "pkg-setupfail" / "tests" / "test_setupfail.py")
    junit_dir = tmp_path / "junit"
    result = run(repo, env={"CI_JUNIT_DIR": str(junit_dir)})
    assert result.returncode == 1
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    assert any("pkg-setupfail" in line and "NOT_EXECUTED_SETUP_FAILURE" in line for line in manifest.splitlines())
    assert not list(junit_dir.glob("*setupfail*.xml"))


def test_focused_target_gets_unique_junit(repo: Path, tmp_path: Path) -> None:
    junit_dir = tmp_path / "junit"
    result = run(repo, "--focused", "tests/test_root.py", env={"CI_JUNIT_DIR": str(junit_dir)})
    assert result.returncode == 0, result.stderr + result.stdout
    assert "focused__tests__test_root.py.xml" in [p.name for p in junit_dir.glob("*.xml")]
    manifest = (junit_dir / "manifest.tsv").read_text(encoding="utf-8")
    assert "focused: tests/test_root.py" in manifest
