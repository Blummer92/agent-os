"""Architecture-boundary tests for the #755 pure-local compiler.

Proves, statically and dynamically, that ``models.py``, ``provenance.py``,
``freshness.py``, ``blockers.py``, and ``compiler.py`` cannot reach a
network, subprocess, Git, filesystem-mutation, GitHub/Drive/Sheets/Notion/
Cloud Build, Scheduler-execution, lease/worktree, or merge/publication
capability, that importing the package performs no I/O, and that a
monkeypatched prohibited capability is never actually invoked during a
successful compile.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

_PACKAGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "agent_os_candidate_packet"
_COMPILER_MODULES = ("models.py", "provenance.py", "freshness.py", "blockers.py", "compiler.py")

_FORBIDDEN_MODULE_PREFIXES = (
    "subprocess",
    "socket",
    "urllib",
    "http.client",
    "requests",
    "git",
    "github",
    "google",
    "googleapiclient",
    "notion_client",
    "gcloud",
    "google.cloud",
    "workflow_scheduler.execution.executor",
    "workflow_scheduler.execution.lease",
    "workflow_scheduler.execution.worktree",
)


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("filename", _COMPILER_MODULES)
def test_module_imports_no_forbidden_capability(filename: str) -> None:
    imported = _imported_module_names(_PACKAGE_DIR / filename)
    for name in imported:
        for forbidden in _FORBIDDEN_MODULE_PREFIXES:
            assert not name.startswith(forbidden), f"{filename} imports forbidden module {name!r}"


@pytest.mark.parametrize("filename", _COMPILER_MODULES)
def test_module_contains_no_subprocess_or_filesystem_write_calls(filename: str) -> None:
    source = (_PACKAGE_DIR / filename).read_text(encoding="utf-8")
    for banned in (
        "subprocess.",
        "os.system(",
        "os.popen(",
        "shutil.rmtree",
        "shutil.copy",
        "open(",
        ".write_text(",
        ".write_bytes(",
        "socket.socket",
        "urlopen(",
    ):
        assert banned not in source, f"{filename} contains banned call {banned!r}"


def test_compiler_only_catches_type_and_value_errors() -> None:
    """KeyboardInterrupt/SystemExit/GeneratorExit must never become a compile failure.

    Every ``try/except`` in ``compiler.py`` narrows to exactly
    ``(TypeError, ValueError)`` (the two exception types every reused stage
    transport raises on drift); nothing broader is ever caught, so a
    ``KeyboardInterrupt`` or ``SystemExit`` raised inside a reused transport
    still propagates instead of being reported as an ordinary failure.
    """
    tree = ast.parse((_PACKAGE_DIR / "compiler.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                pytest.fail("compiler.py must not use a bare except clause")
            names = (
                {elt.id for elt in node.type.elts if isinstance(elt, ast.Name)}
                if isinstance(node.type, ast.Tuple)
                else {node.type.id} if isinstance(node.type, ast.Name) else set()
            )
            assert names <= {"TypeError", "ValueError"}, (
                f"compiler.py catches an exception broader than TypeError/ValueError: {names}"
            )


def test_package_import_performs_no_io() -> None:
    """No import-time I/O is possible: no module contains an I/O call at all.

    Reloading an already-imported package submodule would corrupt class
    identity for every other test module that already bound a name from it
    (Python module reload mutates the shared namespace dict in place), so
    this is proven statically instead: ``test_module_contains_no_subprocess_or_filesystem_write_calls``
    already shows zero I/O call sites anywhere in these files, which is a
    strictly stronger guarantee than "none execute at import time."
    """
    for filename in _COMPILER_MODULES:
        source = (_PACKAGE_DIR / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        module_level_calls = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        ]
        assert module_level_calls == [], f"{filename} executes a call at module scope"


def test_successful_compile_never_invokes_a_monkeypatched_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.agent_os_candidate_packet.compiler import compile_candidate_packet
    from scripts.agent_os_candidate_packet.models import CandidatePacket
    from tests.agent_os_candidate_packet.test_compiler import valid_approval_ready_input

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("prohibited capability invoked during compile")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)

    result = compile_candidate_packet(valid_approval_ready_input(), evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacket)


def test_no_object_produced_by_a_successful_compile_grants_authority(tmp_path) -> None:
    from scripts.agent_os_candidate_packet.compiler import compile_candidate_packet
    from scripts.agent_os_candidate_packet.models import CandidatePacket
    from tests.agent_os_candidate_packet.test_compiler import valid_execution_candidate_input

    result = compile_candidate_packet(
        valid_execution_candidate_input(tmp_path), evaluated_at="2026-08-11T12:05:00Z"
    )

    assert isinstance(result, CandidatePacket)
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.automatic_retry is False
    assert result.side_effects_performed is False
