#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER_OVERLAYS = {
    "apps-script-sync-test-overlay",
    "dashboard-builder-overlay",
    "python-development-overlay",
    "workspace-implementation-overlay",
}
SUPPORT_SURFACES = {
    "Apps Script Sync Test Overlay",
    "Dashboard Builder Overlay",
    "Python Development Overlay",
    "Workspace Implementation Overlay",
}
PATH_RE = re.compile(r"`((?:00_Governance|01_Shared_Standards|04_Registry)/[^`]+)`")


def table_rows(
    text: str,
    headers: tuple[str, ...],
    stop_heading: str | None = None,
) -> list[list[str]]:
    if stop_heading:
        text = text.split(stop_heading, 1)[0]
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if tuple(cells) != headers:
            continue
        rows: list[list[str]] = []
        for row_line in lines[index + 2 :]:
            if not row_line.lstrip().startswith("|"):
                break
            rows.append([cell.strip() for cell in row_line.strip().strip("|").split("|")])
        return rows
    return []


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

    registry_rows = table_rows(
        registry.read_text(encoding="utf-8"),
        ("Agent", "Inherits", "Overlay"),
        "## Routed Combinations",
    )
    if not registry_rows:
        errors.append("Agent Inheritance Registry table is missing or empty")

    agents: set[str] = set()
    overlay_slugs: set[str] = set()
    for row in registry_rows:
        if len(row) != 3 or not all(row):
            errors.append("Agent Inheritance Registry contains a malformed row")
            continue
        agent, _, overlay = row
        agents.add(agent)
        overlay_slugs.add(overlay.strip("`"))

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
        for path in PATH_RE.findall(overlay.read_text(encoding="utf-8")):
            if not (root / path).exists():
                errors.append(f"Overlay references missing path: {slug} -> {path}")

    matrix_rows = table_rows(
        matrix.read_text(encoding="utf-8"),
        ("Responsibility", "Primary", "Support"),
    )
    if not matrix_rows:
        errors.append("Responsibility Matrix table is missing or empty")

    valid_matrix_rows: list[list[str]] = []
    assigned_agents: set[str] = set()
    for row in matrix_rows:
        if len(row) != 3 or not all(row):
            errors.append("Responsibility Matrix contains a malformed or empty row")
            continue
        valid_matrix_rows.append(row)
        responsibility, primary, support = row
        for name in split_people(primary):
            if name in agents:
                assigned_agents.add(name)
            else:
                errors.append(f"Unknown primary agent: {responsibility} -> {name}")
        for name in split_people(support):
            if name in agents:
                assigned_agents.add(name)
            elif name not in SUPPORT_SURFACES:
                errors.append(f"Unknown support value: {responsibility} -> {name}")

    for agent in sorted(agents - assigned_agents):
        errors.append(f"Canonical agent has no Responsibility Matrix assignment: {agent}")

    nav_rows = [row for row in valid_matrix_rows if "Navigation Registry" in row[0]]
    if len(nav_rows) != 1 or nav_rows[0][1] != "Integration Manager":
        errors.append("Navigation Registry primary owner must be Integration Manager")
    integration = overlays / "integration-manager.md"
    if not integration.is_file() or "navigation-registry-standard.md" not in integration.read_text(encoding="utf-8"):
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
