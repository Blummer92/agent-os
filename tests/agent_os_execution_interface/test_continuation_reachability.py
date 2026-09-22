from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

GOVERNED_CONTINUATION_DECISIONS = {
    "plan_execution_continuation": REPO_ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/continuation.py",
    "plan_red_ci_continuation": REPO_ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/red_ci_continuation.py",
    "classify_recovery_progress": REPO_ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/recovery_progress.py",
    "evaluate_mission_completion_admission": REPO_ROOT / "scripts/agent_os_execution_interface/mission_completion_admission.py",
    "evaluate_failed_repair_admission": REPO_ROOT / "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/failed_repair_admission.py",
    "drive_governed_continuation": REPO_ROOT / "scripts/agent_os_execution_interface/continuation_driver.py",
}

# These decisions are currently referenced only by unregistered mcp_facade wrappers.
# Keeping the expected set explicit makes the reduction evidence visible without
# pretending the wrappers are runtime consumers. #2772/#1729 own their retirement.
KNOWN_UNCONSUMED_DECISIONS = {
    "plan_execution_continuation",
    "plan_red_ci_continuation",
    "classify_recovery_progress",
}

PRODUCTION_ROOTS = (
    REPO_ROOT / "scripts",
    REPO_ROOT / "08_Tooling/agent-memory-context-manager/src",
    REPO_ROOT / "08_Tooling/agent-os-execution-service/src",
    REPO_ROOT / "08_Tooling/workflow-scheduler/src",
)

RUNTIME_ENTRYPOINTS = {
    REPO_ROOT / "scripts/agent-os-execution-interface-preflight.py": ("main",),
}


def _production_python_files() -> tuple[Path, ...]:
    files: list[Path] = []
    for root in PRODUCTION_ROOTS:
        files.extend(path for path in root.rglob("*.py") if "tests" not in path.parts)
    return tuple(sorted(set(files)))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _top_level_functions(
    path: Path,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in _tree(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _called_names(nodes: list[ast.stmt]) -> set[str]:
    names: set[str] = set()

    class Calls(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Dict(self, node: ast.Dict) -> None:
            # Reachable dispatch tables are real runtime edges even when the
            # function is invoked later through subscription.
            for value in node.values:
                if isinstance(value, ast.Name):
                    names.add(value.id)
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

    visitor = Calls()
    for node in nodes:
        visitor.visit(node)
    return names


def _function_called_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    return _called_names(node.body)


def _module_called_names(path: Path) -> set[str]:
    return _called_names(_tree(path).body)


def _main_guard_called_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in _tree(path).body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            continue
        names.update(_called_names(node.body))
    return names


def _is_mcp_tool(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "tool":
            return True
    return False


def _definition_index(
    files: tuple[Path, ...],
) -> dict[
    str,
    tuple[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef], ...],
]:
    index: dict[
        str,
        list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]],
    ] = {}
    for path in files:
        for name, node in _top_level_functions(path).items():
            index.setdefault(name, []).append((path, node))
    return {name: tuple(definitions) for name, definitions in index.items()}


def _unique_definition(
    name: str,
    index: dict[
        str,
        tuple[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef], ...],
    ],
) -> tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef] | None:
    definitions = index.get(name, ())
    return definitions[0] if len(definitions) == 1 else None


def _reachable_functions(files: tuple[Path, ...]) -> set[tuple[Path, str]]:
    """Resolve bounded reachability from explicit script and MCP roots.

    Exact path+function script roots avoid guessing among common names such as
    main. Ambiguous transitive same-name definitions still fail closed. This
    helper proves the continuation decisions in this regression suite; it is
    not a general repository dead-code analyzer.
    """
    index = _definition_index(files)
    reachable: set[tuple[Path, str]] = set()
    pending: list[
        tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]
    ] = []

    def admit(
        definition: tuple[
            Path, ast.FunctionDef | ast.AsyncFunctionDef
        ] | None,
    ) -> None:
        if definition is None:
            return
        path, node = definition
        identity = (path, node.name)
        if identity not in reachable:
            reachable.add(identity)
            pending.append(definition)

    for path in files:
        functions = _top_level_functions(path)
        for entrypoint_name in RUNTIME_ENTRYPOINTS.get(path, ()):
            entrypoint = functions.get(entrypoint_name)
            if entrypoint is not None:
                admit((path, entrypoint))
        for name in _main_guard_called_names(path):
            admit(_unique_definition(name, index))
        for node in functions.values():
            if _is_mcp_tool(node):
                admit((path, node))

    while pending:
        _, node = pending.pop()
        for name in _function_called_names(node):
            admit(_unique_definition(name, index))
    return reachable


def _production_consumers(
    function_name: str,
    owner: Path,
    *,
    files: tuple[Path, ...] | None = None,
) -> tuple[Path, ...]:
    production_files = (
        _production_python_files() if files is None else files
    )
    reachable = _reachable_functions(production_files)
    consumers: set[Path] = set()
    for path, caller_name in reachable:
        if path == owner and caller_name == function_name:
            continue
        caller = _top_level_functions(path).get(caller_name)
        if (
            caller is not None
            and function_name in _function_called_names(caller)
        ):
            consumers.add(path)
    for path in production_files:
        if (
            path != owner
            and function_name in _module_called_names(path)
        ):
            consumers.add(path)
    return tuple(
        sorted(
            path.relative_to(REPO_ROOT)
            if path.is_relative_to(REPO_ROOT)
            else path
            for path in consumers
        )
    )


def test_governed_continuation_reachability_matches_current_runtime() -> None:
    missing = {
        name
        for name, owner in GOVERNED_CONTINUATION_DECISIONS.items()
        if not _production_consumers(name, owner)
    }
    assert missing == KNOWN_UNCONSUMED_DECISIONS


def test_dead_wrapper_does_not_create_production_reachability(
    tmp_path: Path,
) -> None:
    owner = tmp_path / "owner.py"
    wrapper = tmp_path / "wrapper.py"
    owner.write_text(
        "def governed():\n    return 'ok'\n",
        encoding="utf-8",
    )
    wrapper.write_text(
        "from owner import governed\n\n"
        "def dead_wrapper():\n"
        "    return governed()\n",
        encoding="utf-8",
    )
    assert _production_consumers(
        "governed", owner, files=(owner, wrapper)
    ) == ()


def test_live_entrypoint_wrapper_creates_production_reachability(
    tmp_path: Path,
) -> None:
    owner = tmp_path / "owner.py"
    wrapper = tmp_path / "wrapper.py"
    entrypoint = tmp_path / "entrypoint.py"
    owner.write_text(
        "def governed():\n    return 'ok'\n",
        encoding="utf-8",
    )
    wrapper.write_text(
        "from owner import governed\n\n"
        "def live_wrapper():\n"
        "    return governed()\n",
        encoding="utf-8",
    )
    entrypoint.write_text(
        "from wrapper import live_wrapper\n\n"
        "if __name__ == '__main__':\n"
        "    live_wrapper()\n",
        encoding="utf-8",
    )
    assert _production_consumers(
        "governed",
        owner,
        files=(owner, wrapper, entrypoint),
    ) == (wrapper,)


def test_test_only_reference_does_not_enter_production_file_set() -> None:
    assert Path(__file__).resolve() not in _production_python_files()


def test_driver_is_reached_from_a_runtime_entrypoint() -> None:
    consumers = _production_consumers(
        "drive_governed_continuation",
        GOVERNED_CONTINUATION_DECISIONS["drive_governed_continuation"],
    )
    assert Path("scripts/agent_os_execution_interface/hook_adapter.py") in consumers
