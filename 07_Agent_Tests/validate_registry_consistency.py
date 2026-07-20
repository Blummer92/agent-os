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
ROUTING_PLACEHOLDERS = {
    "Relevant registered owner",
    "Selected owner",
    "package owner",
    "GitHub Service Agent or system owner",
    "target owner",
    "Integration Manager when cross-system",
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


def section_text(text: str, heading: str) -> str:
    marker = f"## {heading}"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != marker:
            continue
        body: list[str] = []
        for section_line in lines[index + 1 :]:
            if section_line.startswith("## "):
                break
            body.append(section_line)
        return "\n".join(body).strip()
    return ""


def normalized(text: str) -> str:
    return " ".join(text.split())


def split_people(value: str) -> list[str]:
    parts = re.split(r"\s*;\s*|\s*->\s*", value)
    return [part.strip() for part in parts if part.strip()]


def read_required(path: Path, label: str, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"Required governance file is missing: {label}")
        return ""
    return path.read_text(encoding="utf-8")


def validate_routing_documents(
    root: Path,
    agents: set[str],
    overlay_slugs: set[str],
    errors: list[str],
) -> None:
    loadout_text = read_required(
        root / "04_Registry/agent-loadout-matrix.md",
        "Agent Loadout Matrix",
        errors,
    )
    routing_text = read_required(
        root / "04_Registry/task-routing-guide.md",
        "Task Routing Guide",
        errors,
    )
    if not loadout_text or not routing_text:
        return

    loadout_rows = table_rows(
        loadout_text,
        (
            "Agent",
            "Overlay",
            "Additional inherited standards",
            "Default tier/write mode",
            "Primary work",
            "Evidence and escalation",
        ),
        "## Governed Routing Overlays",
    )
    if not loadout_rows:
        errors.append("Agent Loadout Matrix table is missing or empty")
    loadout_agents: list[str] = []
    for row in loadout_rows:
        if len(row) != 6 or not all(row):
            errors.append("Agent Loadout Matrix contains a malformed or empty row")
            continue
        agent, overlay, _, _, _, _ = row
        loadout_agents.append(agent)
        if agent not in agents:
            errors.append(f"Unknown loadout agent: {agent}")
        slug = overlay.strip("`")
        if slug not in overlay_slugs:
            errors.append(f"Unknown loadout overlay: {agent} -> {slug}")

    for agent in sorted(agents):
        count = loadout_agents.count(agent)
        if count == 0:
            errors.append(f"Canonical agent has no loadout entry: {agent}")
        elif count > 1:
            errors.append(f"Canonical agent has duplicate loadout entries: {agent}")

    routing_rows = table_rows(
        routing_text,
        (
            "Workflow",
            "Primary role",
            "Support or overlay",
            "Tier and intake",
            "Source and destination",
            "Stop or escalate when",
        ),
    )
    if not routing_rows:
        errors.append("Task Routing Guide table is missing or empty")
    for row in routing_rows:
        if len(row) != 6 or not all(row):
            errors.append("Task Routing Guide contains a malformed or empty row")
            continue
        workflow, primary, support, tier_intake, source, stop = row
        if primary not in agents and primary not in ROUTING_PLACEHOLDERS:
            errors.append(f"Unknown routing primary role: {workflow} -> {primary}")
        for value in split_people(support):
            if (
                value not in agents
                and value not in SUPPORT_SURFACES
                and value not in ROUTING_PLACEHOLDERS
            ):
                errors.append(f"Unknown routing support value: {workflow} -> {value}")

        tier_lower = tier_intake.lower()
        workflow_lower = workflow.lower()
        if "tier 2" in tier_lower and "lightweight" in tier_lower:
            errors.append(f"Tier 2 route cannot use Lightweight Intake: {workflow}")
        if "tier 3" in tier_lower and "lightweight" in tier_lower:
            errors.append(f"Tier 3 route cannot use Lightweight Intake: {workflow}")

        explicitly_governed = (
            "governed" in workflow_lower
            or "workspace implementation" in workflow_lower
            or "google workspace automation" in workflow_lower
            or "standards, overlay, governance, or registry change" in workflow_lower
        )
        if explicitly_governed and (
            "full" not in tier_lower or "live readiness" not in tier_lower
        ):
            errors.append(
                f"Governed route must require Full Intake and Live Readiness: {workflow}"
            )

        if workflow_lower == "ambiguous write request":
            combined = normalized(f"{tier_intake} {source} {stop}").lower()
            fail_closed = normalized(section_text(routing_text, "Fail-Closed Rules")).lower()
            if "manual review" not in combined or "human decision" not in fail_closed:
                errors.append("Ambiguous write request must route to human decision")

    routing_sequence = normalized(section_text(routing_text, "Routing Sequence")).lower()
    required_sequence = (
        "full intake",
        "live readiness",
        "tier 2",
        "tier 3",
        "external-write",
        "irreversible",
    )
    if any(value not in routing_sequence for value in required_sequence):
        errors.append(
            "Task Routing Guide must require Full Intake and Live Readiness for governed work"
        )


def validate_write_boundaries(
    root: Path,
    overlays: Path,
    valid_matrix_rows: list[list[str]],
    errors: list[str],
) -> None:
    agents_text = read_required(root / "AGENTS.md", "AGENTS.md", errors)
    write_policy_text = read_required(
        root / "00_Governance/write-authorization-policy.md",
        "Write Authorization Policy",
        errors,
    )
    github_text = read_required(
        overlays / "github-service-agent.md",
        "GitHub Service Agent overlay",
        errors,
    )
    integration_text = read_required(
        overlays / "integration-manager.md",
        "Integration Manager overlay",
        errors,
    )
    navigation_text = read_required(
        root / "01_Shared_Standards/navigation/navigation-registry-standard.md",
        "Navigation Registry Standard",
        errors,
    )
    protected_text = read_required(
        root / "01_Shared_Standards/github/protected-branch-governance.md",
        "Protected Branch Governance Standard",
        errors,
    )

    github_rows = [row for row in valid_matrix_rows if row[0] == "GitHub repository writes"]
    if len(github_rows) != 1 or github_rows[0][1] != "GitHub Service Agent":
        errors.append("GitHub repository write owner must be GitHub Service Agent")

    access_rules = normalized(section_text(agents_text, "Access Rules"))
    sole_writer_rule = "Only the GitHub Service Agent may write to GitHub"
    if sole_writer_rule not in access_rules:
        errors.append("AGENTS access rules must name GitHub Service Agent as the sole GitHub writer")
    for sentence in re.split(r"(?<=[.!?])\s+", access_rules):
        if "may write to GitHub" in sentence and sole_writer_rule not in sentence:
            errors.append("AGENTS access rules contain a conflicting GitHub write authorization")

    canonical_role = normalized(section_text(github_text, "Canonical Role"))
    if "Sole GitHub write owner" not in canonical_role:
        errors.append("GitHub Service Agent must retain the sole GitHub write-owner role")
    inherited = section_text(github_text, "Inherited Standards")
    protected_path = "01_Shared_Standards/github/protected-branch-governance.md"
    if protected_path not in inherited:
        errors.append("GitHub Service Agent must inherit Protected Branch Governance")
    if "00_Governance/write-authorization-policy.md" not in inherited:
        errors.append("GitHub Service Agent must inherit the Write Authorization Policy")

    normal_change = normalized(section_text(protected_text, "Normal Change Path"))
    if "non-protected branch" not in normal_change or "pull request" not in normal_change:
        errors.append("Protected Branch Governance must require a non-protected branch and pull request")

    non_authoritative = normalized(section_text(navigation_text, "Non-Authoritative Rule"))
    if "lookup aid only" not in non_authoritative or "Cached records do not authorize" not in non_authoritative:
        errors.append("Navigation Registry must remain explicitly non-authoritative")
    write_boundary = normalized(section_text(navigation_text, "Write Boundary"))
    if "may not treat a registry result as permission to write" not in write_boundary:
        errors.append("Navigation Registry results must not grant write permission")
    navigation_lower = normalized(navigation_text).lower()
    conflicting_navigation_grants = (
        "cached records authorize writes",
        "cached records may authorize writes",
        "registry result grants permission to write",
        "registry results grant permission to write",
    )
    if any(phrase in navigation_lower for phrase in conflicting_navigation_grants):
        errors.append("Navigation Registry standard contains a conflicting write authorization")

    owned_systems = normalized(section_text(integration_text, "Owned Systems"))
    if "cross-system navigation governance" not in owned_systems:
        errors.append("Integration Manager must retain cross-system navigation governance")
    blocked_writes = normalized(section_text(integration_text, "Blocked Write Surfaces"))
    if "direct github writes outside the github service agent handoff" not in blocked_writes.lower():
        errors.append("Integration Manager must block direct GitHub writes outside the GitHub Service Agent handoff")
    allowed_writes = normalized(section_text(integration_text, "Allowed Write Surfaces"))
    if re.search(r"\b(?:direct )?GitHub writes?\b|\bwrite to GitHub\b", allowed_writes, re.IGNORECASE):
        errors.append("Integration Manager must not have direct GitHub write authority")

    if write_policy_text and "Confirm target, system of record, field ownership, and authorization before any write" not in normalized(write_policy_text):
        errors.append("Write Authorization Policy must require target, ownership, and authorization confirmation")


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

    validate_routing_documents(root, agents, overlay_slugs, errors)
    validate_write_boundaries(root, overlays, valid_matrix_rows, errors)
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
