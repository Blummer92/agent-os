"""Focused packaging/import boundary test for Issue #912.

Proves the canonical `workflow_scheduler` package (08_Tooling/workflow-scheduler/
src/workflow_scheduler) is importable from the repository root through the
standard editable-package install declared in `requirements-dev.txt`, with no
sys.path mutation, no duplicate installed module path, no import-time side
effects, and no circular import against `scripts/**`.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import importlib.util
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL_PACKAGE_ROOT = (
    ROOT / "08_Tooling" / "workflow-scheduler" / "src" / "workflow_scheduler"
).resolve()
SCRIPTS_ROOT = ROOT / "scripts"

TARGET_MODULES = (
    "workflow_scheduler",
    "workflow_scheduler.planning",
    "workflow_scheduler.planning.draft_ingestion",
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

    real_open = builtins.open

    def _deny_write_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"workflow_scheduler import must not write to {file!r}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _deny_subprocess)
    monkeypatch.setattr(subprocess, "run", _deny_subprocess)
    monkeypatch.setattr(socket, "socket", _deny_socket)
    monkeypatch.setattr(builtins, "open", _deny_write_open)

    _fresh_import_of_target()


def _imports_workflow_scheduler(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "workflow_scheduler" or alias.name.startswith("workflow_scheduler.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "workflow_scheduler" or module.startswith("workflow_scheduler."):
                return True
    return False


def test_no_circular_import_between_scripts_and_workflow_scheduler() -> None:
    _fresh_import_of_target()

    offending = [
        path
        for path in SCRIPTS_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts and _imports_workflow_scheduler(path)
    ]
    assert offending == []
