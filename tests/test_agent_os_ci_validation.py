from __future__ import annotations

import importlib.util
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
import os

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
