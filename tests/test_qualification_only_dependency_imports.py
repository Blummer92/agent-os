"""Regression guard for qualification-only test dependencies (#1554).

The #1554 property-based pilot imported Hypothesis at module scope without a
guard. Hypothesis is a qualification-only dependency — see
`08_Tooling/workflow-scheduler/docs/DEPENDENCY_READINESS.md` ("`hypothesis==6.165.9`
is a qualification-only exact pin ... and does not mutate `requirements-dev.txt`")
— so it is absent on the governed remote-validation host. The unguarded import
therefore raised at *collection* time, and a collection error is not a single
failing test: pytest reports `Interrupted: 1 error during collection` and exits
2, so the entire governed aggregate suite stopped before running any of its 421
collected tests.

That defect class is invisible to every test that only runs where the optional
dependency happens to be installed, which is exactly why it escaped the
developer loop. These checks are static, offline, and deterministic: they parse
module ASTs rather than importing anything, so they detect the defect on a host
that has the optional dependency present.

Two invariants are pinned:

1. every test module that imports a qualification-only distribution guards it
   with `pytest.importorskip(...)` *before* the first such import; and
2. no qualification-only distribution is adopted as a permanent entry in
   `requirements-dev.txt`.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_DEV = ROOT / "requirements-dev.txt"

# Distributions qualified task-scoped rather than adopted permanently. Keep this
# aligned with the qualification-only pins in DEPENDENCY_READINESS.md.
QUALIFICATION_ONLY_MODULES = frozenset({"hypothesis"})

# Directories that hold their own historical copies and are not executed.
EXCLUDED_PARTS = frozenset({"06_Archive", "node_modules", ".git", "__pycache__"})

_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _test_modules() -> list[Path]:
    modules = [
        path
        for path in ROOT.rglob("tests/**/*.py")
        if not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
    ]
    assert modules, "no test modules discovered; the scan itself has regressed"
    return sorted(modules)


def _root_module(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def _first_qualification_only_import(tree: ast.Module) -> tuple[str, int] | None:
    """Return the earliest qualification-only import as (module, line)."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root_module(alias.name)
                if root in QUALIFICATION_ONLY_MODULES:
                    found.append((root, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # `level > 0` is a relative import and can never name a distribution.
            if node.level:
                continue
            root = _root_module(node.module)
            if root in QUALIFICATION_ONLY_MODULES:
                found.append((root, node.lineno))
    return min(found, key=lambda item: item[1]) if found else None


def _guard_lines(tree: ast.Module) -> dict[str, int]:
    """Return the earliest module-level `pytest.importorskip` line per module."""
    guards: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        if not isinstance(func, ast.Attribute) or func.attr != "importorskip":
            continue
        if not isinstance(func.value, ast.Name) or func.value.id != "pytest":
            continue
        if not call.args:
            continue
        first = call.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        root = _root_module(first.value)
        guards.setdefault(root, node.lineno)
    return guards


def test_qualification_only_imports_are_guarded_before_use() -> None:
    """An unguarded optional import fails collection and stops the whole suite."""
    unguarded: list[str] = []
    for path in _test_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        first_import = _first_qualification_only_import(tree)
        if first_import is None:
            continue
        module, import_line = first_import
        guard_line = _guard_lines(tree).get(module)
        relative = path.relative_to(ROOT)
        if guard_line is None:
            unguarded.append(
                f"{relative}:{import_line} imports '{module}' with no "
                f"module-level pytest.importorskip('{module}') guard"
            )
        elif guard_line > import_line:
            unguarded.append(
                f"{relative}:{import_line} imports '{module}' before its guard "
                f"on line {guard_line}; the guard must precede the import"
            )
    assert unguarded == []


def test_at_least_one_module_exercises_the_guard_contract() -> None:
    """Guard the scan itself from silently matching nothing."""
    guarded = [
        path
        for path in _test_modules()
        if _first_qualification_only_import(
            ast.parse(path.read_text(encoding="utf-8"), str(path))
        )
        is not None
    ]
    assert guarded, "no module imports a qualification-only distribution"


def _declared_requirement_names(text: str) -> set[str]:
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        # `-e ./path` and other directives never name an index distribution.
        if not line or line.startswith("-"):
            continue
        match = _REQUIREMENT_NAME.match(line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def test_qualification_only_dependencies_are_not_permanently_adopted() -> None:
    """Adoption would change the content-addressed dependency-manifest identity."""
    declared = _declared_requirement_names(
        REQUIREMENTS_DEV.read_text(encoding="utf-8")
    )
    assert "pytest" in declared, "requirements parsing regressed"
    adopted = sorted(declared.intersection(QUALIFICATION_ONLY_MODULES))
    assert adopted == []
