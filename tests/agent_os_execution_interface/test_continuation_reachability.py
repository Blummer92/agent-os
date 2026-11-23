from __future__ import annotations

import ast
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

GOVERNED_CONTINUATION_DECISIONS = {
    "plan_execution_continuation": REPO_ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/continuation.py",
    "classify_recovery_progress": REPO_ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/recovery_progress.py",
    "evaluate_mission_completion_admission": REPO_ROOT / "scripts/agent_os_execution_interface/mission_completion_admission.py",
    "evaluate_failed_repair_admission": REPO_ROOT / "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/failed_repair_admission.py",
    "drive_governed_continuation": REPO_ROOT / "scripts/agent_os_execution_interface/continuation_driver.py",
}

# These decisions are currently referenced only by unregistered mcp_facade wrappers.
# Keeping the expected set explicit makes the reduction evidence visible without
# pretending the wrappers are runtime consumers. #2772/#1729 own their retirement.
KNOWN_UNCONSUMED_DECISIONS = {
    # RETAINED (#1188 planner, campaign reduction boundary): plan_execution_continuation
    # and its pieces in continuation.py are the canonical composition seam and must
    # not be deleted, retired, or consumed by this campaign. #2281 composes with
    # classify_recovery_progress only; the planner stays exactly as-is.
    "plan_execution_continuation",
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


def _parse_snapshot(files: tuple[Path, ...]) -> dict[Path, ast.Module]:
    """Read and parse each file once for a SINGLE analysis invocation.

    The snapshot is built from fresh reads at the start of every
    ``_production_consumers`` call and is only ever held in that call's local
    variables. It is never stored at module level or reused by a later call, so
    an edit, addition or deletion between invocations is always observed. The
    trees are read-only inputs: no analysis helper mutates them.
    """
    # Preserve the caller's file sequence for reachability semantics, but
    # never parse the same path more than once within this invocation.
    return {path: _tree(path) for path in dict.fromkeys(files)}


def _top_level_functions(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
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


def _module_called_names(tree: ast.Module) -> set[str]:
    return _called_names(tree.body)


def _main_guard_called_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
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
    trees: dict[Path, ast.Module],
) -> dict[
    str,
    tuple[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef], ...],
]:
    index: dict[
        str,
        list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]],
    ] = {}
    for path in files:
        for name, node in _top_level_functions(trees[path]).items():
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


def _reachable_functions(
    files: tuple[Path, ...],
    trees: dict[Path, ast.Module],
) -> set[tuple[Path, str]]:
    """Resolve bounded reachability from explicit script and MCP roots.

    Exact path+function script roots avoid guessing among common names such as
    main. Ambiguous transitive same-name definitions still fail closed. This
    helper proves the continuation decisions in this regression suite; it is
    not a general repository dead-code analyzer. ``trees`` is the caller's
    single-invocation parse snapshot of ``files``.
    """
    index = _definition_index(files, trees)
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
        functions = _top_level_functions(trees[path])
        for entrypoint_name in RUNTIME_ENTRYPOINTS.get(path, ()):
            entrypoint = functions.get(entrypoint_name)
            if entrypoint is not None:
                admit((path, entrypoint))
        for name in _main_guard_called_names(trees[path]):
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
    trees = _parse_snapshot(production_files)
    reachable = _reachable_functions(production_files, trees)
    consumers: set[Path] = set()
    for path, caller_name in reachable:
        if path == owner and caller_name == function_name:
            continue
        caller = _top_level_functions(trees[path]).get(caller_name)
        if (
            caller is not None
            and function_name in _function_called_names(caller)
        ):
            consumers.add(path)
    for path in production_files:
        if (
            path != owner
            and function_name in _module_called_names(trees[path])
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


# The tests below pin the freshness and semantic contract of the per-invocation
# parse snapshot: every analysis re-reads current source, nothing survives
# between invocations, and graph semantics are unchanged by parsing once.
_LIVE_ENTRYPOINT = (
    "from wrapper import live_wrapper\n\n"
    "if __name__ == '__main__':\n"
    "    live_wrapper()\n"
)


def _absolute(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    # Results are repo-relative for files under REPO_ROOT and absolute otherwise;
    # compare against absolute fixture paths wherever pytest's tmp_path lives.
    return tuple(REPO_ROOT / path for path in paths)


def test_each_invocation_observes_source_edits_between_calls(
    tmp_path: Path,
) -> None:
    owner = tmp_path / "owner.py"
    wrapper = tmp_path / "wrapper.py"
    entrypoint = tmp_path / "entrypoint.py"
    owner.write_text("def governed():\n    return 'ok'\n", encoding="utf-8")
    entrypoint.write_text(_LIVE_ENTRYPOINT, encoding="utf-8")
    files = (owner, wrapper, entrypoint)

    wrapper.write_text(
        "def live_wrapper():\n    return governed()\n", encoding="utf-8"
    )
    assert _absolute(_production_consumers("governed", owner, files=files)) == (wrapper,)
    wrapper.write_text(
        "def live_wrapper():\n    return 'detached'\n", encoding="utf-8"
    )
    assert _absolute(_production_consumers("governed", owner, files=files)) == ()
    wrapper.write_text(
        "def live_wrapper():\n    return governed()\n", encoding="utf-8"
    )
    assert _absolute(_production_consumers("governed", owner, files=files)) == (wrapper,)

    # A same-size edit with the original timestamps restored must still be
    # seen: freshness may not depend on size or modification-time shortcuts.
    stamp = wrapper.stat()
    wrapper.write_text(
        "def live_wrapper():\n    return governor()\n", encoding="utf-8"
    )
    os.utime(wrapper, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert wrapper.stat().st_size == stamp.st_size
    assert wrapper.stat().st_mtime_ns == stamp.st_mtime_ns
    assert _absolute(_production_consumers("governed", owner, files=files)) == ()


def test_each_invocation_enumerates_added_and_deleted_files(
    tmp_path: Path, monkeypatch
) -> None:
    assert "tests" not in tmp_path.parts
    root = tmp_path / "prod"
    root.mkdir()
    owner = root / "owner.py"
    entrypoint = root / "entrypoint.py"
    late = root / "wrapper.py"
    owner.write_text("def governed():\n    return 'ok'\n", encoding="utf-8")
    entrypoint.write_text(_LIVE_ENTRYPOINT, encoding="utf-8")
    monkeypatch.setitem(globals(), "PRODUCTION_ROOTS", (root,))
    monkeypatch.setitem(globals(), "RUNTIME_ENTRYPOINTS", {})

    assert _absolute(_production_consumers("governed", owner)) == ()
    late.write_text(
        "def live_wrapper():\n    return governed()\n", encoding="utf-8"
    )
    assert _absolute(_production_consumers("governed", owner)) == (late,)
    late.unlink()
    assert _absolute(_production_consumers("governed", owner)) == ()


def test_duplicate_definitions_stay_ambiguous_until_the_source_changes(
    tmp_path: Path,
) -> None:
    owner = tmp_path / "owner.py"
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    entrypoint = tmp_path / "entrypoint.py"
    owner.write_text("def governed():\n    return 'ok'\n", encoding="utf-8")
    first.write_text(
        "def live_wrapper():\n    return governed()\n", encoding="utf-8"
    )
    second.write_text(
        "def live_wrapper():\n    return 'other'\n", encoding="utf-8"
    )
    entrypoint.write_text(_LIVE_ENTRYPOINT, encoding="utf-8")
    files = (owner, first, second, entrypoint)

    # Same-name transitive definitions in two files fail closed.
    assert _absolute(_production_consumers("governed", owner, files=files)) == ()
    # A fresh read sees the ambiguity removed in the very next invocation.
    second.write_text("VALUE = 1\n", encoding="utf-8")
    assert _absolute(_production_consumers("governed", owner, files=files)) == (first,)
    # `files` is consumed exactly as given: a repeated path is a repeated
    # definition and therefore stays ambiguous.
    repeated = (owner, first, first, entrypoint)
    assert _production_consumers("governed", owner, files=repeated) == ()


def test_graph_edge_kinds_keep_their_existing_semantics(
    tmp_path: Path,
) -> None:
    owner = tmp_path / "owner.py"
    mcp_tool = tmp_path / "mcp_tool.py"
    table_user = tmp_path / "table_user.py"
    module_level = tmp_path / "module_level.py"
    class_only = tmp_path / "class_only.py"
    nested_only = tmp_path / "nested_only.py"
    entrypoint = tmp_path / "entrypoint.py"
    owner.write_text("def governed():\n    return 'ok'\n", encoding="utf-8")
    mcp_tool.write_text(
        "@mcp.tool()\ndef registered():\n    return governed()\n",
        encoding="utf-8",
    )
    table_user.write_text(
        "def via_table():\n    return governed()\n", encoding="utf-8"
    )
    module_level.write_text("RESULT = governed()\n", encoding="utf-8")
    class_only.write_text(
        "class Holder:\n"
        "    VALUE = governed()\n\n"
        "    def method(self):\n"
        "        return governed()\n",
        encoding="utf-8",
    )
    nested_only.write_text(
        "def outer():\n"
        "    def inner():\n"
        "        return governed()\n"
        "    return inner\n",
        encoding="utf-8",
    )
    entrypoint.write_text(
        "def main():\n"
        "    return {'k': via_table, 'o': outer}\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    consumers = _absolute(_production_consumers(
        "governed",
        owner,
        files=(
            owner,
            mcp_tool,
            table_user,
            module_level,
            class_only,
            nested_only,
            entrypoint,
        ),
    ))
    # MCP root, dispatch-table edge and module-level call are real edges;
    # class bodies and nested definitions are not, and ordering is sorted.
    assert consumers == tuple(
        sorted((mcp_tool, table_user, module_level))
    )


def test_parse_errors_still_fail_and_a_fixed_file_is_read_afresh(
    tmp_path: Path,
) -> None:
    owner = tmp_path / "owner.py"
    broken = tmp_path / "broken.py"
    owner.write_text("def governed():\n    return 'ok'\n", encoding="utf-8")
    broken.write_text("def (:\n", encoding="utf-8")
    files = (owner, broken)

    try:
        _production_consumers("governed", owner, files=files)
    except SyntaxError:
        pass
    else:
        raise AssertionError("a syntax error must not be swallowed")
    try:
        _production_consumers("governed", owner, files=(owner, tmp_path / "ghost.py"))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("a missing file must not be skipped")
    # A failed analysis leaves nothing behind: the repaired file is re-read.
    broken.write_text("def helper():\n    return governed()\n", encoding="utf-8")
    assert _absolute(_production_consumers("governed", owner, files=files)) == ()


def test_each_invocation_parses_every_file_once_and_shares_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    owner = tmp_path / "owner.py"
    wrapper = tmp_path / "wrapper.py"
    entrypoint = tmp_path / "entrypoint.py"
    owner.write_text("def governed():\n    return 'ok'\n", encoding="utf-8")
    wrapper.write_text(
        "def live_wrapper():\n    return governed()\n", encoding="utf-8"
    )
    entrypoint.write_text(_LIVE_ENTRYPOINT, encoding="utf-8")
    files = (owner, wrapper, entrypoint)
    parsed: list[str] = []
    real_parse = ast.parse

    def counting_parse(source, filename="<unknown>", *args, **kwargs):
        parsed.append(str(filename))
        return real_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", counting_parse)
    expected = sorted(str(path) for path in files)

    assert _absolute(_production_consumers("governed", owner, files=files)) == (wrapper,)
    assert sorted(parsed) == expected
    # A second invocation re-parses everything: no state survives between calls.
    assert _absolute(_production_consumers("governed", owner, files=files)) == (wrapper,)
    assert sorted(parsed) == sorted(expected * 2)

    # Duplicate paths preserve existing ambiguity semantics but must not
    # trigger duplicate reads or parses within the same invocation.
    parsed.clear()
    repeated = (owner, wrapper, wrapper, entrypoint)
    assert _production_consumers("governed", owner, files=repeated) == ()
    assert sorted(parsed) == expected


def test_only_the_exact_main_guard_form_is_a_runtime_root(
    tmp_path: Path,
) -> None:
    owner = tmp_path / "owner.py"
    owner.write_text("def governed():\n    return 'ok'\n", encoding="utf-8")
    forms = {
        "exact": "__name__ == '__main__'",
        "reversed": "'__main__' == __name__",
        "negated": "__name__ != '__main__'",
    }
    files = [owner]
    for label, condition in forms.items():
        wrapper = tmp_path / f"wrapper_{label}.py"
        guard = tmp_path / f"guard_{label}.py"
        wrapper.write_text(
            f"def go_{label}():\n    return governed()\n", encoding="utf-8"
        )
        guard.write_text(f"if {condition}:\n    go_{label}()\n", encoding="utf-8")
        files += [wrapper, guard]
    consumers = _production_consumers("governed", owner, files=tuple(files))
    assert _absolute(consumers) == (tmp_path / "wrapper_exact.py",)
