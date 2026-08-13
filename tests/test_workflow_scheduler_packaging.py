"""Focused packaging/import boundary test for Issue #912.

Proves the canonical `workflow_scheduler` package (08_Tooling/workflow-scheduler/
src/workflow_scheduler) is importable from the repository root through the
standard editable-package install declared in `requirements-dev.txt`, with no
sys.path mutation, no duplicate installed module path, no import-time side
effects, and no circular import against `scripts/**`.

Issue #752 replaced the original blanket prohibition on every `scripts/**`
import of `workflow_scheduler` with the strict allowlist below. Exactly one
importer, one module, and a closed set of public symbols are permitted (#1054
widened that set with the canonical DraftTaskProposalResult transport
functions); everything else still fails. This is not a general licence for
`scripts/** -> workflow_scheduler` dependencies.
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

# The complete #752 dependency-boundary allowlist, widened by #1054 for the
# canonical DraftTaskProposalResult transport (serialize/reconstruct) reused
# by RepositoryProposalStageResult's own outer-envelope transport.
ALLOWED_IMPORTER = CANDIDATE_PACKET_ROOT / "proposal_stage.py"
ALLOWED_MODULE = "workflow_scheduler.planning.draft_ingestion"
ALLOWED_SYMBOLS = frozenset(
    {
        "DraftTaskProposal",
        "DraftTaskProposalResult",
        "build_draft_task_proposals",
        "reconstruct_draft_task_proposal_result",
        "serialize_draft_task_proposal_result",
    }
)

# The #754 packet-preparation addition: the pure runtime-configuration seam
# only, never the executable adapter modules it is built from. #1054 widened
# this set with the canonical ConcreteRuntimeConfiguration transport
# functions reused by ExecutionPacketStageResult's own outer-envelope
# transport.
ALLOWED_IMPORTER_2 = CANDIDATE_PACKET_ROOT / "execution_packet_stage.py"
ALLOWED_MODULE_2 = "workflow_scheduler.execution.runtime_configuration"
ALLOWED_SYMBOLS_2 = frozenset(
    {
        "ConcreteRuntimeConfiguration",
        "ConcreteRuntimeConfigurationError",
        "FrozenTestCommand",
        "SingleIssuePilotInput",
        "VALIDATION_ONLY_EXECUTION_MODE",
        "reconstruct_concrete_runtime_configuration",
        "runtime_configuration_payload",
    }
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
    `load(...)` past the loader check, and neither may a plain assignment:
    `load = importlib.import_module` or a further `load2 = load` chain.
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

    # Second pass: plain assignments that bind a local name to an already-known
    # loader entry point. Iterated to a fixed point so a chain such as
    # `load = importlib.import_module; load2 = load` resolves regardless of
    # declaration order, without attempting general-purpose value tracking.
    # Annotated assignments (`load: object = importlib.import_module`) bind
    # exactly the same way, just with a single `.target` instead of a
    # `.targets` list, so they are folded into the same fixed-point pass.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                value = node.value
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                value = node.value
                targets = [node.target]
            else:
                continue
            is_loader_reference = (
                isinstance(value, ast.Attribute)
                and value.attr in PROHIBITED_LOADER_CALLS
            ) or (isinstance(value, ast.Name) and value.id in aliases)
            if not is_loader_reference:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return aliases


_ALLOWED_IMPORTERS = (ALLOWED_IMPORTER, ALLOWED_IMPORTER_2)


def test_only_the_allowlisted_scripts_module_imports_workflow_scheduler() -> None:
    offending = [
        path.relative_to(ROOT).as_posix()
        for path in _python_sources(SCRIPTS_ROOT)
        if path not in _ALLOWED_IMPORTERS and _workflow_scheduler_imports(path)
    ]
    assert offending == []

    # Each allowlist entry exists only to serve its governed call (#752 WSC3,
    # #754 packet preparation). If that call is ever removed, the exception
    # must be removed with it.
    assert _workflow_scheduler_imports(ALLOWED_IMPORTER)
    assert _workflow_scheduler_imports(ALLOWED_IMPORTER_2)


def test_allowlisted_importer_uses_only_the_permitted_module_and_symbols() -> None:
    for importer, module, allowed_symbols in (
        (ALLOWED_IMPORTER, ALLOWED_MODULE, ALLOWED_SYMBOLS),
        (ALLOWED_IMPORTER_2, ALLOWED_MODULE_2, ALLOWED_SYMBOLS_2),
    ):
        imports = _workflow_scheduler_imports(importer)

        assert {mod for mod, _ in imports} == {module}
        symbols = {symbol for _, symbol in imports}
        assert None not in symbols, "binding the package itself is not permitted"
        assert symbols <= allowed_symbols


def _boundary_violations(display_name: str, tree: ast.Module) -> list[str]:
    """Return every packaging-boundary violation found in `tree`.

    Shared by the real-tree scan below and by the direct bypass-vector
    regression tests further down, so both exercise identical detection
    logic rather than a parallel reimplementation that could drift.
    """
    offending: list[str] = []
    prohibited_calls = PROHIBITED_LOADER_CALLS | _loader_aliases(tree)
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            # Check the fully-qualified imported path, not just the parent
            # module: `from workflow_scheduler.planning import _private`
            # names an underscore-prefixed member even though the parent
            # module itself has no underscore component.
            base = node.module or ""
            modules = [
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
            ]
        for module in modules:
            if any(
                part.startswith("_") and part != "__future__"
                for part in module.split(".")
                if part
            ):
                offending.append(f"{display_name}: private import path {module!r}")

        if isinstance(node, ast.Attribute) and node.attr == "path":
            if isinstance(node.value, ast.Name) and node.value.id == "sys":
                offending.append(f"{display_name}: sys.path access")
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
                offending.append(f"{display_name}: import-machinery call {called!r}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "PYTHONPATH" in node.value:
                offending.append(f"{display_name}: PYTHONPATH workaround")
    return offending


def test_candidate_packet_uses_no_private_path_loader_or_syspath_workaround() -> None:
    """No candidate-packet module may route around the declared boundary.

    Only absolute imports are inspected for private paths: an underscore-named
    module reached through a package's public name is a boundary workaround,
    while an intra-package relative import is ordinary Python.
    """
    offending: list[str] = []
    for path in _python_sources(CANDIDATE_PACKET_ROOT):
        name = path.relative_to(ROOT).as_posix()
        offending.extend(_boundary_violations(name, _parse(path)))

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


# --------------------------------------------------------------------------
# Deterministic bypass-vector regression tests.
#
# The structural tests above prove the boundary holds against the real
# repository tree, but the real tree contains no bypass attempt -- so they
# cannot, by themselves, prove a bypass would actually be *detected*. These
# tests exercise the same detection helpers directly against synthetic
# source, one vector at a time, so each rejection is deterministic and does
# not depend on what happens to already be present in the codebase.
# --------------------------------------------------------------------------


def _module_and_symbols(source: str) -> list[tuple[str, str | None]]:
    """`_workflow_scheduler_imports`-equivalent over in-memory source."""
    found: list[tuple[str, str | None]] = []
    for node in ast.walk(ast.parse(source)):
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


def test_bypass_another_importer_is_detected() -> None:
    """Any workflow_scheduler import is detected regardless of which file it
    is in; the real test then rejects it unless the file is the one
    allowlisted importer."""
    assert _module_and_symbols(
        "from workflow_scheduler.planning.draft_ingestion import DraftTaskProposal\n"
    )


def test_bypass_another_scheduler_module_is_rejected() -> None:
    imports = _module_and_symbols(
        "from workflow_scheduler.planning import batch_planning\n"
    )
    assert {module for module, _ in imports} != {ALLOWED_MODULE}


def test_bypass_another_symbol_is_rejected() -> None:
    imports = _module_and_symbols(f"from {ALLOWED_MODULE} import OtherSymbol\n")
    symbols = {symbol for _, symbol in imports}
    assert not symbols <= ALLOWED_SYMBOLS


def test_bypass_binding_the_package_is_rejected() -> None:
    imports = _module_and_symbols(
        "import workflow_scheduler.planning.draft_ingestion\n"
    )
    symbols = {symbol for _, symbol in imports}
    assert None in symbols, "binding the package itself must be detected"


def test_bypass_private_import_path_is_rejected() -> None:
    tree = ast.parse("from workflow_scheduler.planning import _private\n")
    offending = _boundary_violations("synthetic", tree)
    assert any("private import path" in item for item in offending)


def test_bypass_sys_path_mutation_is_rejected() -> None:
    tree = ast.parse("import sys\nsys.path.append('/tmp')\n")
    offending = _boundary_violations("synthetic", tree)
    assert any("sys.path access" in item for item in offending)


def test_bypass_filesystem_loader_is_rejected() -> None:
    tree = ast.parse(
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('x', 'x.py')\n"
    )
    offending = _boundary_violations("synthetic", tree)
    assert any("spec_from_file_location" in item for item in offending)


def test_bypass_pythonpath_workaround_is_rejected() -> None:
    tree = ast.parse("value = 'PYTHONPATH=/tmp'\n")
    offending = _boundary_violations("synthetic", tree)
    assert any("PYTHONPATH workaround" in item for item in offending)


def test_bypass_from_import_loader_alias_laundering_is_rejected() -> None:
    tree = ast.parse(
        "from importlib import import_module as load\n"
        "load('workflow_scheduler._private')\n"
    )
    offending = _boundary_violations("synthetic", tree)
    assert any("import-machinery call 'load'" in item for item in offending)


def test_bypass_importlib_module_alias_laundering_is_rejected() -> None:
    tree = ast.parse(
        "import importlib as il\n"
        "il.import_module('workflow_scheduler._private')\n"
    )
    offending = _boundary_violations("synthetic", tree)
    assert any("import_module" in item for item in offending)


def test_bypass_reverse_import_as_member_is_rejected(tmp_path) -> None:
    module_path = tmp_path / "reverse_member.py"
    module_path.write_text(
        "from scripts import agent_os_candidate_packet\n", encoding="utf-8"
    )
    assert _imports_prefix(module_path, "scripts.agent_os_candidate_packet")


def test_bypass_reverse_import_as_module_is_rejected(tmp_path) -> None:
    module_path = tmp_path / "reverse_module.py"
    module_path.write_text(
        "import scripts.agent_os_candidate_packet\n", encoding="utf-8"
    )
    assert _imports_prefix(module_path, "scripts.agent_os_candidate_packet")


def test_bypass_assigned_loader_alias_is_rejected() -> None:
    """Newly closed (#915 correction): `load = importlib.import_module`."""
    tree = ast.parse(
        "import importlib\n"
        "load = importlib.import_module\n"
        "load('workflow_scheduler._private')\n"
    )
    offending = _boundary_violations("synthetic", tree)
    assert any("import-machinery call 'load'" in item for item in offending)


def test_bypass_chained_assigned_loader_alias_is_rejected() -> None:
    """A further `load2 = load` link must resolve too, in either order."""
    tree = ast.parse(
        "import importlib\n"
        "load = importlib.import_module\n"
        "load2 = load\n"
        "load2('workflow_scheduler._private')\n"
    )
    offending = _boundary_violations("synthetic", tree)
    assert any("import-machinery call 'load2'" in item for item in offending)


def test_bypass_private_importfrom_member_is_rejected() -> None:
    """Newly closed (#915 correction):
    `from workflow_scheduler.planning import _private`."""
    tree = ast.parse("from workflow_scheduler.planning import _private\n")
    offending = _boundary_violations("synthetic", tree)
    assert any(
        "private import path 'workflow_scheduler.planning._private'" in item
        for item in offending
    )


def test_bypass_annotated_assigned_loader_alias_is_rejected() -> None:
    """Newly closed (#915 correction): `load: object = importlib.import_module`."""
    tree = ast.parse(
        "import importlib\n"
        "load: object = importlib.import_module\n"
        "load('workflow_scheduler._private')\n"
    )
    offending = _boundary_violations("synthetic", tree)
    assert any("import-machinery call 'load'" in item for item in offending)


def test_ordinary_allowed_imports_still_pass() -> None:
    """The two corrections must not flag ordinary, permitted code."""
    tree = ast.parse(
        "from __future__ import annotations\n"
        "import json\n"
        "from pathlib import Path\n"
        "from workflow_scheduler.planning.draft_ingestion import (\n"
        "    DraftTaskProposal,\n"
        "    build_draft_task_proposals,\n"
        ")\n"
    )
    assert _boundary_violations("synthetic", tree) == []
    assert _loader_aliases(tree) == set()
