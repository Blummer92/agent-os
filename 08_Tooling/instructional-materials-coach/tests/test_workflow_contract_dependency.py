"""Packaging boundary checks for the Instructional Materials Coach dependency."""
from __future__ import annotations

import ast
from pathlib import Path

from instructional_workflow_contracts.reuse_planner import plan_instructional_artifact_reuse


def test_real_reuse_planner_is_importable() -> None:
    assert callable(plan_instructional_artifact_reuse)
    assert plan_instructional_artifact_reuse.__module__ == "instructional_workflow_contracts.reuse_planner"


def test_contracts_do_not_import_instructional_materials_coach() -> None:
    contracts = Path(__file__).parents[3] / "src" / "instructional_workflow_contracts"
    for path in contracts.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("instructional_materials_coach") for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("instructional_materials_coach")
