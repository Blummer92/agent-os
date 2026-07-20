"""Structural validation for the simplified issue-lifecycle contract.

Verifies that the three-level lifecycle standard, the risk-owner map, and
the pull-request template stay consistent with the existing issue
acceptance automation without weakening any control.
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
RISK_MAP = ROOT / "04_Registry" / "risk-owner-map.md"
PR_TEMPLATE = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"

REQUIRED_LIFECYCLE_SECTIONS = [
    "Three Work Levels",
    "Level 1 — Roadmap issue",
    "Level 2 — Implementation issue",
    "Level 3 — Pull request",
    "Child-Issue Creation Test",
    "Canonical Boilerplate By Reference",
    "Issue-Body Maintenance",
    "Risk Ownership",
    "Closure And Supersession",
    "Label Policy",
]

PRESERVED_CONTROL_REFERENCES = [
    "write-authorization-policy.md",
    "issue-acceptance-automation.md",
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
