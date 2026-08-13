"""Offline acceptance tests for the pure runtime-configuration seam (#1032)."""

from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
TESTS_DIR = Path(__file__).resolve().parent
for path in (REPOSITORY_ROOT, SCHEDULER_SRC, TESTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import test_single_issue_pilot as tsp  # noqa: E402

from scripts.agent_os_execution_capabilities.models import (  # noqa: E402
    RepositoryIdentity,
)
from workflow_scheduler.execution import runtime_configuration as rc  # noqa: E402
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
    reconstruct_concrete_runtime_configuration,
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


def _bound_configuration(tmp_path: Path) -> ConcreteRuntimeConfiguration:
    root = tmp_path / "repository"
    parent = tmp_path / "worktrees"
    root.mkdir()
    parent.mkdir()
    return ConcreteRuntimeConfiguration.bind(
        tsp._pilot_input(),
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
    """Traverse the first-party import closure, not only direct imports."""
    source_root = SCHEDULER_SRC.resolve()
    modules: dict[str, Path] = {}
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root).with_suffix("")
        parts = relative.parts
        module = ".".join(parts[:-1]) if parts[-1] == "__init__" else ".".join(parts)
        modules[module] = path

    forbidden = {
        "subprocess",
        "workflow_scheduler.execution.concrete_runtime_adapters",
        "workflow_scheduler.execution.git_worktree_adapter",
        "workflow_scheduler.execution.in_memory_lease_adapter",
        "workflow_scheduler.execution.posix_process_adapter",
        "workflow_scheduler.execution.single_issue_runtime",
    }

    def imported_names(module: str, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        package = module.split(".")[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_module = ""
                if node.level:
                    keep = len(package) - node.level + 1
                    prefix = package[:keep]
                    suffix = node.module.split(".") if node.module else []
                    imported_module = ".".join(prefix + suffix)
                elif node.module:
                    imported_module = node.module
                if imported_module:
                    names.add(imported_module)
                    names.update(
                        f"{imported_module}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
        return names

    queue = ["workflow_scheduler.execution.runtime_configuration"]
    seen: set[str] = set()
    all_imports: set[str] = set()
    while queue:
        module = queue.pop(0)
        if module in seen:
            continue
        seen.add(module)
        path = modules.get(module)
        if path is None:
            continue
        imports = imported_names(module, path)
        all_imports.update(imports)
        for imported in imports:
            candidate = imported
            while candidate and candidate not in modules and "." in candidate:
                candidate = candidate.rsplit(".", 1)[0]
            if candidate in modules and candidate not in seen:
                queue.append(candidate)

    assert all_imports.isdisjoint(forbidden)
    assert seen.isdisjoint(forbidden)


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


# --- reconstruct_concrete_runtime_configuration (#1071) ---------------------


def test_reconstruction_round_trips_payload_fingerprint_and_is_deterministic(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    fingerprint = original.configuration_fingerprint

    first = reconstruct_concrete_runtime_configuration(
        payload, configuration_fingerprint=fingerprint
    )
    second = reconstruct_concrete_runtime_configuration(
        copy.deepcopy(payload), configuration_fingerprint=fingerprint
    )

    assert first == original
    assert first == second
    assert first.configuration_fingerprint == fingerprint
    assert runtime_configuration_payload(first) == payload
    assert runtime_configuration_payload(second) == payload
    assert tuple(command.test_id for command in first.required_test_commands) == tuple(
        command.test_id for command in original.required_test_commands
    )
    first.verify(tsp._pilot_input())


def test_reconstruction_does_not_mutate_input_payload(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    snapshot = copy.deepcopy(payload)
    reconstruct_concrete_runtime_configuration(
        payload, configuration_fingerprint=original.configuration_fingerprint
    )
    assert payload == snapshot


def test_reconstruction_rejects_fingerprint_tampering(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint="concrete-adapters:" + "0" * 64
        )


def test_reconstruction_rejects_semantic_drift_with_original_fingerprint(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    drifted = copy.deepcopy(payload)
    drifted["branch"] = drifted["branch"] + "-drifted"
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            drifted, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_unknown_top_level_field(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["unexpected_field"] = "x"
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_missing_top_level_field(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    del payload["branch"]
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_unsupported_schema_name(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["schema_name"] = "wrong-schema"
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["schema_version"] = "9.9"
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_unsupported_execution_mode(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["execution_mode"] = "not-a-real-mode"
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_unsupported_environment_policy(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["environment_policy"] = "not-a-real-policy"
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_malformed_repository_identity_shape(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["repository_identity"] = "not-a-dict"
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_unknown_repository_identity_field(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["repository_identity"] = dict(
        payload["repository_identity"], unexpected="x"
    )
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_missing_repository_identity_field(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    identity = dict(payload["repository_identity"])
    del identity["host"]
    payload["repository_identity"] = identity
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_bool_repository_id(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    identity = dict(payload["repository_identity"], repository_id=True)
    payload["repository_identity"] = identity
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_bool_upstream_repository_id(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    identity = dict(payload["repository_identity"], upstream_repository_id=True)
    payload["repository_identity"] = identity
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_repository_identity_round_trips_exactly(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    reconstructed = reconstruct_concrete_runtime_configuration(
        payload, configuration_fingerprint=original.configuration_fingerprint
    )
    assert reconstructed.repository_identity == original.repository_identity
    assert isinstance(reconstructed.repository_identity, RepositoryIdentity)


def test_reconstruction_rejects_malformed_frozen_test_command(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    commands = list(payload["required_test_commands"])
    commands[0] = dict(commands[0], test_id="")
    payload["required_test_commands"] = commands
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_unknown_command_field(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    commands = list(payload["required_test_commands"])
    commands[0] = dict(commands[0], unexpected="x")
    payload["required_test_commands"] = commands
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_missing_command_field(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    commands = list(payload["required_test_commands"])
    reduced = dict(commands[0])
    del reduced["argv"]
    commands[0] = reduced
    payload["required_test_commands"] = commands
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_requires_command_argv_list_before_tuple_conversion(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    commands = list(payload["required_test_commands"])
    commands[0] = dict(commands[0], argv=tuple(commands[0]["argv"]))
    payload["required_test_commands"] = commands
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_malformed_command_argv_item(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    commands = list(payload["required_test_commands"])
    commands[0] = dict(commands[0], argv=[123])
    payload["required_test_commands"] = commands
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_requires_required_test_commands_to_be_a_list(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["required_test_commands"] = tuple(payload["required_test_commands"])
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_preserves_command_order(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    reconstructed = reconstruct_concrete_runtime_configuration(
        payload, configuration_fingerprint=original.configuration_fingerprint
    )
    assert [command["test_id"] for command in payload["required_test_commands"]] == [
        command.test_id for command in reconstructed.required_test_commands
    ]


def test_reconstruction_rejects_command_reorder_with_original_fingerprint(
    tmp_path: Path,
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    commands = list(payload["required_test_commands"])
    extra = dict(commands[0], test_id=commands[0]["test_id"] + "-second")
    payload["required_test_commands"] = [*commands, extra]
    ordered_fingerprint = rc._fingerprint(payload)
    reconstructed = reconstruct_concrete_runtime_configuration(
        payload, configuration_fingerprint=ordered_fingerprint
    )
    assert [command.test_id for command in reconstructed.required_test_commands] == [
        command["test_id"] for command in payload["required_test_commands"]
    ]

    reordered = copy.deepcopy(payload)
    reordered["required_test_commands"] = list(reversed(payload["required_test_commands"]))
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            reordered, configuration_fingerprint=ordered_fingerprint
        )


def test_reconstruction_requires_executor_argv_list_or_null(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["executor_argv"] = tuple(payload["executor_argv"])
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_bool_issue_number(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["issue_number"] = True
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


@pytest.mark.parametrize(
    "field",
    [
        "executor_timeout_seconds",
        "executor_grace_period_seconds",
        "validation_per_command_timeout_seconds",
        "validation_total_timeout_seconds",
    ],
)
def test_reconstruction_rejects_bool_timeout_values(
    tmp_path: Path, field: str
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload[field] = True
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


@pytest.mark.parametrize(
    "field", ["executor_max_output_bytes", "validation_max_output_bytes"]
)
def test_reconstruction_rejects_bool_output_bounds(tmp_path: Path, field: str) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload[field] = True
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


@pytest.mark.parametrize(
    "field", ["base_sha", "source_head_sha", "tested_sha"]
)
def test_reconstruction_rejects_malformed_sha(tmp_path: Path, field: str) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload[field] = "not-a-sha"
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_malformed_allowed_files(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["allowed_files"] = ["../escape"]
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_malformed_forbidden_paths(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["forbidden_paths"] = ["/absolute"]
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_rejects_malformed_id_text(tmp_path: Path) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)
    payload["invocation_id"] = ""
    with pytest.raises(ConcreteRuntimeConfigurationError):
        reconstruct_concrete_runtime_configuration(
            payload, configuration_fingerprint=original.configuration_fingerprint
        )


def test_reconstruction_never_calls_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("reconstruction must never call bind(...)")

    monkeypatch.setattr(ConcreteRuntimeConfiguration, "bind", _forbidden)
    reconstruct_concrete_runtime_configuration(
        payload, configuration_fingerprint=original.configuration_fingerprint
    )


def test_reconstruction_never_probes_the_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)

    def _forbidden(_path: object) -> bool:
        raise AssertionError("reconstruction must never probe directory existence")

    monkeypatch.setattr(rc.os.path, "isdir", _forbidden)
    reconstruct_concrete_runtime_configuration(
        payload, configuration_fingerprint=original.configuration_fingerprint
    )


def test_reconstruction_never_derives_a_workspace_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _bound_configuration(tmp_path)
    payload = runtime_configuration_payload(original)

    def _forbidden(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("reconstruction must never derive a workspace path")

    monkeypatch.setattr(rc, "_workspace_path", _forbidden)
    reconstruct_concrete_runtime_configuration(
        payload, configuration_fingerprint=original.configuration_fingerprint
    )
