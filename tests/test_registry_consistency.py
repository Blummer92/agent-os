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


def replace_text(root: Path, path: str, old: str, new: str) -> None:
    target = root / path
    target.write_text(target.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def baseline(tmp_path: Path) -> Path:
    write(tmp_path, "AGENTS.md", """# AGENTS

## Access Rules

Only the GitHub Service Agent may write to GitHub. All non-GitHub agents must use a handoff.

## Other Rules

Use governed sources.
""")
    write(tmp_path, "00_Governance/write-authorization-policy.md", """# Write Authorization Policy

Confirm target, system of record, field ownership, and authorization before any write.
""")
    write(tmp_path, "04_Registry/agent-inheritance-registry.md", """# Agent Inheritance Registry

| Agent | Inherits | Overlay |
|---|---|---|
| Integration Manager | Global | `integration-manager` |
| QA / Test Agent | Global | qa-test-agent |
| GitHub Service Agent | Global | github-service-agent |

## Routed Combinations

| Workflow | Canonical Owner | Overlays |
|---|---|---|
| Example | Integration Manager | selected registered owner |
""")
    write(tmp_path, "04_Registry/responsibility-matrix.md", """# Responsibility Matrix

| Responsibility | Primary | Support |
|---|---|---|
| GitHub repository writes | GitHub Service Agent | QA / Test Agent |
| Navigation Registry governance and lookup routing | Integration Manager | QA / Test Agent |
""")
    write(tmp_path, "02_Agent_Overlays/integration-manager.md", """# Integration Manager

## Inherited Standards

`01_Shared_Standards/navigation/navigation-registry-standard.md`

## Owned Systems

Integration maps and cross-system navigation governance.

## Allowed Write Surfaces

Local specs and approved coordination records.

## Blocked Write Surfaces

Direct GitHub writes outside the GitHub Service Agent handoff.
""")
    write(tmp_path, "02_Agent_Overlays/github-service-agent.md", """# GitHub Service Agent

## Canonical Role

Sole GitHub write owner for ChatGPT-driven Agent OS implementation work.

## Inherited Standards

- `00_Governance/write-authorization-policy.md`
- `01_Shared_Standards/github/protected-branch-governance.md`
""")
    write(tmp_path, "02_Agent_Overlays/qa-test-agent.md", "# QA\n")
    write(tmp_path, "07_Agent_Tests/integration-manager.tests.md", "# Tests\n")
    write(tmp_path, "07_Agent_Tests/github-service-agent.tests.md", "# Tests\n")
    write(tmp_path, "07_Agent_Tests/qa-test-agent.tests.md", "# Tests\n")
    write(tmp_path, "01_Shared_Standards/navigation/navigation-registry-standard.md", """# Navigation Registry Standard

## Non-Authoritative Rule

The Navigation Registry is a lookup aid only. Cached records do not authorize writes or ownership changes.

## Write Boundary

Agents may not treat a registry result as permission to write.
""")
    write(tmp_path, "01_Shared_Standards/github/protected-branch-governance.md", """# Protected Branch Governance

## Normal Change Path

Changes begin on a non-protected branch and use a pull request.
""")
    return tmp_path


def replace_matrix_support(root: Path, value: str) -> None:
    replace_text(root, "04_Registry/responsibility-matrix.md", "QA / Test Agent", value)


def append_matrix_row(root: Path, row: str) -> None:
    matrix = root / "04_Registry/responsibility-matrix.md"
    matrix.write_text(matrix.read_text(encoding="utf-8") + row, encoding="utf-8")


def errors_with_support(root: Path, value: str) -> list[str]:
    replace_matrix_support(root, value)
    return MODULE.validate(root)


def test_current_repository_passes() -> None:
    assert MODULE.validate(MODULE.ROOT) == []


def test_clean_baseline_passes(tmp_path: Path) -> None:
    assert MODULE.validate(baseline(tmp_path)) == []


def test_output_is_deterministic_and_non_mutating(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    first = MODULE.validate(root)
    second = MODULE.validate(root)
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert first == second == []
    assert before == after


def test_missing_overlay_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "02_Agent_Overlays/qa-test-agent.md").unlink()
    assert "Registered agent has no overlay: qa-test-agent" in MODULE.validate(root)


def test_missing_test_file_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "07_Agent_Tests/qa-test-agent.tests.md").unlink()
    assert "Registered agent has no test file: qa-test-agent" in MODULE.validate(root)


def test_unknown_matrix_agent_fails_and_does_not_count_as_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "Unknown Agent")
    assert any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_routing_placeholder_is_not_valid_matrix_support_or_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "selected registered owner")
    assert any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_exact_helper_support_surface_is_valid_but_not_agent_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "Python Development Overlay")
    assert not any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_near_match_helper_support_surface_fails_and_is_not_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "Python Development")
    assert any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_legacy_alias_is_not_agent_coverage(tmp_path: Path) -> None:
    errors = errors_with_support(baseline(tmp_path), "QA Agent")
    assert any("Unknown support value" in error for error in errors)
    assert "Canonical agent has no Responsibility Matrix assignment: QA / Test Agent" in errors


def test_primary_assignment_counts_as_coverage(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_matrix_support(root, "Python Development Overlay")
    append_matrix_row(root, "| Validation evidence | QA / Test Agent | Integration Manager |\n")
    assert MODULE.validate(root) == []


def test_exact_canonical_support_assignment_counts_as_coverage(tmp_path: Path) -> None:
    assert MODULE.validate(baseline(tmp_path)) == []


def test_registered_agent_without_any_matrix_assignment_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(
        root,
        "04_Registry/agent-inheritance-registry.md",
        "| GitHub Service Agent | Global | github-service-agent |",
        "| GitHub Service Agent | Global | github-service-agent |\n| Agent Orchestrator | Global | agent-orchestrator |",
    )
    write(root, "02_Agent_Overlays/agent-orchestrator.md", "# Agent Orchestrator\n")
    write(root, "07_Agent_Tests/agent-orchestrator.tests.md", "# Tests\n")
    assert "Canonical agent has no Responsibility Matrix assignment: Agent Orchestrator" in MODULE.validate(root)


def test_malformed_or_empty_matrix_row_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    append_matrix_row(root, "| Empty support | Integration Manager | |\n")
    assert "Responsibility Matrix contains a malformed or empty row" in MODULE.validate(root)


def test_missing_shared_standard_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "01_Shared_Standards/navigation/navigation-registry-standard.md").unlink()
    assert any("Navigation Registry Standard" in error for error in MODULE.validate(root))


def test_navigation_owner_mismatch_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "04_Registry/responsibility-matrix.md", "| Navigation Registry governance and lookup routing | Integration Manager |", "| Navigation Registry governance and lookup routing | QA / Test Agent |")
    assert "Navigation Registry primary owner must be Integration Manager" in MODULE.validate(root)


def test_navigation_description_can_change_without_failure(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "04_Registry/responsibility-matrix.md", "governance and lookup routing", "cross-system routing and governance")
    assert MODULE.validate(root) == []


def test_unregistered_overlay_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    write(root, "02_Agent_Overlays/unregistered.md", "# Unregistered\n")
    assert "Overlay is not registered or exempt: unregistered" in MODULE.validate(root)


def test_github_write_owner_reassignment_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "04_Registry/responsibility-matrix.md", "| GitHub repository writes | GitHub Service Agent |", "| GitHub repository writes | Integration Manager |")
    assert "GitHub repository write owner must be GitHub Service Agent" in MODULE.validate(root)


def test_agents_sole_writer_rule_removed_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "AGENTS.md", "Only the GitHub Service Agent may write to GitHub.", "GitHub writes require approval.")
    assert "AGENTS access rules must name GitHub Service Agent as the sole GitHub writer" in MODULE.validate(root)


def test_agents_conflicting_writer_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "AGENTS.md", "All non-GitHub agents must use a handoff.", "All non-GitHub agents must use a handoff. Integration Manager may write to GitHub.")
    assert "AGENTS access rules contain a conflicting GitHub write authorization" in MODULE.validate(root)


def test_github_service_agent_role_removed_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "02_Agent_Overlays/github-service-agent.md", "Sole GitHub write owner", "GitHub coordination role")
    assert "GitHub Service Agent must retain the sole GitHub write-owner role" in MODULE.validate(root)


def test_protected_governance_reference_removed_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "02_Agent_Overlays/github-service-agent.md", "- `01_Shared_Standards/github/protected-branch-governance.md`\n", "")
    assert "GitHub Service Agent must inherit Protected Branch Governance" in MODULE.validate(root)


def test_missing_protected_governance_source_fails_clearly(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "01_Shared_Standards/github/protected-branch-governance.md").unlink()
    assert "Required governance file is missing: Protected Branch Governance Standard" in MODULE.validate(root)


def test_protected_governance_requires_branch_and_pr_path(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "01_Shared_Standards/github/protected-branch-governance.md", "Changes begin on a non-protected branch and use a pull request.", "Changes use an approved process.")
    assert "Protected Branch Governance must require a non-protected branch and pull request" in MODULE.validate(root)


def test_navigation_non_authoritative_rule_removed_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "01_Shared_Standards/navigation/navigation-registry-standard.md", "The Navigation Registry is a lookup aid only. Cached records do not authorize writes or ownership changes.", "The Navigation Registry stores routing metadata.")
    assert "Navigation Registry must remain explicitly non-authoritative" in MODULE.validate(root)


def test_navigation_permission_grant_conflict_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "01_Shared_Standards/navigation/navigation-registry-standard.md", "Cached records do not authorize writes or ownership changes.", "Cached records do not authorize ownership changes. Cached records authorize writes.")
    assert "Navigation Registry standard contains a conflicting write authorization" in MODULE.validate(root)


def test_navigation_write_boundary_removed_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "01_Shared_Standards/navigation/navigation-registry-standard.md", "Agents may not treat a registry result as permission to write.", "Agents should verify results.")
    assert "Navigation Registry results must not grant write permission" in MODULE.validate(root)


def test_integration_navigation_ownership_removed_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "02_Agent_Overlays/integration-manager.md", "cross-system navigation governance", "cross-system routing support")
    assert "Integration Manager must retain cross-system navigation governance" in MODULE.validate(root)


def test_integration_github_handoff_boundary_removed_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "02_Agent_Overlays/integration-manager.md", "Direct GitHub writes outside the GitHub Service Agent handoff.", "Unclear writes are blocked.")
    assert "Integration Manager must block direct GitHub writes outside the GitHub Service Agent handoff" in MODULE.validate(root)


def test_integration_direct_github_write_grant_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "02_Agent_Overlays/integration-manager.md", "Local specs and approved coordination records.", "Local specs and direct GitHub writes.")
    assert "Integration Manager must not have direct GitHub write authority" in MODULE.validate(root)


def test_write_policy_confirmation_rule_removed_fails(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    replace_text(root, "00_Governance/write-authorization-policy.md", "Confirm target, system of record, field ownership, and authorization before any write.", "Confirm the request before writing.")
    assert "Write Authorization Policy must require target, ownership, and authorization confirmation" in MODULE.validate(root)


def test_harmless_prose_changes_do_not_break_invariants(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    protected = root / "01_Shared_Standards/github/protected-branch-governance.md"
    protected.write_text(protected.read_text(encoding="utf-8") + "\n## Notes\n\nExamples may vary by repository.\n", encoding="utf-8")
    navigation = root / "01_Shared_Standards/navigation/navigation-registry-standard.md"
    navigation.write_text(navigation.read_text(encoding="utf-8") + "\n## Notes\n\nLookup latency is implementation-specific.\n", encoding="utf-8")
    assert MODULE.validate(root) == []
