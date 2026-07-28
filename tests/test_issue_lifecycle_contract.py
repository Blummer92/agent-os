"""Structural validation for the simplified issue-lifecycle contract.

Verifies that the three-level lifecycle standard, the Safe Implementation Lane,
the risk-owner map, and the pull-request template stay consistent with the
existing issue acceptance automation without weakening any control.
"""
from __future__ import annotations

import re
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import LinkedIssueParseStatus
from scripts.agent_os_issue_acceptance.parse_pr import (
    REQUIRED_PR_FIELDS,
    has_markdown_heading,
    has_validation_command,
    parse_linked_issue_result,
)

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "01_Shared_Standards" / "github" / "issue-lifecycle-standard.md"
SAFE_LANE = ROOT / "01_Shared_Standards" / "github" / "safe-implementation-lane.md"
WRITE_POLICY = ROOT / "00_Governance" / "write-authorization-policy.md"
GITHUB_OVERLAY = ROOT / "02_Agent_Overlays" / "github-service-agent.md"
RISK_MAP = ROOT / "04_Registry" / "risk-owner-map.md"
PR_TEMPLATE = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"

REQUIRED_LIFECYCLE_SECTIONS = [
    "Three Work Levels",
    "Level 1 — Roadmap issue",
    "Level 2 — Implementation issue",
    "Level 3 — Pull request",
    "Safe Implementation Lane",
    "Child-Issue Creation Test",
    "Canonical Boilerplate By Reference",
    "Issue-Body Maintenance",
    "Risk Ownership",
    "Closure And Supersession",
    "Closed-Issue Authority",
    "Refactor And Consolidation Value",
    "Label Policy",
]

REQUIRED_SAFE_LANE_SECTIONS = [
    "Purpose",
    "Eligibility",
    "Authorization Effect",
    "Bounded Scope Envelope",
    "Branch Names",
    "Operational Authorization Comments",
    "Stop Conditions",
    "Reporting",
    "Version",
]

PRESERVED_CONTROL_REFERENCES = [
    "write-authorization-policy.md",
    "issue-acceptance-automation.md",
    "safe-implementation-lane.md",
    "protected-branch-governance.md",
    "fail-closed",
]


def test_lifecycle_standard_defines_required_sections() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    missing = [
        section
        for section in REQUIRED_LIFECYCLE_SECTIONS
        if not has_markdown_heading(text, section)
    ]
    assert not missing, f"lifecycle standard is missing sections: {missing}"


def test_lifecycle_standard_preserves_safety_references() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    missing = [ref for ref in PRESERVED_CONTROL_REFERENCES if ref not in text]
    assert not missing, f"lifecycle standard dropped control references: {missing}"


def test_safe_implementation_lane_defines_required_sections() -> None:
    text = SAFE_LANE.read_text(encoding="utf-8")
    missing = [
        section
        for section in REQUIRED_SAFE_LANE_SECTIONS
        if not has_markdown_heading(text, section)
    ]
    assert not missing, f"safe implementation lane is missing sections: {missing}"


def test_safe_lane_is_risk_tiered_and_not_readiness_authorized() -> None:
    text = SAFE_LANE.read_text(encoding="utf-8")
    for phrase in (
        "Tier 0 or Tier 1",
        "status:ready",
        "no-external-write",
        "explicit implementation instruction",
        "Tier 2",
        "not eligible",
    ):
        assert phrase in text, f"safe lane is missing eligibility boundary: {phrase}"

    write_policy = WRITE_POLICY.read_text(encoding="utf-8")
    assert "Readiness alone does not authorize implementation" in write_policy


def test_safe_lane_authorizes_bounded_pr_work_but_not_merge() -> None:
    text = SAFE_LANE.read_text(encoding="utf-8")
    for phrase in (
        "one non-protected branch",
        "bounded scope envelope",
        "one draft pull request",
        "Ready-for-Review",
        "It does not authorize merge",
        "issue closure",
        "protected-setting changes",
        "production or external writes",
    ):
        assert phrase in text, f"safe lane is missing authorization boundary: {phrase}"


def test_safe_lane_defines_mechanical_support_scope_without_material_expansion() -> None:
    text = SAFE_LANE.read_text(encoding="utf-8")
    for phrase in (
        "directly corresponding tests and documentation",
        "minimum package exports",
        "architecture registration or classification",
        "generated manifests or changelog entries",
        "behaviorally subordinate",
        "new subsystem",
        "schema",
        "external effect",
    ):
        assert phrase in text, f"safe lane is missing scope rule: {phrase}"


def test_safe_lane_accepts_environment_assigned_branch_names() -> None:
    text = SAFE_LANE.read_text(encoding="utf-8")
    assert "harness- or environment-assigned branch name" in text
    assert "guidance, not an authorization boundary" in text


def test_safe_lane_comments_cannot_override_durable_or_closed_authority() -> None:
    text = SAFE_LANE.read_text(encoding="utf-8")
    for phrase in (
        "issue body remains authoritative",
        "may not broaden durable scope",
        "reactivate a closed issue",
        "authorize merge",
    ):
        assert phrase in text, f"safe lane is missing comment authority guard: {phrase}"


def test_github_service_agent_inherits_lane_and_retains_core_controls() -> None:
    text = GITHUB_OVERLAY.read_text(encoding="utf-8")
    for phrase in (
        "safe-implementation-lane.md",
        "Sole GitHub write owner",
        "non-protected branch",
        "merge, auto-merge, issue closure",
        "separately authorized",
    ):
        assert phrase in text, f"GitHub Service Agent overlay is missing: {phrase}"


def test_pr_template_satisfies_acceptance_report_headings() -> None:
    text = PR_TEMPLATE.read_text(encoding="utf-8")
    missing = [
        field for field in REQUIRED_PR_FIELDS if not has_markdown_heading(text, field)
    ]
    assert not missing, f"PR template is missing required headings: {missing}"


def test_pr_template_references_validation_commands() -> None:
    assert has_validation_command(PR_TEMPLATE.read_text(encoding="utf-8"))


def test_pr_template_includes_rollback_heading() -> None:
    """Level 3 of the lifecycle standard requires the PR to own rollback
    evidence. REQUIRED_PR_FIELDS in the canonical acceptance parser is left
    unchanged; this only enforces the lifecycle standard's own template."""
    text = PR_TEMPLATE.read_text(encoding="utf-8")
    assert has_markdown_heading(text, "rollback"), (
        "PR template must include a Rollback heading per "
        "issue-lifecycle-standard.md Level 3 (pull request owns rollback evidence)"
    )


def test_risk_map_rows_have_exactly_one_canonical_owner() -> None:
    """Structural check only: proves the map's format invariant (one owner
    issue number per row). It cannot and does not prove that a referenced
    issue is still open, current, or canonical on live GitHub — that
    requires network access and is out of scope for offline structural
    tests. Freshness is a manual-review and issue-lifecycle-maintenance
    concern, not something this test can enforce."""
    text = RISK_MAP.read_text(encoding="utf-8")
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("|")
        and not line.startswith("|---")
        and "Canonical owner" not in line
    ]
    assert rows, "risk-owner map defines no risk rows"
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 5, f"risk row must have 5 columns: {row}"
        owners = re.findall(r"#\d+", cells[1])
        assert len(owners) == 1, (
            f"risk '{cells[0]}' must name exactly one canonical owner issue, "
            f"found {owners}"
        )


def test_risk_map_is_linked_from_lifecycle_standard() -> None:
    assert "risk-owner-map.md" in LIFECYCLE.read_text(encoding="utf-8")


def test_lifecycle_standard_defines_closed_issue_authority_and_dispositions() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    for phrase in (
        "immutable",
        "cannot reactivate a closed issue",
        "reopening requires explicit authorization",
    ):
        assert phrase in text, f"missing closed-issue authority phrase: {phrase}"
    for disposition in (
        "completed",
        "completed/no-change",
        "not planned",
        "duplicate",
        "superseded",
    ):
        assert f"`{disposition}`" in text, f"missing terminal disposition: {disposition}"


def test_lifecycle_standard_defines_refactor_value_policy() -> None:
    text = LIFECYCLE.read_text(encoding="utf-8")
    for phrase in (
        "three behaviorally identical",
        "no universal 40-line threshold",
        "no-change is a valid",
    ):
        assert phrase in text, f"missing refactor-value phrase: {phrase}"


def test_risk_map_names_issue_lifecycle_owner_543_not_544() -> None:
    text = RISK_MAP.read_text(encoding="utf-8")
    row = next(
        (
            line
            for line in text.splitlines()
            if line.startswith("|") and "retired-scope revival" in line
        ),
        None,
    )
    assert row is not None, "risk-owner map is missing the issue-lifecycle authority row"
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[1] == "#543", f"issue-lifecycle risk owner must be #543, found {cells[1]}"
    # #544 closes after implementation and must never become a persistent owner.
    assert "#544" not in text


def _pr_satisfies_linked_issue_contract(pr_body: str, pr_title: str = "") -> bool:
    """Level 3 requires exactly one authoritative closing target. Reuses the
    canonical parser and result vocabulary; adds no new parsing logic."""
    result = parse_linked_issue_result(pr_body, pr_title)
    return result.status == LinkedIssueParseStatus.RESOLVED


def test_single_authoritative_closing_target_satisfies_lifecycle_contract() -> None:
    assert _pr_satisfies_linked_issue_contract("Closes #123")


def test_no_closing_target_does_not_satisfy_lifecycle_contract() -> None:
    assert not _pr_satisfies_linked_issue_contract("This PR has no linked issue.")


def test_two_authoritative_closing_targets_do_not_satisfy_lifecycle_contract() -> None:
    assert not _pr_satisfies_linked_issue_contract("Closes #123\n\nFixes #456")


def test_bare_issue_reference_does_not_satisfy_lifecycle_contract() -> None:
    assert not _pr_satisfies_linked_issue_contract("See #123 for background context.")


def test_unsupported_addresses_keyword_does_not_satisfy_lifecycle_contract() -> None:
    assert not _pr_satisfies_linked_issue_contract("Addresses #123")
