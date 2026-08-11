"""Offline acceptance tests for the pure runtime-configuration seam (#1032)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
TESTS_DIR = Path(__file__).resolve().parent
for path in (REPOSITORY_ROOT, SCHEDULER_SRC, TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import test_single_issue_pilot as tsp  # noqa: E402

from workflow_scheduler.execution.concrete_runtime_adapters import (  # noqa: E402
    ConcreteRuntimeConfiguration as LegacyConfiguration,
    ConcreteRuntimeConfigurationError as LegacyConfigurationError,
)
from workflow_scheduler.execution.frozen_test_validation_adapter import (  # noqa: E402
    FrozenTestCommand,
)
from workflow_scheduler.execution.runtime_configuration import (  # noqa: E402
    ConcreteRuntimeConfiguration,
    ConcreteRuntimeConfigurationError,
    runtime_configuration_payload,
)

PURE_MODULE = (
    SCHEDULER_SRC
    / "workflow_scheduler"
    / "execution"
    / "runtime_configuration.py"
)


def _commands() -> tuple[FrozenTestCommand, ...]:
    return tuple(
        FrozenTestCommand(test_id=test_id, argv=(sys.executable, "-c", "pass"))
        for test_id in tsp.REQUIRED_TESTS
    )


def test_legacy_import_path_reexports_the_exact_pure_types() -> None:
    assert LegacyConfiguration is ConcreteRuntimeConfiguration
    assert LegacyConfigurationError is ConcreteRuntimeConfigurationError


def test_pure_configuration_binding_is_deterministic_and_side_effect_free(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    parent = tmp_path / "worktrees"
    root.mkdir()
    parent.mkdir()
    pilot_input = tsp._pilot_input()
    first = ConcreteRuntimeConfiguration.bind(
        pilot_input,
        repository_identity=tsp._identity(),
        repository_root=str(root),
        workspace_parent=str(parent),
        executor_argv=(sys.executable, "-c", "pass"),
        required_test_commands=_commands(),
        executor_timeout_seconds=1.0,
        executor_grace_period_seconds=0.05,
        validation_per_command_timeout_seconds=1.0,
        validation_total_timeout_seconds=5.0,
    )
    second = ConcreteRuntimeConfiguration.bind(
        pilot_input,
        repository_identity=tsp._identity(),
        repository_root=str(root),
        workspace_parent=str(parent),
        executor_argv=(sys.executable, "-c", "pass"),
        required_test_commands=_commands(),
        executor_timeout_seconds=1.0,
        executor_grace_period_seconds=0.05,
        validation_per_command_timeout_seconds=1.0,
        validation_total_timeout_seconds=5.0,
    )
    assert first == second
    assert first.configuration_fingerprint == second.configuration_fingerprint
    assert runtime_configuration_payload(first) == runtime_configuration_payload(second)
    first.verify(pilot_input)


def test_pure_module_has_no_execution_capable_imports() -> None:
    tree = ast.parse(PURE_MODULE.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    forbidden = {
        "subprocess",
        "workflow_scheduler.execution.concrete_runtime_adapters",
        "workflow_scheduler.execution.git_worktree_adapter",
        "workflow_scheduler.execution.in_memory_lease_adapter",
        "workflow_scheduler.execution.posix_process_adapter",
        "workflow_scheduler.execution.single_issue_runtime",
    }
    assert imports.isdisjoint(forbidden)


def test_pure_module_exposes_no_runtime_entrypoint_or_adapter_builder() -> None:
    source = PURE_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert "build_concrete_runtime_adapters" not in definitions
    assert "run_concrete_runtime_entrypoint" not in definitions
    assert "run_concrete_runtime_entrypoint_with_validation_evidence" not in definitions
