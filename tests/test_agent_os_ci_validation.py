from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/agent_os_ci_validation.py"

spec = importlib.util.spec_from_file_location("agent_os_ci_validation", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_bounded_executor_resolves_registered_python_command_without_shell():
    argv, cwd = module._resolve_command("python -m pytest tests/agent_os_issue_acceptance")
    assert argv == ("python", "-m", "pytest", "tests/agent_os_issue_acceptance")
    assert cwd == ROOT


def test_bounded_executor_resolves_picture_perfect_focused_command_to_fixed_argv_and_cwd():
    command = (
        "cd 08_Tooling/instructional-materials-coach/picture-perfect-coach && npm test -- "
        "src/overlayIntegrity.test.ts src/exactComposite.test.ts "
        "src/exactCompositeSuite.test.ts src/framePlan.test.ts "
        "src/executorContract.test.ts src/provenanceValidator.test.ts"
    )
    argv, cwd = module._resolve_command(command)
    assert argv == (
        "npm",
        "test",
        "--",
        "src/overlayIntegrity.test.ts",
        "src/exactComposite.test.ts",
        "src/exactCompositeSuite.test.ts",
        "src/framePlan.test.ts",
        "src/executorContract.test.ts",
        "src/provenanceValidator.test.ts",
    )
    assert cwd == ROOT / "08_Tooling/instructional-materials-coach/picture-perfect-coach"


def test_bounded_executor_resolves_capture_commands_to_exact_npm_argv_and_cwd():
    expected = {
        "cd 08_Tooling/instructional-materials-coach/capture && npm ci": ("npm", "ci"),
        "cd 08_Tooling/instructional-materials-coach/capture && npm test": ("npm", "test"),
        "cd 08_Tooling/instructional-materials-coach/capture && npm run check": (
            "npm",
            "run",
            "check",
        ),
    }
    for command, argv in expected.items():
        resolved, cwd = module._resolve_command(command)
        assert resolved == argv
        assert cwd == ROOT / "08_Tooling/instructional-materials-coach/capture"


def test_bounded_executor_resolves_ui_cross_platform_reference_commands_to_exact_npm_argv_and_cwd():
    expected = {
        "cd 05_Examples/ui-cross-platform-reference && npm install": ("npm", "install"),
        "cd 05_Examples/ui-cross-platform-reference && npm test": ("npm", "test"),
    }
    for command, argv in expected.items():
        resolved, cwd = module._resolve_command(command)
        assert resolved == argv
        assert cwd == ROOT / "05_Examples/ui-cross-platform-reference"


def test_bounded_executor_does_not_admit_unregistered_ui_cross_platform_npm_commands():
    for command in (
        "cd 05_Examples/ui-cross-platform-reference && npm ci",
        "cd 05_Examples/ui-cross-platform-reference && npm exec sh",
        "cd 05_Examples/ui-cross-platform-reference && npm run arbitrary",
    ):
        with pytest.raises(ValueError, match="not in the bounded CI executor"):
            module._resolve_command(command)


def test_bounded_executor_resolves_its_exact_self_test_without_generic_pytest_expansion():
    argv, cwd = module._resolve_command("python -m pytest tests/test_agent_os_ci_validation.py")
    assert argv == ("python", "-m", "pytest", "tests/test_agent_os_ci_validation.py")
    assert cwd == ROOT


def test_bounded_executor_does_not_admit_unregistered_capture_npm_commands():
    for command in (
        "cd 08_Tooling/instructional-materials-coach/capture && npm install",
        "cd 08_Tooling/instructional-materials-coach/capture && npm exec sh",
        "cd 08_Tooling/instructional-materials-coach/capture && npm run arbitrary",
    ):
        with pytest.raises(ValueError, match="not in the bounded CI executor"):
            module._resolve_command(command)


def test_bounded_executor_does_not_admit_full_picture_perfect_package_check():
    with pytest.raises(ValueError, match="not in the bounded CI executor"):
        module._resolve_command(
            "cd 08_Tooling/instructional-materials-coach/picture-perfect-coach && npm run check"
        )


def test_bounded_executor_fails_closed_on_unregistered_command():
    with pytest.raises(ValueError, match="not in the bounded CI executor"):
        module._resolve_command("python -c 'print(\"branch controlled\")'")


def test_teacher_os_fixed_command_allowlist_and_working_directory():
    expected = {
        "npm ci": ("npm", "ci"),
        "npm run build": ("npm", "run", "build"),
        "npm run test:unit": ("npm", "run", "test:unit"),
        "npx playwright install chromium": ("npx", "playwright", "install", "chromium"),
        "npx playwright test": ("npx", "playwright", "test"),
    }
    for command, argv in expected.items():
        resolved, cwd = module._resolve_command(
            "cd 08_Tooling/teacher-os-web && " + command
        )
        assert resolved == argv
        assert cwd == ROOT / "08_Tooling/teacher-os-web"


@pytest.mark.parametrize("suffix", [
    "npm test -- --run", "npm run arbitrary", "npm exec sh",
    "npx playwright test --grep skip", "npm ci && echo bypass",
])
def test_teacher_os_rejects_unregistered_commands(suffix):
    with pytest.raises(ValueError, match="not in the bounded CI executor"):
        module._resolve_command("cd 08_Tooling/teacher-os-web && " + suffix)


# --- D07 Track A: the 10 newly mapped Python suites (G2/G3) -------------------
# The focused command string keeps the existing root-relative form
# (``python -m pytest 08_Tooling/<dir>/tests``), but the bounded executor runs
# it exactly the way ``scripts/validate-all.sh`` runs the suite: with the
# suite directory as the working directory and ``tests`` as the target, so
# each suite's own pytest configuration and ``PYTHONPATH=src`` layout apply.
# A plain root-relative run cannot import five of the ten packages
# (notion-operational-guidance-writer, visual-asset-drive-writer,
# visual-asset-ingestion-coordinator, visual-asset-notion-writer,
# visual-asset-routing), which is why resolution is suite-local, not a
# registry-only lookup from ROOT.

_D07_PYTHON_SUITES = (
    "agent-memory-context-manager",
    "dashboard-migration-verification",
    "notion-compute-decision-writer",
    "notion-operational-guidance-writer",
    "reusable-capability-registry",
    "visual-asset-drive-writer",
    "visual-asset-ingestion-coordinator",
    "visual-asset-intake",
    "visual-asset-notion-writer",
    "visual-asset-routing",
)


@pytest.mark.parametrize("directory", _D07_PYTHON_SUITES)
def test_d07_executor_resolves_new_python_suite_to_suite_directory(directory):
    command = f"python -m pytest 08_Tooling/{directory}/tests"
    argv, cwd = module._resolve_command(command)
    assert argv == ("python", "-m", "pytest", "tests")
    assert cwd == ROOT / "08_Tooling" / directory


@pytest.mark.parametrize("directory", _D07_PYTHON_SUITES)
def test_d07_executor_supplies_suite_src_on_pythonpath(directory, monkeypatch):
    command = f"python -m pytest 08_Tooling/{directory}/tests"
    _, cwd = module._resolve_command(command)
    monkeypatch.setenv("PYTHONPATH", "/existing-entry")
    env = module._command_env(cwd)
    suite_src = str(cwd / "src")
    if (cwd / "src").is_dir():
        assert env["PYTHONPATH"] == suite_src + os.pathsep + "/existing-entry"
    else:
        # dashboard-migration-verification has no src/ layout; validate-all.sh
        # runs it without PYTHONPATH, and the executor must match exactly.
        assert env["PYTHONPATH"] == "/existing-entry"


def test_d07_executor_root_cwd_still_gets_repository_src_on_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/existing-entry")
    env = module._command_env(ROOT)
    assert env["PYTHONPATH"] == str(ROOT / "src") + os.pathsep + "/existing-entry"


@pytest.mark.parametrize(
    "command",
    [
        # Single-file variants are not registered suite commands.
        "python -m pytest 08_Tooling/visual-asset-routing/tests/test_routing.py",
        "python -m pytest 08_Tooling/agent-memory-context-manager/tests/test_lesson_retrieval_orchestrator.py",
        # Trailing-slash and extra-flag variants are not registered either.
        "python -m pytest 08_Tooling/visual-asset-routing/tests/",
        "python -m pytest 08_Tooling/visual-asset-routing/tests -q",
        # A directory outside the mapped ten is not admitted by analogy.
        "python -m pytest 08_Tooling/workspace-automation-builder/tests",
    ],
)
def test_d07_executor_rejects_unregistered_python_suite_variants(command):
    with pytest.raises(ValueError, match="not in the bounded CI executor"):
        module._resolve_command(command)


def _run_focused_fixture(monkeypatch, commands, run_child):
    head = "b" * 40
    monkeypatch.setattr(module, "_current_head", lambda: head)
    monkeypatch.setattr(module.subprocess, "run", run_child)
    plan = module.ValidationPlan(
        selector_version="1.0.0",
        repository="Blummer92/agent-os",
        pull_request=4031,
        head_sha=head,
        base_sha="a" * 40,
        profile="focused",
        commands=commands,
        reason_codes=("profile.focused-package",),
        command_set_digest="1" * 64,
        remote_build_required=True,
    )
    module.execute_focused(plan, expected_head_sha=head)


def _junit_arg(argv):
    return Path(next(item.partition("=")[2] for item in argv if item.startswith("--junitxml=")))


def _junit_xml(tests, cases, *, skipped=0, failures=0):
    return (
        f'<testsuite tests="{tests}" skipped="{skipped}" failures="{failures}" errors="0">'
        + cases + "</testsuite>"
    )


_CASE_PASS = '<testcase name="tested"/>'
_CASE_SKIP = '<testcase name="skipped"><skipped/></testcase>'
_CASE_FAIL = '<testcase name="failed"><failure/></testcase>'


@pytest.mark.parametrize(
    "report,expected",
    [
        (None, "without fresh, valid, count-consistent JUnit"),
        ("<broken", "without fresh, valid, count-consistent JUnit"),
        (_junit_xml(2, _CASE_PASS), "without fresh, valid, count-consistent JUnit"),
        (_junit_xml(0, ""), "without executing a passing test"),
        (_junit_xml(1, _CASE_SKIP, skipped=1), "without executing a passing test"),
        (_junit_xml(1, _CASE_FAIL, failures=1), "JUnit reports failures or errors"),
    ],
)
def test_d07_successful_child_requires_fresh_positive_case_evidence(tmp_path, monkeypatch, report, expected):
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    command = "python -m pytest tests/test_agent_os_ci_validation.py"
    def child(argv, **kwargs):
        report_path = _junit_arg(argv)
        assert not report_path.exists()
        if report is not None:
            report_path.write_text(report, encoding="utf-8")

    with pytest.raises(ValueError, match=expected):
        _run_focused_fixture(monkeypatch, (command,), child)
    record = json.loads((tmp_path / "manifest.json").read_text())["commands"][0]
    assert record["exit_code"] == 0
    assert record["classification"] == "NOT_EXECUTED_SETUP_FAILURE"
    assert expected in record["error"]


def test_d07_focused_does_not_reuse_stale_passing_junit(tmp_path, monkeypatch):
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    command = "python -m pytest tests/test_agent_os_ci_validation.py"
    stale = module._junit_path_for_command(command, tmp_path, 0)
    stale.write_text(_junit_xml(1, _CASE_PASS), encoding="utf-8")

    def child(argv, **kwargs):
        assert _junit_arg(argv) == stale

    with pytest.raises(ValueError, match="without fresh, valid, count-consistent JUnit"):
        _run_focused_fixture(monkeypatch, (command,), child)
    assert not stale.exists()


def test_d07_focused_python_applies_execution_guards_and_preserves_partial_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    monkeypatch.setenv("PYTEST_ADDOPTS", "--setup-plan")
    command = "python -m pytest 08_Tooling/agent-memory-context-manager/tests"

    def child(argv, *, cwd, env, check):
        assert check is True
        assert cwd == ROOT / "08_Tooling/agent-memory-context-manager"
        assert argv[:4] == ("python", "-m", "pytest", "tests")
        assert argv[-4:] == ("-p", "no:setuponly", "-p", "no:setupplan")
        assert "PYTEST_ADDOPTS" not in env
        _junit_arg(argv).write_text(_junit_xml(2, _CASE_SKIP + _CASE_PASS, skipped=1), encoding="utf-8")

    _run_focused_fixture(monkeypatch, (command,), child)
    assert os.environ["PYTEST_ADDOPTS"] == "--setup-plan"
    record = json.loads((tmp_path / "manifest.json").read_text())["commands"][0]
    assert record["classification"] == "EXECUTED_PASS"
    assert record["junit_counts"] == {"tests": 2, "skipped": 1, "failures": 0, "errors": 0}
    assert record["error"] is None


def test_d07_focused_python_requires_evidence_even_without_published_receipt(monkeypatch):
    monkeypatch.delenv("CI_JUNIT_DIR", raising=False)
    paths = []

    def child(argv, **kwargs):
        paths.append(_junit_arg(argv))

    with pytest.raises(ValueError, match="without fresh, valid, count-consistent JUnit"):
        _run_focused_fixture(monkeypatch, ("python -m pytest tests/test_agent_os_ci_validation.py",), child)
    assert len(paths) == 1 and not paths[0].parent.exists()


@pytest.mark.parametrize("exit_code,classification", [(1, "EXECUTED_FAIL"), (5, "ZERO_COLLECTED")])
def test_d07_focused_preserves_first_real_failure_and_runs_later_commands(tmp_path, monkeypatch, exit_code, classification):
    monkeypatch.setenv("CI_JUNIT_DIR", str(tmp_path))
    commands = (
        "python -m pytest tests/test_agent_os_ci_validation.py",
        "python -m pytest tests/agent_os_issue_acceptance",
    )
    calls = []

    def child(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(exit_code, argv)
        _junit_arg(argv).write_text(_junit_xml(1, _CASE_PASS), encoding="utf-8")

    with pytest.raises(subprocess.CalledProcessError) as raised:
        _run_focused_fixture(monkeypatch, commands, child)
    assert raised.value.returncode == exit_code
    records = json.loads((tmp_path / "manifest.json").read_text())["commands"]
    assert len(calls) == 2
    assert [record["classification"] for record in records] == [classification, "EXECUTED_PASS"]


def test_focused_executor_resolves_receipt_and_junit_regression_commands():
    for suffix in ("junit", "receipt"):
        target = f"tests/test_agent_os_ci_validation_{suffix}.py"
        assert module._resolve_command(f"python -m pytest {target}") == (
            ("python", "-m", "pytest", target),
            ROOT,
        )
