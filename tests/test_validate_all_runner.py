from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SOURCE_SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-all.sh"


def _write_test(path: Path, *, failing: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assertion = "assert False" if failing else "assert True"
    path.write_text(f"def test_example():\n    {assertion}\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SOURCE_SCRIPT, root / "scripts" / "validate-all.sh")
    os.chmod(root / "scripts" / "validate-all.sh", 0o755)
    structural = root / "07_Agent_Tests" / "validate-repo-structure.sh"
    structural.parent.mkdir(parents=True)
    structural.write_text(
        '#!/usr/bin/env bash\necho "STRUCTURE_MARKER"\nexit "${STRUCTURE_EXIT:-0}"\n',
        encoding="utf-8",
    )
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
        "if args == ['-m', 'pytest', '--version']:\n"
        "    print('pytest 9.0')\n"
        "    raise SystemExit(0)\n"
        "if len(args) >= 3 and args[:2] == ['-m', 'pytest']:\n"
        "    target = args[2]\n"
        "    print('PYTEST_MARKER ' + target)\n"
        "    print('CWD_MARKER ' + os.getcwd())\n"
        "    print('PYTHONPATH_MARKER ' + os.environ.get('PYTHONPATH', ''))\n"
        "    should_fail = 'fail' in target\n"
        "    if pathlib.Path(target).is_dir():\n"
        "        should_fail = should_fail or any(pathlib.Path(target).rglob('test_*fail.py'))\n"
        "    if should_fail:\n"
        "        raise SystemExit(1)\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(3)\n",
        encoding="utf-8",
    )
    os.chmod(shim, 0o755)
    return root


def run(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["PYTHON_BIN"] = str(repo / "fake-python")
    if env:
        merged.update(env)
    return subprocess.run(
        [str(repo / "scripts" / "validate-all.sh"), *args],
        cwd=repo,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def test_no_argument_behavior_runs_structure_and_root_once(repo: Path) -> None:
    result = run(repo)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.count("STRUCTURE_MARKER") == 1
    assert result.stdout.count("==> root") == 1
    assert "focused:" not in result.stdout
    assert "OVERALL STATUS\nPASS" in result.stdout


def test_one_focused_target_runs_before_structure(repo: Path) -> None:
    result = run(
        repo,
        "--focused",
        "tests/test_root.py",
        "--focused-maxfail",
        "1",
    )
    assert result.returncode == 0
    assert result.stdout.index("==> focused: tests/test_root.py") < result.stdout.index(
        "STRUCTURE_MARKER"
    )
    assert "--maxfail=1" in result.stdout
    assert result.stdout.count("==> root") == 1


def test_multiple_focused_targets_preserve_declared_order(repo: Path) -> None:
    _write_test(repo / "tests" / "test_second.py")
    result = run(
        repo,
        "--focused",
        "tests/test_second.py",
        "--focused",
        "tests/test_root.py",
    )
    assert result.returncode == 0
    assert result.stdout.index("focused: tests/test_second.py") < result.stdout.index(
        "focused: tests/test_root.py"
    )


def test_valid_nested_package_target_uses_package_src(repo: Path) -> None:
    _write_test(repo / "pkg" / "tests" / "test_pkg.py")
    (repo / "pkg" / "src").mkdir(parents=True)
    result = run(repo, "--focused", "pkg/tests/test_pkg.py")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "cd pkg && PYTHONPATH=src" in result.stdout
    assert result.stdout.count("==> pkg") == 1


def test_exact_tests_segment_ignores_tests_prefixed_parent(repo: Path) -> None:
    package_root = repo / "alpha" / "tests_support"
    _write_test(package_root / "tests" / "test_pkg.py")
    (package_root / "src" / "example_package").mkdir(parents=True)

    result = run(
        repo,
        "--focused",
        "alpha/tests_support/tests/test_pkg.py",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "cd alpha/tests_support && PYTHONPATH=src" in result.stdout
    assert f"CWD_MARKER {package_root}" in result.stdout
    assert str(package_root / "src") in result.stdout


@pytest.mark.parametrize(
    "target",
    [
        "alpha/tests_support/tests",
        "alpha/tests_support/tests/unit",
    ],
)
def test_package_tests_directories_use_exact_tests_segment(
    repo: Path, target: str
) -> None:
    package_root = repo / "alpha" / "tests_support"
    _write_test(package_root / "tests" / "unit" / "test_pkg.py")
    (package_root / "src" / "example_package").mkdir(parents=True)

    result = run(repo, "--focused", target)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "cd alpha/tests_support && PYTHONPATH=src" in result.stdout
    assert f"CWD_MARKER {package_root}" in result.stdout
    assert str(package_root / "src") in result.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--focused", ""), "cannot be empty"),
        (("--focused", "missing.py"), "does not exist"),
        (("--focused", "/tmp/test_bad.py"), "repository-relative"),
        (("--focused", "../test_bad.py"), "cannot contain '..'"),
        (("--focused", "-k"), "cannot begin with"),
        (("--focused", "tests/test_root.py;echo"), "unsupported characters"),
        (("--unknown",), "unsupported option"),
        (("positional",), "unexpected positional"),
        (("--focused-maxfail", "1"), "requires at least one"),
        (
            ("--focused", "tests/test_root.py", "--focused-maxfail", "0"),
            "between 1 and 100",
        ),
        (
            ("--focused", "tests/test_root.py", "--focused-maxfail", "-1"),
            "positive integer",
        ),
        (
            ("--focused", "tests/test_root.py", "--focused-maxfail", "101"),
            "between 1 and 100",
        ),
        (
            (
                "--focused",
                "tests/test_root.py",
                "--focused-maxfail",
                "999999999999999999999999",
            ),
            "between 1 and 100",
        ),
        (
            ("--focused", "tests/test_root.py", "--focused-maxfail", "abc"),
            "positive integer",
        ),
    ],
)
def test_invalid_arguments_fail_before_validation(
    repo: Path, args: tuple[str, ...], message: str
) -> None:
    result = run(repo, *args)
    assert result.returncode == 2
    assert message in result.stderr
    assert "STRUCTURE_MARKER" not in result.stdout


@pytest.mark.parametrize("target", [".", "tests", "tests/"])
def test_complete_root_collection_is_rejected_before_execution(
    repo: Path, target: str
) -> None:
    result = run(repo, "--focused", target)
    assert result.returncode == 2
    assert "complete root test suite" in result.stderr
    assert "STRUCTURE_MARKER" not in result.stdout
    assert "PYTEST_MARKER" not in result.stdout


def test_duplicate_focused_target_is_rejected(repo: Path) -> None:
    result = run(
        repo,
        "--focused",
        "tests/test_root.py",
        "--focused",
        "tests/./test_root.py",
    )
    assert result.returncode == 2
    assert "duplicate focused target" in result.stderr


def test_symlink_escape_is_rejected(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _write_test(outside / "test_escape.py")
    (repo / "tests" / "escape.py").symlink_to(outside / "test_escape.py")
    result = run(repo, "--focused", "tests/escape.py")
    assert result.returncode == 2
    assert "escapes the repository" in result.stderr


def test_directory_with_symlinked_descendant_is_rejected_before_execution(
    repo: Path, tmp_path: Path
) -> None:
    focused = repo / "tests" / "focused"
    _write_test(focused / "test_safe.py")
    outside = tmp_path / "outside"
    _write_test(outside / "test_escape.py")
    (focused / "test_escape.py").symlink_to(outside / "test_escape.py")

    result = run(repo, "--focused", "tests/focused")

    assert result.returncode == 2
    assert "symlink or repository-escaping test path" in result.stderr
    assert "STRUCTURE_MARKER" not in result.stdout
    assert "PYTEST_MARKER" not in result.stdout


def test_directory_with_symlinked_subdirectory_is_rejected_before_execution(
    repo: Path, tmp_path: Path
) -> None:
    focused = repo / "tests" / "focused"
    _write_test(focused / "test_safe.py")
    outside = tmp_path / "outside"
    _write_test(outside / "test_escape.py")
    (focused / "linked").symlink_to(outside, target_is_directory=True)

    result = run(repo, "--focused", "tests/focused")

    assert result.returncode == 2
    assert "symlink or repository-escaping test path" in result.stderr
    assert "STRUCTURE_MARKER" not in result.stdout
    assert "PYTEST_MARKER" not in result.stdout


def test_non_test_python_file_is_rejected(repo: Path) -> None:
    path = repo / "tests" / "helper.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    result = run(repo, "--focused", "tests/helper.py")
    assert result.returncode == 2
    assert "not a pytest test module" in result.stderr


def test_empty_directory_is_rejected(repo: Path) -> None:
    (repo / "tests" / "empty").mkdir()
    result = run(repo, "--focused", "tests/empty")
    assert result.returncode == 2
    assert "contains no pytest test modules" in result.stderr


def test_focused_failure_is_recorded_and_aggregate_continues(repo: Path) -> None:
    _write_test(repo / "tests" / "test_focused_fail.py", failing=True)
    result = run(
        repo,
        "--focused",
        "tests/test_focused_fail.py",
        "--focused-maxfail",
        "1",
    )
    assert result.returncode == 1
    assert "FAIL|focused" not in result.stdout
    assert "FAIL | focused: tests/test_focused_fail.py" in result.stdout
    assert "STRUCTURE_MARKER" in result.stdout
    assert "==> root" in result.stdout
    assert "OVERALL STATUS\nFAIL" in result.stdout


def test_structural_failure_is_recorded_and_aggregate_continues(repo: Path) -> None:
    result = run(repo, env={"STRUCTURE_EXIT": "7"})
    assert result.returncode == 1
    assert "FAIL | structural validation | exit 7" in result.stdout
    assert "==> root" in result.stdout


def test_multiple_failures_remain_visible(repo: Path) -> None:
    _write_test(repo / "tests" / "test_focused_fail.py", failing=True)
    result = run(
        repo,
        "--focused",
        "tests/test_focused_fail.py",
        env={"STRUCTURE_EXIT": "9"},
    )
    assert result.returncode == 1
    assert "focused: tests/test_focused_fail.py" in result.stdout
    assert "structural validation" in result.stdout
    assert result.stdout.count("FAIL |") >= 3


def test_script_contains_no_eval_or_shell_string_execution() -> None:
    content = SOURCE_SCRIPT.read_text(encoding="utf-8")
    assert "eval " not in content
    assert "bash -c" not in content
    assert "sh -c" not in content
    assert 'command=("$PYTHON_BIN" -m pytest' in content


def test_governed_lanes_keep_one_canonical_runner_invocation() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/agent-os-validation.yml").read_text(
        encoding="utf-8"
    )
    cloud_build = (root / "cloudbuild.yaml").read_text(encoding="utf-8")
    for content in (workflow, cloud_build):
        assert content.count("./scripts/validate-all.sh") == 1
        assert "bash 07_Agent_Tests/validate-repo-structure.sh" not in content


def test_pr_template_names_focused_and_aggregate_evidence_without_duplication() -> None:
    root = Path(__file__).parents[1]
    template = (root / ".github/PULL_REQUEST_TEMPLATE.md").read_text(
        encoding="utf-8"
    )
    assert "--focused" in template
    assert "synthetic-merge SHA" in template
    assert "bash 07_Agent_Tests/validate-repo-structure.sh" not in template
    assert template.count("./scripts/validate-all.sh") == 1
