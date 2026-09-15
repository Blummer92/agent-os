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
