#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "04_Registry/agent-inheritance-registry.md"
MATRIX = ROOT / "04_Registry/responsibility-matrix.md"
OVERLAYS = ROOT / "02_Agent_Overlays"
TESTS = ROOT / "07_Agent_Tests"
HELPER_OVERLAYS = {
    "apps-script-sync-test-overlay",
    "dashboard-builder-overlay",
    "python-development-overlay",
    "workspace-implementation-overlay",
}
SUPPORT_SURFACES = {
    "Apps Script Sync Test Overlay",
    "Dashboard Builder Overlay",
    "GitHub Change Request",
    "Instructional Design Standards",
    "Navigation Registry Standard",
    "Python Development Overlay",
    "Workspace Implementation Overlay",
    "selected registered owner",
}
PATH_RE = re.compile(r"`((?:00_Governance|01_Shared_Standards|04_Registry)/[^`]+)`")


def table_rows(text: str, heading: str | None = None) -> list[list[str]]:
    if heading:
        text = text.split(heading, 1)[0]
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(cells)
    return rows[1:] if rows else []


def split_people(value: str) -> list[str]:
    parts = re.split(r"\s*;\s*|\s*->\s*", value)
    return [part.strip() for part in parts if part.strip()]


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    registry = root / "04_Registry/agent-inheritance-registry.md"
    matrix = root / "04_Registry/responsibility-matrix.md"
    overlays = root / "02_Agent_Overlays"
    tests = root / "07_Agent_Tests"
    if not registry.is_file() or not matrix.is_file():
        return ["Registry or Responsibility Matrix is missing"]

    registry_rows = table_rows(registry.read_text(), "## Routed Combinations")
    agents = {row[0] for row in registry_rows if len(row) >= 3}
    overlay_slugs = {row[2].strip("`") for row in registry_rows if len(row) >= 3}

    for slug in sorted(overlay_slugs):
        if not (overlays / f"{slug}.md").is_file():
            errors.append(f"Registered agent has no overlay: {slug}")
        if not (tests / f"{slug}.tests.md").is_file():
            errors.append(f"Registered agent has no test file: {slug}")

    for overlay in sorted(overlays.glob("*.md")):
        slug = overlay.stem
        if slug in {"README", "_common-overlay-rules"}:
            continue
        if slug not in overlay_slugs and slug not in HELPER_OVERLAYS:
            errors.append(f"Overlay is not registered or exempt: {slug}")
        for path in PATH_RE.findall(overlay.read_text()):
            if not (root / path).exists():
                errors.append(f"Overlay references missing path: {slug} -> {path}")

    matrix_rows = table_rows(matrix.read_text())
    for row in matrix_rows:
        if len(row) < 3:
            continue
        responsibility, primary, support = row[:3]
        for name in split_people(primary):
            if name not in agents:
                errors.append(f"Unknown primary agent: {responsibility} -> {name}")
        for name in split_people(support):
            if name not in agents and name not in SUPPORT_SURFACES:
                errors.append(f"Unknown support value: {responsibility} -> {name}")

    nav_rows = [row for row in matrix_rows if row and row[0].startswith("Navigation Registry governance")]
    if len(nav_rows) != 1 or len(nav_rows[0]) < 2 or nav_rows[0][1] != "Integration Manager":
        errors.append("Navigation Registry primary owner must be Integration Manager")
    integration = overlays / "integration-manager.md"
    if not integration.is_file() or "navigation-registry-standard.md" not in integration.read_text():
        errors.append("Integration Manager must inherit the Navigation Registry standard")
    return sorted(set(errors))


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"FAIL - {error}")
        return 1
    print("PASS - Registry consistency audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
