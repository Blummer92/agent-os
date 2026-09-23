#!/usr/bin/env python3
"""Shared helpers for dashboard migration verification tooling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TOOL_ROOT = Path(__file__).resolve().parents[1]

DESTRUCTIVE_ACTIONS = {
    "archive_view",
    "archive_database",
    "merge_database",
    "dependency_cleanup",
}

REPORT_SECTIONS = [
    "## 1. Executive Summary",
    "## 2. Migration Readiness Table",
    "## 3. Data Integrity Review",
    "## 4. Dependency Review",
    "## 5. Migration Tasks",
    "## 6. Retirement Order",
    "## 7. Items That Must Not Be Retired",
    "## 8. Final Decision",
]


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_changes(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return parse_simple_yaml(text)


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the intentionally small manifest shape used by the examples.

    This is not a general YAML parser. It avoids a hard dependency for the fixture
    tests while keeping the scripts runnable in minimal environments.
    """
    payload: dict[str, Any] = {"changes": []}
    current: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "changes:":
            continue
        if stripped.startswith("version:"):
            payload["version"] = int(stripped.split(":", 1)[1].strip())
            continue
        if stripped.startswith("- "):
            if current is not None:
                payload["changes"].append(current)
            current = {}
            key, value = split_key_value(stripped[2:])
            current[key] = coerce_scalar(value)
            continue
        if current is not None and ":" in stripped:
            key, value = split_key_value(stripped)
            current[key] = coerce_scalar(value)

    if current is not None:
        payload["changes"].append(current)
    return payload


def split_key_value(text: str) -> tuple[str, str]:
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def coerce_scalar(value: str) -> Any:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "none"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def change_id(change: dict[str, Any]) -> str:
    parts = [
        change.get("action", "unknown"),
        change.get("source_database", "unknown_source"),
        change.get("source_item", "unknown_item"),
    ]
    return "::".join(str(part).replace(" ", "_") for part in parts)


def migration_status_for_action(action: str) -> str:
    mapping = {
        "rename_field": "Requires Field Migration",
        "merge_field": "Requires Field Migration",
        "archive_view": "Requires View Migration",
        "archive_database": "Requires Record Migration",
        "merge_database": "Requires Record Migration",
        "rename_status_value": "Requires Field Migration",
        "normalize_status_vocabulary": "Requires Field Migration",
        "update_linked_view": "Requires View Migration",
        "update_formula_dependency": "Requires Dependency Cleanup",
        "dependency_cleanup": "Requires Dependency Cleanup",
    }
    return mapping.get(action, "Requires Manual Review")
