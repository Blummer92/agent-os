"""Deterministic guard against duplicate authored top-level Python declarations."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", "vendor", "generated"}


@dataclass(frozen=True, slots=True)
class DuplicateDeclaration:
    path: str
    symbol: str
    lines: tuple[int, ...]


def find_duplicate_top_level_declarations(path: Path) -> tuple[DuplicateDeclaration, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    declarations: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        declarations.setdefault(node.name, []).append(node)

    duplicates: list[DuplicateDeclaration] = []
    for name, nodes in declarations.items():
        if len(nodes) < 2 or _is_overload_group(nodes):
            continue
        duplicates.append(
            DuplicateDeclaration(str(path), name, tuple(node.lineno for node in nodes))
        )
    return tuple(sorted(duplicates, key=lambda item: (item.path, item.symbol, item.lines)))


def scan_authored_python(root: Path) -> tuple[DuplicateDeclaration, ...]:
    duplicates: list[DuplicateDeclaration] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in _SKIP_PARTS for part in relative.parts):
            continue
        duplicates.extend(find_duplicate_top_level_declarations(path))
    return tuple(duplicates)


def format_duplicates(items: Iterable[DuplicateDeclaration]) -> str:
    return "\n".join(
        f"{item.path}: duplicate top-level {item.symbol!r} at lines "
        + ",".join(str(line) for line in item.lines)
        for item in items
    )


def _is_overload_group(nodes: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]) -> bool:
    if any(isinstance(node, ast.ClassDef) for node in nodes):
        return False
    return all(_has_overload_decorator(node) for node in nodes[:-1]) and not _has_overload_decorator(nodes[-1])


def _has_overload_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "overload":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "overload":
            return True
    return False
