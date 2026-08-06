"""Focused packaging/import boundary test for Issue #912.

Proves the canonical `workflow_scheduler` package (08_Tooling/workflow-scheduler/
src/workflow_scheduler) is importable from the repository root through the
standard editable-package install declared in `requirements-dev.txt`, with no
sys.path mutation, no duplicate installed module path, no import-time side
effects, and no circular import against `scripts/**`.

Issue #752 replaced the original blanket prohibition on every `scripts/**`
import of `workflow_scheduler` with the strict allowlist below. Exactly one
importer, one module, and three public symbols are permitted; everything else
still fails. This is not a general licence for `scripts/** ->
workflow_scheduler` dependencies.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import importlib.util
import io
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL_PACKAGE_ROOT = (
    ROOT / "08_Tooling" / "workflow-scheduler" / "src" / "workflow_scheduler"
).resolve()
SCRIPTS_ROOT = ROOT / "scripts"
CANDIDATE_PACKET_ROOT = SCRIPTS_ROOT / "agent_os_candidate_packet"

TARGET_MODULES = (
    "workflow_scheduler",
    "workflow_scheduler.planning",
    "workflow_scheduler.planning.draft_ingestion",
)

# The complete #752 dependency-boundary allowlist.
ALLOWED_IMPORTER = CANDIDATE_PACKET_ROOT / "proposal_stage.py"
ALLOWED_MODULE = "workflow_scheduler.planning.draft_ingestion"
ALLOWED_SYMBOLS = frozenset(
    {"DraftTaskProposal", "DraftTaskProposalResult", "build_draft_task_proposals"}
)

# Loader and import-machinery entry points that would let candidate-packet code
# reach Workflow Scheduler around the declared package boundary.
PROHIBITED_LOADER_CALLS = frozenset(
    {
        "__import__",
        "import_module",
        "spec_from_file_location",
        "module_from_spec",
        "SourceFileLoader",
        "load_source",
        "load_module",
        "exec_module",
    }
)


def _drop_from_sys_modules(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(prefix + "."):
            sys.modules.pop(name, None)


def _fresh_import_of_target() -> None:
    for module_name in TARGET_MODULES:
        _drop_from_sys_modules(module_name)
    _drop_from_sys_modules("scripts")
    importlib.import_module("workflow_scheduler.planning.draft_ingestion")


def _cold_import_of_allowlisted_importer() -> None:
    """Import the allowlisted importer first, from a fully cold cache.

    Importing Workflow Scheduler first would leave it warm and prove nothing
    about the direction that could actually cycle, so both package prefixes are
    evicted and `proposal_stage` is what pulls Workflow Scheduler back in.
    """
    for module_name in TARGET_MODULES:
        _drop_from_sys_modules(module_name)
    _drop_from_sys_modules("scripts")
    importlib.import_module("scripts.agent_os_candidate_packet.proposal_stage")


def test_root_import_resolves_to_canonical_package_tree() -> None:
    _fresh_import_of_target()

    draft_ingestion = sys.modules["workflow_scheduler.planning.draft_ingestion"]
    resolved_module_path = Path(draft_ingestion.__file__).resolve()
    assert resolved_module_path == CANONICAL_PACKAGE_ROOT / "planning" / "draft_ingestion.py"

    package = sys.modules["workflow_scheduler"]
    search_locations = [Path(entry).resolve() for entry in package.__path__]
    assert search_locations == [CANONICAL_PACKAGE_ROOT]


def test_root_import_exposes_draft_task_proposal_symbols() -> None:
    from workflow_scheduler.planning.draft_ingestion import (
        DraftTaskProposal,
        build_draft_task_proposals,
    )

    assert DraftTaskProposal.__module__ == "workflow_scheduler.planning.draft_ingestion"
    assert callable(build_draft_task_proposals)


def test_no_duplicate_installed_workflow_scheduler_module_path() -> None:
    spec = importlib.util.find_spec("workflow_scheduler")
    assert spec is not None
    search_locations = [Path(entry).resolve() for entry in spec.submodule_search_locations]
    assert search_locations == [CANONICAL_PACKAGE_ROOT]


def test_import_performs_no_subprocess_network_or_filesystem_write(monkeypatch) -> None:
    def _deny_subprocess(*args, **kwargs):
        raise AssertionError("workflow_scheduler import must not invoke subprocess")

    def _deny_socket(*args, **kwargs):
        raise AssertionError("workflow_scheduler import must not open a network socket")

    real_builtin_open = builtins.open
    real_io_open = io.open
    real_os_open = os.open

    def _deny_write_mode(file, mode="r", *args, _real_open, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"workflow_scheduler import must not write to {file!r}")
        return _real_open(file, mode, *args, **kwargs)

    def _deny_os_write(file, flags, *args, **kwargs):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
        if flags & write_flags:
            raise AssertionError(f"workflow_scheduler import must not write to {file!r}")
        return real_os_open(file, flags, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _deny_subprocess)
    monkeypatch.setattr(subprocess, "run", _deny_subprocess)
    monkeypatch.setattr(socket, "socket", _deny_socket)
    monkeypatch.setattr(
        builtins,
        "open",
        lambda file, mode="r", *args, **kwargs: _deny_write_mode(
            file, mode, *args, _real_open=real_builtin_open, **kwargs
        ),
    )
    monkeypatch.setattr(
        io,
        "open",
        lambda file, mode="r", *args, **kwargs: _deny_write_mode(
            file, mode, *args, _real_open=real_io_open, **kwargs
        ),
    )
    monkeypatch.setattr(os, "open", _deny_os_write)

    _fresh_import_of_target()


def _python_sources(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _is_prefixed(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _workflow_scheduler_imports(path: Path) -> list[tuple[str, str | None]]:
    """Return every `workflow_scheduler` import in `path` as (module, symbol).

    `symbol` is None for a plain `import workflow_scheduler...` statement, which
    binds the package itself rather than a named public symbol.
    """
    found: list[tuple[str, str | None]] = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            found.extend(
                (alias.name, None)
                for alias in node.names
                if _is_prefixed(alias.name, "workflow_scheduler")
            )
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if _is_prefixed(module, "workflow_scheduler"):
                found.extend((module, alias.name) for alias in node.names)
    return found


def _imports_prefix(path: Path, prefix: str) -> bool:
    """Detect an import of `prefix`, including `from <parent> import <member>`."""
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            if any(_is_prefixed(alias.name, prefix) for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if _is_prefixed(module, prefix):
                return True
            # `from scripts import agent_os_candidate_packet` names the target
            # as a member, not as the module.
            if any(
                _is_prefixed(f"{module}.{alias.name}", prefix) for alias in node.names
            ):
                return True
    return False


def _loader_aliases(tree: ast.Module) -> set[str]:
    """Local names bound to an import-machinery entry point, aliases included.

    `from importlib import import_module as load` must not launder a call to
    `load(...)` past the loader check.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                if alias.name in PROHIBITED_LOADER_CALLS:
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname and alias.name in PROHIBITED_LOADER_CALLS:
                    aliases.add(alias.asname)
    return aliases


def test_only_the_allowlisted_scripts_module_imports_workflow_scheduler() -> None:
    offending = [
        path.relative_to(ROOT).as_posix()
        for path in _python_sources(SCRIPTS_ROOT)
        if path != ALLOWED_IMPORTER and _workflow_scheduler_imports(path)
    ]
    assert offending == []

    # The allowlist entry exists only to serve the governed #752 WSC3 call. If
    # that call is ever removed, the exception must be removed with it.
    assert _workflow_scheduler_imports(ALLOWED_IMPORTER)


def test_allowlisted_importer_uses_only_the_permitted_module_and_symbols() -> None:
    imports = _workflow_scheduler_imports(ALLOWED_IMPORTER)

    assert {module for module, _ in imports} == {ALLOWED_MODULE}
    symbols = {symbol for _, symbol in imports}
    assert None not in symbols, "binding the package itself is not permitted"
    assert symbols <= ALLOWED_SYMBOLS


def test_candidate_packet_uses_no_private_path_loader_or_syspath_workaround() -> None:
    """No candidate-packet module may route around the declared boundary.

    Only absolute imports are inspected for private paths: an underscore-named
    module reached through a package's public name is a boundary workaround,
    while an intra-package relative import is ordinary Python.
    """
    offending: list[str] = []
    for path in _python_sources(CANDIDATE_PACKET_ROOT):
        name = path.relative_to(ROOT).as_posix()
        tree = _parse(path)
        prohibited_calls = PROHIBITED_LOADER_CALLS | _loader_aliases(tree)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                modules = [node.module or ""]
            for module in modules:
                if any(
                    part.startswith("_") and part != "__future__"
                    for part in module.split(".")
                    if part
                ):
                    offending.append(f"{name}: private import path {module!r}")

            if isinstance(node, ast.Attribute) and node.attr == "path":
                if isinstance(node.value, ast.Name) and node.value.id == "sys":
                    offending.append(f"{name}: sys.path access")
            if isinstance(node, ast.Call):
                function = node.func
                called = (
                    function.attr
                    if isinstance(function, ast.Attribute)
                    else function.id
                    if isinstance(function, ast.Name)
                    else ""
                )
                if called in prohibited_calls:
                    offending.append(f"{name}: import-machinery call {called!r}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "PYTHONPATH" in node.value:
                    offending.append(f"{name}: PYTHONPATH workaround")

    assert offending == []


def test_no_circular_import_between_scripts_and_workflow_scheduler() -> None:
    """Workflow Scheduler must never import back into the one package that
    imports it, and the allowlisted importer must load from a cold cache."""
    offending = [
        path.relative_to(ROOT).as_posix()
        for path in _python_sources(CANONICAL_PACKAGE_ROOT)
        if _imports_prefix(path, "scripts.agent_os_candidate_packet")
    ]
    assert offending == []

    _cold_import_of_allowlisted_importer()
