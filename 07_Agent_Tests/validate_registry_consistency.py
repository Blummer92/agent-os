#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED_TECHNICAL_AGENTS = {
    "Integration Manager",
    "Google Workspace Automation Engineer",
}

HELPER_OVERLAYS = {
    "apps-script-sync-test-overlay",
    "chatgpt-orchestrator-request-interpretation",
    "dashboard-builder-overlay",
    "python-development-overlay",
    "workspace-implementation-overlay",
    # Retired canonical-agent files remain compatibility guidance only.
    "integration-manager",
    "google-workspace-automation-engineer",
}

SUPPORT_SURFACES = {
    "Apps Script Sync Test Overlay",
    "Dashboard Builder Overlay",
    "Python Development Overlay",
    "Workspace Implementation Overlay",
    "Python Standards",
    "Google Workspace Standards",
    "Navigation Registry Standard",
    "Reusable Capability Registry Standard",
    "Source-of-Truth Checks",
}

ROUTING_PLACEHOLDERS = {
    "Relevant registered owner",
    "Selected owner",
    "target owner",
}

PATH_RE = re.compile(r"`((?:00_Governance|01_Shared_Standards|04_Registry)/[^`]+)`")


def table_rows(text: str, headers: tuple[str, ...], stop_heading: str | None = None) -> list[list[str]]:
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


def validate_legacy_aliases(root: Path, agents: set[str], errors: list[str]) -> None:
    alias_text = read_required(
        root / "04_Registry/legacy-agent-alias-registry.md",
        "Legacy Agent Alias Registry",
        errors,
    )
    if not alias_text:
        return
    rows = table_rows(
        alias_text,
        ("Legacy Name / Property", "Canonical Agent", "Current Overlay", "Status", "Notes"),
        "## Ambiguous Legacy Values",
    )
    aliases = {row[0]: row[1] for row in rows if len(row) == 5}
    required = {
        "Integration Manager": "ChatGPT Orchestrator",
        "Google Workspace Automation Engineer": "GitHub Service Agent",
        "Python Development Overlay": "GitHub Service Agent",
    }
    for legacy, expected in required.items():
        if aliases.get(legacy) != expected:
            errors.append(f"Retired legacy alias must resolve to retained canonical agent: {legacy} -> {expected}")
    for legacy, canonical in aliases.items():
        if canonical not in agents:
            errors.append(f"Legacy alias resolves to non-canonical agent: {legacy} -> {canonical}")


def validate_routing_documents(root: Path, agents: set[str], overlay_slugs: set[str], errors: list[str]) -> None:
    loadout_text = read_required(root / "04_Registry/agent-loadout-matrix.md", "Agent Loadout Matrix", errors)
    routing_text = read_required(root / "04_Registry/task-routing-guide.md", "Task Routing Guide", errors)
    if not loadout_text or not routing_text:
        return

    loadout_rows = table_rows(
        loadout_text,
        ("Agent", "Overlay", "Additional inherited standards", "Default tier/write mode", "Primary work", "Evidence and escalation"),
        "## Governed Routing Overlays",
    )
    loadout_agents: list[str] = []
    for row in loadout_rows:
        if len(row) != 6 or not all(row):
            errors.append("Agent Loadout Matrix contains a malformed or empty row")
            continue
        agent, overlay, *_ = row
        loadout_agents.append(agent)
        if agent not in agents:
            errors.append(f"Unknown loadout agent: {agent}")
        if agent in RETIRED_TECHNICAL_AGENTS:
            errors.append(f"Retired technical agent remains executable in loadout: {agent}")
        if overlay.strip("`") not in overlay_slugs:
            errors.append(f"Unknown loadout overlay: {agent} -> {overlay.strip('`')}")
    for agent in sorted(agents):
        count = loadout_agents.count(agent)
        if count == 0:
            errors.append(f"Canonical agent has no loadout entry: {agent}")
        elif count > 1:
            errors.append(f"Canonical agent has duplicate loadout entries: {agent}")

    routing_rows = table_rows(
        routing_text,
        ("Workflow", "Primary role", "Support or overlay", "Tier and intake", "Source and destination", "Stop or escalate when"),
    )
    for row in routing_rows:
        if len(row) != 6 or not all(row):
            errors.append("Task Routing Guide contains a malformed or empty row")
            continue
        workflow, primary, support, tier_intake, source, stop = row
        if primary in RETIRED_TECHNICAL_AGENTS:
            errors.append(f"Retired technical agent remains routing primary: {workflow} -> {primary}")
        if primary not in agents and primary not in ROUTING_PLACEHOLDERS:
            errors.append(f"Unknown routing primary role: {workflow} -> {primary}")
        for value in split_people(support):
            if value in RETIRED_TECHNICAL_AGENTS:
                errors.append(f"Retired technical agent remains routing support: {workflow} -> {value}")
            elif value not in agents and value not in SUPPORT_SURFACES and value not in ROUTING_PLACEHOLDERS:
                errors.append(f"Unknown routing support value: {workflow} -> {value}")

        tier_lower = tier_intake.lower()
        if ("tier 2" in tier_lower or "tier 3" in tier_lower) and "lightweight" in tier_lower:
            errors.append(f"Tier 2/3 route cannot use Lightweight Intake: {workflow}")
        governed = any(term in workflow.lower() for term in (
            "governed", "workspace repository implementation", "google workspace automation",
            "apps script repository implementation", "standards, overlay, governance, or registry change",
        ))
        if governed and ("full" not in tier_lower or "live readiness" not in tier_lower):
            errors.append(f"Governed route must require Full Intake and Live Readiness: {workflow}")
        if workflow.lower() == "ambiguous write request":
            combined = normalized(f"{tier_intake} {source} {stop}").lower()
            fail_closed = normalized(section_text(routing_text, "Fail-Closed Rules")).lower()
            if "manual review" not in combined or "human decision" not in fail_closed:
                errors.append("Ambiguous write request must route to human decision")

    sequence = normalized(section_text(routing_text, "Routing Sequence")).lower()
    for required in ("full intake", "live readiness", "tier 2", "tier 3", "external-write", "irreversible"):
        if required not in sequence:
            errors.append("Task Routing Guide must require Full Intake and Live Readiness for governed work")
            break


def validate_write_boundaries(root: Path, overlays: Path, matrix_rows: list[list[str]], errors: list[str]) -> None:
    agents_text = read_required(root / "AGENTS.md", "AGENTS.md", errors)
    write_policy = read_required(root / "00_Governance/write-authorization-policy.md", "Write Authorization Policy", errors)
    github_text = read_required(overlays / "github-service-agent.md", "GitHub Service Agent overlay", errors)
    orchestrator_text = read_required(overlays / "chatgpt-orchestrator.md", "ChatGPT Orchestrator overlay", errors)
    navigation_text = read_required(root / "01_Shared_Standards/navigation/navigation-registry-standard.md", "Navigation Registry Standard", errors)
    workspace_write = read_required(root / "01_Shared_Standards/google-workspace/workspace-write-authorization.md", "Workspace Write Authorization", errors)
    protected_text = read_required(root / "01_Shared_Standards/github/protected-branch-governance.md", "Protected Branch Governance Standard", errors)

    github_rows = [row for row in matrix_rows if row[0] == "GitHub repository writes"]
    if len(github_rows) != 1 or github_rows[0][1] != "GitHub Service Agent":
        errors.append("GitHub repository write owner must be GitHub Service Agent")
    implementation_rows = [row for row in matrix_rows if row[0].startswith("Repository implementation")]
    if len(implementation_rows) != 1 or implementation_rows[0][1] != "GitHub Service Agent":
        errors.append("Ordinary repository implementation owner must be GitHub Service Agent")

    access_rules = normalized(section_text(agents_text, "Access Rules"))
    sole_writer = "Only the GitHub Service Agent may write to GitHub"
    if sole_writer not in access_rules:
        errors.append("AGENTS access rules must name GitHub Service Agent as the sole GitHub writer")

    role = normalized(section_text(github_text, "Canonical Role"))
    if "Sole GitHub write owner" not in role or "sole ordinary repository implementation owner" not in role:
        errors.append("GitHub Service Agent must retain sole GitHub write and repository implementation ownership")
    inherited = section_text(github_text, "Inherited Standards")
    if "01_Shared_Standards/github/protected-branch-governance.md" not in inherited:
        errors.append("GitHub Service Agent must inherit Protected Branch Governance")
    if "00_Governance/write-authorization-policy.md" not in inherited:
        errors.append("GitHub Service Agent must inherit the Write Authorization Policy")

    blocked = normalized(section_text(orchestrator_text, "Blocked Write Surfaces")).lower()
    if "github repository writes" not in blocked:
        errors.append("ChatGPT Orchestrator must not gain direct GitHub repository write authority")

    normal_change = normalized(section_text(protected_text, "Normal Change Path"))
    if "non-protected branch" not in normal_change or "pull request" not in normal_change:
        errors.append("Protected Branch Governance must require a non-protected branch and pull request")

    non_authoritative = normalized(section_text(navigation_text, "Non-Authoritative Rule"))
    if "lookup aid only" not in non_authoritative or "Cached records do not authorize" not in non_authoritative:
        errors.append("Navigation Registry must remain explicitly non-authoritative")
    if "may not treat a registry result as permission to write" not in normalized(section_text(navigation_text, "Write Boundary")):
        errors.append("Navigation Registry results must not grant write permission")
    nav_rows = [row for row in matrix_rows if "Navigation Registry" in row[0]]
    if len(nav_rows) != 1 or nav_rows[0][1] != "ChatGPT Orchestrator":
        errors.append("Navigation Registry routing owner must be ChatGPT Orchestrator")

    workspace_norm = normalized(workspace_write).lower()
    if "repository implementation authorization" not in workspace_norm or "never grants a workspace write" not in workspace_norm:
        errors.append("Workspace writes must remain separately authorized from repository implementation")
    if "exact target" not in workspace_norm and "exact target file" not in workspace_norm:
        errors.append("Workspace Write Authorization must require an exact target")

    if write_policy and "Confirm target, system of record, field ownership, and authorization before any write" not in normalized(write_policy):
        errors.append("Write Authorization Policy must require target, ownership, and authorization confirmation")


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    registry = root / "04_Registry/agent-inheritance-registry.md"
    matrix = root / "04_Registry/responsibility-matrix.md"
    overlays = root / "02_Agent_Overlays"
    tests = root / "07_Agent_Tests"
    if not registry.is_file() or not matrix.is_file():
        return ["Registry or Responsibility Matrix is missing"]

    registry_rows = table_rows(registry.read_text(encoding="utf-8"), ("Agent", "Inherits", "Overlay"), "## Technical Execution Architecture")
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
        if agent in RETIRED_TECHNICAL_AGENTS:
            errors.append(f"Retired technical agent remains canonical: {agent}")

    for required in ("ChatGPT Orchestrator", "GitHub Service Agent", "QA / Test Agent"):
        if required not in agents:
            errors.append(f"Required canonical agent is missing: {required}")

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

    matrix_rows = table_rows(matrix.read_text(encoding="utf-8"), ("Responsibility", "Primary", "Support"))
    assigned: set[str] = set()
    valid_rows: list[list[str]] = []
    for row in matrix_rows:
        if len(row) != 3 or not all(row):
            errors.append("Responsibility Matrix contains a malformed or empty row")
            continue
        valid_rows.append(row)
        responsibility, primary, support = row
        for name in split_people(primary):
            if name in RETIRED_TECHNICAL_AGENTS:
                errors.append(f"Retired technical agent remains matrix primary: {responsibility} -> {name}")
            elif name in agents:
                assigned.add(name)
            else:
                errors.append(f"Unknown primary agent: {responsibility} -> {name}")
        for name in split_people(support):
            if name in RETIRED_TECHNICAL_AGENTS:
                errors.append(f"Retired technical agent remains matrix support: {responsibility} -> {name}")
            elif name in agents:
                assigned.add(name)
            elif name not in SUPPORT_SURFACES:
                errors.append(f"Unknown support value: {responsibility} -> {name}")

    for agent in sorted(agents - assigned):
        errors.append(f"Canonical agent has no Responsibility Matrix assignment: {agent}")

    validate_legacy_aliases(root, agents, errors)
    validate_routing_documents(root, agents, overlay_slugs, errors)
    validate_write_boundaries(root, overlays, valid_rows, errors)
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
