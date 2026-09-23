"""Unit tests for bounded static path/interface inspection (#494 / #254)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reusable_capability_registry import inspection as insp
from reusable_capability_registry.models import EvidenceConfidence, ValidationSeverity


def _root(tmp_path: Path) -> Path:
    return insp.resolve_repository_root(tmp_path)


def _write(root: Path, rel: str, content: str = "x = 1\n") -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# --- canonical path inspection ---------------------------------------------


def test_valid_canonical_path_has_no_finding(tmp_path):
    root = _root(tmp_path)
    _write(root, "src/pkg/mod.py")
    assert insp.inspect_canonical_path(root, "src/pkg/mod.py").code is None


@pytest.mark.parametrize(
    "registered,code",
    [
        ("", "path.invalid-format"),
        ("/abs/mod.py", "path.invalid-format"),
        ("C:/win.py", "path.invalid-format"),
        ("a\\b.py", "path.invalid-format"),
        ("../escape.py", "path.traversal"),
        ("does/not/exist.py", "path.missing"),
    ],
)
def test_lexical_and_missing_path_codes(tmp_path, registered, code):
    root = _root(tmp_path)
    assert insp.inspect_canonical_path(root, registered).code == code


def test_noncanonical_path_warns(tmp_path):
    root = _root(tmp_path)
    _write(root, "src/mod.py")
    outcome = insp.inspect_canonical_path(root, "./src/mod.py")
    assert outcome.code == "path.noncanonical"
    assert outcome.severity is ValidationSeverity.WARN
    assert outcome.confidence is EvidenceConfidence.PROBABLE


def test_case_variant_fails_closed(tmp_path):
    # On a case-sensitive filesystem a differently-cased path is genuinely missing;
    # on a case-insensitive one it is a case-mismatch. Either way it fails closed.
    root = _root(tmp_path)
    _write(root, "src/Mod.py")
    outcome = insp.inspect_canonical_path(root, "src/mod.py")
    assert outcome.code in ("path.case-mismatch", "path.missing")
    assert outcome.severity is ValidationSeverity.FAIL


def test_exact_case_target_rejects_mismatched_component(tmp_path):
    root = _root(tmp_path)
    _write(root, "src/Mod.py")
    assert insp._exact_case_target(root, ("src", "mod.py")) is None
    assert insp._exact_case_target(root, ("src", "Mod.py")) == root / "src" / "Mod.py"


def test_symlink_inside_is_manual_review(tmp_path):
    root = _root(tmp_path)
    _write(root, "src/real.py")
    (root / "src" / "link.py").symlink_to(root / "src" / "real.py")
    outcome = insp.inspect_canonical_path(root, "src/link.py")
    assert outcome.code == "path.symlink-inside"
    assert outcome.severity is ValidationSeverity.MANUAL_REVIEW


def test_symlink_outside_fails(tmp_path):
    root = _root(tmp_path)
    outside = tmp_path.parent / "outside_target.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    (root / "escape.py").symlink_to(outside)
    assert insp.inspect_canonical_path(root, "escape.py").code == "path.symlink-outside"


def test_path_through_symlinked_dir_is_outside_repository(tmp_path):
    root = _root(tmp_path)
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "file.py").write_text("x = 1\n", encoding="utf-8")
    (root / "link").symlink_to(outside_dir, target_is_directory=True)
    assert insp.inspect_canonical_path(root, "link/file.py").code == "path.outside-repository"


# --- interface inspection --------------------------------------------------


def _interface(tmp_path, source: str, canonical=("src/pkg/mod.py",), interface="src.pkg.mod:run"):
    root = _root(tmp_path)
    for path in canonical:
        _write(root, path, source)
    return insp.inspect_python_interface(root, interface, canonical)


@pytest.mark.parametrize("source", ["def run():\n    return 1\n", "async def run():\n    return 1\n", "class run:\n    pass\n"])
def test_definition_bindings_verify(tmp_path, source):
    assert _interface(tmp_path, source).code is None


def test_import_and_alias_bindings_verify(tmp_path):
    assert _interface(tmp_path, "from other import run\n").code is None
    assert _interface(tmp_path, "from other import thing as run\n").code is None


def test_all_plus_binding_verifies(tmp_path):
    assert _interface(tmp_path, "__all__ = ['run']\n\ndef run():\n    pass\n").code is None


@pytest.mark.parametrize(
    "interface,code",
    [
        ("no-colon", "interface.malformed"),
        ("mod:", "interface.malformed"),
        (":sym", "interface.malformed"),
        ("mod:Class.method", "interface.nested-symbol"),
    ],
)
def test_malformed_and_nested_interface(tmp_path, interface, code):
    root = _root(tmp_path)
    _write(root, "src/pkg/mod.py", "def run():\n    pass\n")
    assert insp.inspect_python_interface(root, interface, ("src/pkg/mod.py",)).code == code


def test_module_missing_and_ambiguous(tmp_path):
    root = _root(tmp_path)
    _write(root, "src/pkg/mod.py", "def run():\n    pass\n")
    assert insp.inspect_python_interface(root, "no.such:run", ("src/pkg/mod.py",)).code == "interface.module-missing"
    _write(root, "a/pkg/mod.py", "def run():\n    pass\n")
    _write(root, "b/pkg/mod.py", "def run():\n    pass\n")
    outcome = insp.inspect_python_interface(root, "pkg.mod:run", ("a/pkg/mod.py", "b/pkg/mod.py"))
    assert outcome.code == "interface.module-ambiguous"


def test_symbol_missing_and_syntax_error(tmp_path):
    assert _interface(tmp_path, "def other():\n    pass\n").code == "interface.symbol-missing"
    assert _interface(tmp_path, "def run(:\n").code == "interface.syntax-error"


def test_star_and_dynamic_and_conditional_route_to_manual_review(tmp_path):
    assert _interface(tmp_path, "from other import *\n").code == "interface.dynamic-export"
    assert _interface(tmp_path, "def __getattr__(name):\n    return None\n").code == "interface.dynamic-export"
    assert _interface(tmp_path, "import typing\nif typing.TYPE_CHECKING:\n    from other import run\n").code == "interface.conditional-binding"


def test_deleted_symbol_conflicts(tmp_path):
    assert _interface(tmp_path, "def run():\n    pass\n\ndel run\n").code == "interface.conflicting-binding"


def test_non_python_interface(tmp_path):
    root = _root(tmp_path)
    _write(root, "config/settings.yaml", "a: 1\n")
    outcome = insp.inspect_python_interface(root, "config.settings:value", ("config/settings.yaml",))
    assert outcome.code == "interface.non-python"


def test_init_reexport_from_unregistered_source(tmp_path):
    root = _root(tmp_path)
    _write(root, "pkg/__init__.py", "from .hidden import run\n")
    _write(root, "pkg/hidden.py", "def run():\n    pass\n")
    outcome = insp.inspect_python_interface(root, "pkg:run", ("pkg/__init__.py",))
    assert outcome.code == "interface.local-source-unregistered"


def test_init_reexport_from_registered_source_verifies(tmp_path):
    root = _root(tmp_path)
    _write(root, "pkg/__init__.py", "from .core import run\n")
    _write(root, "pkg/core.py", "def run():\n    pass\n")
    outcome = insp.inspect_python_interface(root, "pkg:run", ("pkg/__init__.py", "pkg/core.py"))
    assert outcome.code is None


# --- path classification ---------------------------------------------------


@pytest.mark.parametrize(
    "rel,category",
    [
        ("src/pkg/mod.py", "operational"),
        ("scripts/tool.py", "operational"),
        ("tests/test_x.py", "test"),
        ("src/test_x.py", "test"),
        ("pkg/fixtures/data.py", "excluded"),
        ("examples/demo.py", "informational"),
        ("docs/readme.md", "excluded"),
    ],
)
def test_classify_repository_path(rel, category):
    assert insp.classify_repository_path(rel) == category
