"""B2 regression tests: canonical status precedence in the report path.

The rendered status token always comes from the canonical `Status` enum; the
message channel is annotation only. On divergence, the Status wins.
"""

import pytest

from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    Status,
)
from scripts.agent_os_issue_acceptance.report import render_report


def _report_with(check: CheckResult) -> AcceptanceReport:
    return AcceptanceReport(
        linked_issue=None,
        overall_status=(
            check.status if type(check.status) is Status else Status.PASS
        ),
        checks=[check],
    )


def test_b2_canonical_status_wins_over_prose_message():
    """A blocked-sounding prose message with MANUAL_REVIEW status renders the
    manual-review token: the Status wins on divergence."""
    check = CheckResult(
        "dependencies",
        Status.MANUAL_REVIEW,
        "The issue body declares a dependency blocker (sounds blocked).",
        ["evidence_source=body-prose", "code=prose-declared-blocker"],
    )
    rendered = render_report(_report_with(check))
    assert "- dependencies: manual-review - The issue body declares" in rendered
    assert "- dependencies: fail" not in rendered


def test_b2_canonical_fail_renders_fail_even_with_soft_message():
    """A soft prose message with FAIL status still renders the fail token."""
    check = CheckResult(
        "dependencies",
        Status.FAIL,
        "Minor note only.",
        ["evidence_source=structured-dependency-signal", "code=dependency-blocked"],
    )
    rendered = render_report(_report_with(check))
    assert "- dependencies: fail - Minor note only." in rendered


def test_b2_report_rejects_non_canonical_status():
    """A prose-derived status (e.g. a bare string) fails fast at render time."""
    check = CheckResult("dependencies", "fail", "Prose message.")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="canonical Status"):
        render_report(_report_with(check))


def test_b2_report_rejects_none_status():
    check = CheckResult("dependencies", None, "Prose message.")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="canonical Status"):
        render_report(_report_with(check))


def test_b2_informational_checks_pinned_too():
    """The informational channel carries the same precedence pin."""
    check = CheckResult("dependencies", "fail", "Prose message.")  # type: ignore[arg-type]
    report = AcceptanceReport(
        linked_issue=None,
        overall_status=Status.PASS,
        checks=[],
        informational_checks=(check,),
    )
    with pytest.raises(TypeError, match="canonical Status"):
        render_report(report)
