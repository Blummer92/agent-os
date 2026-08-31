from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "07_Agent_Tests/validate_registry_consistency.py"
SPEC = importlib.util.spec_from_file_location("registry_consistency", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace(root: Path, path: str, old: str, new: str) -> None:
    target = root / path
    target.write_text(target.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def baseline(tmp_path: Path) -> Path:
    write(tmp_path, "AGENTS.md", """# AGENTS\n\n## Access Rules\nOnly the GitHub Service Agent may write to GitHub. All non-GitHub agents must use a handoff.\n""")
    write(tmp_path, "00_Governance/write-authorization-policy.md", "Confirm target, system of record, field ownership, and authorization before any write.\n")
    write(tmp_path, "04_Registry/agent-inheritance-registry.md", """# Agent Inheritance Registry\n\n| Agent | Inherits | Overlay |\n|---|---|---|\n| ChatGPT Orchestrator | Global | chatgpt-orchestrator |\n| GitHub Service Agent | Global | github-service-agent |\n| QA / Test Agent | Global | qa-test-agent |\n\n## Technical Execution Architecture\nTwo technical roles.\n""")
    write(tmp_path, "04_Registry/responsibility-matrix.md", """# Responsibility Matrix\n\n| Responsibility | Primary | Support |\n|---|---|---|\n| ChatGPT request triage | ChatGPT Orchestrator | QA / Test Agent |\n| Repository implementation (all languages) | GitHub Service Agent | QA / Test Agent |\n| GitHub repository writes | GitHub Service Agent | QA / Test Agent |\n| Navigation Registry governance and lookup routing | ChatGPT Orchestrator | Navigation Registry Standard; QA / Test Agent |\n""")
    write(tmp_path, "04_Registry/legacy-agent-alias-registry.md", """# Legacy Agent Alias Registry\n\n| Legacy Name / Property | Canonical Agent | Current Overlay | Status | Notes |\n|---|---|---|---|---|\n| Integration Manager | ChatGPT Orchestrator | `chatgpt-orchestrator` | active alias | retired |\n| Google Workspace Automation Engineer | GitHub Service Agent | `github-service-agent` | active alias | retired; live writes separate |\n| Python Development Overlay | GitHub Service Agent | `github-service-agent` | active alias | Python Standards |\n\n## Ambiguous Legacy Values\n\n| Legacy Name / Property | Default Canonical Agent | Alternate Canonical Agent | Disambiguation Rule |\n|---|---|---|---|\n| Workspace Builder | ChatGPT Orchestrator | GitHub Service Agent | classify first |\n""")
    write(tmp_path, "02_Agent_Overlays/chatgpt-orchestrator.md", """# ChatGPT Orchestrator\n\n## Blocked Write Surfaces\nGitHub repository writes, production systems, governed fields, source-of-truth records.\n""")
    write(tmp_path, "02_Agent_Overlays/github-service-agent.md", """# GitHub Service Agent\n\n## Canonical Role\nSole GitHub write owner and sole ordinary repository implementation owner.\n\n## Inherited Standards\n- `00_Governance/write-authorization-policy.md`\n- `01_Shared_Standards/github/protected-branch-governance.md`\n""")
    write(tmp_path, "02_Agent_Overlays/qa-test-agent.md", "# QA / Test Agent\n")
    for slug in ("chatgpt-orchestrator", "github-service-agent", "qa-test-agent"):
        write(tmp_path, f"07_Agent_Tests/{slug}.tests.md", "# Tests\n")
    write(tmp_path, "01_Shared_Standards/navigation/navigation-registry-standard.md", """# Navigation Registry Standard\n\n## Non-Authoritative Rule\nThe Navigation Registry is a lookup aid only. Cached records do not authorize writes or ownership changes.\n\n## Write Boundary\nAgents may not treat a registry result as permission to write.\n""")
    write(tmp_path, "01_Shared_Standards/google-workspace/workspace-write-authorization.md", """# Workspace Write Authorization\nThe exact target file must be confirmed. Repository implementation authorization never grants a Workspace write.\n""")
    write(tmp_path, "01_Shared_Standards/github/protected-branch-governance.md", """# Protected Branch Governance\n\n## Normal Change Path\nChanges begin on a non-protected branch and use a pull request.\n""")
    write(tmp_path, "04_Registry/agent-loadout-matrix.md", """# Agent Loadout Matrix\n\n| Agent | Overlay | Additional inherited standards | Default tier/write mode | Primary work | Evidence and escalation |\n|---|---|---|---|---|---|\n| ChatGPT Orchestrator | `chatgpt-orchestrator` | Navigation | Tier 0 | routing | escalate writes |\n| GitHub Service Agent | `github-service-agent` | Python | Tier 1/2 | repository | validate |\n| QA / Test Agent | `qa-test-agent` | QA | Tier 0 | evidence | report |\n\n## Governed Routing Overlays\nHelper only.\n""")
    write(tmp_path, "04_Registry/task-routing-guide.md", """# Task Routing Guide\n\n| Workflow | Primary role | Support or overlay | Tier and intake | Source and destination | Stop or escalate when |\n|---|---|---|---|---|---|\n| Read-only review | QA / Test Agent | Relevant registered owner | Tier 0, Lightweight | source | unclear |\n| Governed registry change | GitHub Service Agent | ChatGPT Orchestrator; QA / Test Agent | Tier 2, Full plus Live Readiness | GitHub | unclear |\n| Ambiguous write request | ChatGPT Orchestrator | target owner | Manual review | No write | unclear |\n\n## Routing Sequence\nUse Full Intake and Live Readiness for Tier 2 and Tier 3 external-write or irreversible work.\n\n## Fail-Closed Rules\nAmbiguous evidence routes to human decision.\n""")
    return tmp_path


def test_current_repository_passes() -> None:
    assert MODULE.validate(MODULE.ROOT) == []


def test_clean_two_role_technical_baseline_passes(tmp_path: Path) -> None:
    assert MODULE.validate(baseline(tmp_path)) == []


def test_integration_manager_cannot_be_canonical_again(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "04_Registry/agent-inheritance-registry.md", "| QA / Test Agent | Global | qa-test-agent |", "| QA / Test Agent | Global | qa-test-agent |\n| Integration Manager | Global | integration-manager |")
    write(root, "02_Agent_Overlays/integration-manager.md", "# Integration\n")
    write(root, "07_Agent_Tests/integration-manager.tests.md", "# Tests\n")
    assert "Retired technical agent remains canonical: Integration Manager" in MODULE.validate(root)


def test_workspace_engineer_cannot_be_canonical_again(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "04_Registry/agent-inheritance-registry.md", "| QA / Test Agent | Global | qa-test-agent |", "| QA / Test Agent | Global | qa-test-agent |\n| Google Workspace Automation Engineer | Global | google-workspace-automation-engineer |")
    write(root, "02_Agent_Overlays/google-workspace-automation-engineer.md", "# Workspace\n")
    write(root, "07_Agent_Tests/google-workspace-automation-engineer.tests.md", "# Tests\n")
    assert "Retired technical agent remains canonical: Google Workspace Automation Engineer" in MODULE.validate(root)


def test_retired_role_cannot_be_routing_primary(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "04_Registry/task-routing-guide.md", "| Governed registry change | GitHub Service Agent |", "| Governed registry change | Integration Manager |")
    assert any("Retired technical agent remains routing primary" in e for e in MODULE.validate(root))


def test_retired_role_cannot_be_loadout_agent(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "04_Registry/agent-loadout-matrix.md", "| QA / Test Agent | `qa-test-agent` | QA | Tier 0 | evidence | report |", "| QA / Test Agent | `qa-test-agent` | QA | Tier 0 | evidence | report |\n| Integration Manager | `chatgpt-orchestrator` | Navigation | Tier 0 | routing | report |")
    assert any("Unknown loadout agent: Integration Manager" in e or "Retired technical agent remains executable in loadout" in e for e in MODULE.validate(root))


def test_navigation_routing_owner_is_orchestrator(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "04_Registry/responsibility-matrix.md", "| Navigation Registry governance and lookup routing | ChatGPT Orchestrator |", "| Navigation Registry governance and lookup routing | QA / Test Agent |")
    assert "Navigation Registry routing owner must be ChatGPT Orchestrator" in MODULE.validate(root)


def test_repository_implementation_owner_is_github(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "04_Registry/responsibility-matrix.md", "| Repository implementation (all languages) | GitHub Service Agent |", "| Repository implementation (all languages) | QA / Test Agent |")
    assert "Ordinary repository implementation owner must be GitHub Service Agent" in MODULE.validate(root)


def test_retired_aliases_are_required(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "04_Registry/legacy-agent-alias-registry.md", "| Integration Manager | ChatGPT Orchestrator |", "| Integration Manager | QA / Test Agent |")
    assert any("Integration Manager -> ChatGPT Orchestrator" in e for e in MODULE.validate(root))


def test_python_legacy_alias_resolves_to_github(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "04_Registry/legacy-agent-alias-registry.md", "| Python Development Overlay | GitHub Service Agent |", "| Python Development Overlay | ChatGPT Orchestrator |")
    assert any("Python Development Overlay -> GitHub Service Agent" in e for e in MODULE.validate(root))


def test_workspace_write_never_inherits_repository_authority(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "01_Shared_Standards/google-workspace/workspace-write-authorization.md", "Repository implementation authorization never grants a Workspace write.", "Repository implementation may authorize a Workspace write.")
    assert "Workspace writes must remain separately authorized from repository implementation" in MODULE.validate(root)


def test_chatgpt_orchestrator_does_not_gain_github_write(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "02_Agent_Overlays/chatgpt-orchestrator.md", "GitHub repository writes", "External routing")
    assert "ChatGPT Orchestrator must not gain direct GitHub repository write authority" in MODULE.validate(root)


def test_github_sole_writer_rule_remains(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace(root, "AGENTS.md", "Only the GitHub Service Agent may write to GitHub.", "GitHub writes require approval.")
    assert "AGENTS access rules must name GitHub Service Agent as the sole GitHub writer" in MODULE.validate(root)


# --- Semantic ownership advisory (#1511) fixture matrix ---------------------


def semantic_baseline(tmp_path: Path) -> Path:
    root = baseline(tmp_path)
    write(root, "04_Registry/navigation/README.md", (
        "# Navigation Registry\n\n"
        "Navigation Registry governance is owned by the ChatGPT Orchestrator.\n\n"
        "Use GitHub Service Agent instead of Google Workspace Automation Engineer.\n"
    ))
    write(root, "04_Registry/lp-reason-code-catalog.yaml", (
        "semantic_owners:\n"
        "- id: chatgpt-orchestrator\n"
        "  role: ChatGPT Orchestrator\n"
        "families:\n"
        "- id: routing\n"
        "  semantic_owner: chatgpt-orchestrator\n"
    ))
    write(root, "01_Shared_Standards/instructional-design/lp-reason-code-catalog.md", (
        "# LP Reason Code Catalog\n\n"
        "## ownership-single-semantic-owner\n"
        "ChatGPT Orchestrator for routing meaning.\n"
    ))
    write(root, "04_Registry/reusable-capabilities.yml", "records:\n- owner_agent: Integration Manager\n")
    write(root, "04_Registry/navigation/06_Archive/legacy.md", "Owner agent: Integration Manager\n")
    return root


def test_so1_stale_retired_owner_navigation(tmp_path: Path) -> None:
    root = semantic_baseline(tmp_path)
    replace(root, "04_Registry/navigation/README.md", "owned by the ChatGPT Orchestrator", "owned by the Integration Manager")
    findings = MODULE.validate_semantic_ownership(root)
    assert any("stale retired owner" in e and "navigation/README.md" in e for e in findings)


def test_so2_stale_retired_owner_catalog(tmp_path: Path) -> None:
    root = semantic_baseline(tmp_path)
    replace(root, "04_Registry/lp-reason-code-catalog.yaml", "role: ChatGPT Orchestrator", "role: Integration Manager")
    replace(root, "04_Registry/lp-reason-code-catalog.yaml", "semantic_owner: chatgpt-orchestrator", "semantic_owner: integration-manager")
    findings = MODULE.validate_semantic_ownership(root)
    assert any("stale retired owner" in e and "semantic_owners[].role" in e for e in findings)
    assert any("stale retired owner" in e and "semantic_owner ->" in e for e in findings)


def test_so3_unknown_canonical_owner(tmp_path: Path) -> None:
    root = semantic_baseline(tmp_path)
    replace(root, "04_Registry/navigation/README.md", "owned by the ChatGPT Orchestrator", "owned by the Random Agent")
    findings = MODULE.validate_semantic_ownership(root)
    assert any("unknown canonical owner" in e and "Random Agent" in e for e in findings)


def test_so4_reusable_capabilities_alias_allowed_not_scanned(tmp_path: Path) -> None:
    root = semantic_baseline(tmp_path)
    findings = MODULE.validate_semantic_ownership(root)
    assert not any("reusable-capabilities.yml" in e for e in findings)


def test_so5_archive_reference_ignored(tmp_path: Path) -> None:
    root = semantic_baseline(tmp_path)
    findings = MODULE.validate_semantic_ownership(root)
    assert not any("06_Archive" in e for e in findings)


def test_so6_ordinary_prose_resolving_legacy_name_ignored(tmp_path: Path) -> None:
    root = semantic_baseline(tmp_path)
    findings = MODULE.validate_semantic_ownership(root)
    assert not any("Google Workspace Automation Engineer" in e for e in findings)


def test_so7_current_canonical_owner_no_finding(tmp_path: Path) -> None:
    root = semantic_baseline(tmp_path)
    assert MODULE.validate_semantic_ownership(root) == []


def test_so8_no_ownership_field_present_no_finding(tmp_path: Path) -> None:
    root = semantic_baseline(tmp_path)
    write(root, "04_Registry/navigation/no-owner.md", "# Just a page\n\nNo ownership assertion here.\n")
    assert MODULE.validate_semantic_ownership(root) == []


def test_semantic_ownership_advisory_is_non_blocking_on_current_repository() -> None:
    findings = MODULE.validate_semantic_ownership(MODULE.ROOT)
    assert isinstance(findings, list)
