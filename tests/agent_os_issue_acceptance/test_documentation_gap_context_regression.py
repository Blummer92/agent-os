import pytest

from scripts.agent_os_issue_acceptance.documentation_gap_report import DocumentationGapCategory, build_documentation_gap_report
from scripts.agent_os_issue_acceptance.issue_scanner import IssueScannerRecord


def record(body: str) -> IssueScannerRecord:
    return IssueScannerRecord(2161, "Implementation work", "open", body, ("type:implementation",), "https://github.com/Blummer92/agent-os/issues/2161", "2026-09-08T20:00:00Z", "2026-09-08T20:00:00Z", "sha")


def category(body: str) -> DocumentationGapCategory:
    return build_documentation_gap_report([record(body)], evaluator_revision="test").rows[0].category


def implementation_body(extra: str) -> str:
    return f"""## Objective
Implement bounded work.
## Owner
GitHub Service Agent
## Source of truth
GitHub
## Scope
Repository only.
## Acceptance criteria
- [ ] Deterministic.
{extra}
"""


@pytest.mark.parametrize(
    "extra",
    [
        "Example: this issue is a roadmap only",
        'Do not write "tracker only" here.',
        "> This issue is a roadmap only",
        "```text\nThis issue is a roadmap only\n```",
    ],
)
def test_non_authoritative_planning_phrases_do_not_make_issue_not_applicable(extra: str) -> None:
    assert category(implementation_body(extra)) == DocumentationGapCategory.BACKFILL_NOW


def test_genuine_roadmap_declaration_remains_not_applicable() -> None:
    assert category(implementation_body("This issue is a roadmap only")) == DocumentationGapCategory.NOT_APPLICABLE
