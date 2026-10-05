"""B2 regression tests: prose-vs-canonical precedence in readiness.

The AI navigation layer selects among canonical deterministic outcomes; it
does not manufacture operational state. Body-prose blocker declarations are
prose evidence only: they are tagged distinctly from the canonical dependency
signal, and stale prose never overrides an injected canonical CLEAR.
"""

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_acceptance.readiness import (
    ReadinessOutcome,
    evaluate_issue_readiness,
    evaluate_issue_readiness_with_labels,
)
from scripts.agent_os_issue_acceptance.models import AcceptanceReport


def _tier_zero_body(dependency_line: str) -> str:
    return f"""
Issue Tier: 0
## Objective
Remove one deprecation warning.
## Owner
GitHub Service Agent
## Allowed Files
- src/example.py
## Validation
- pytest tests/test_example.py
## Completion Criterion
- Warning no longer appears.
## Prior scope, duplicate, and supersession review
Reviewed related prior issues; no duplicate or superseded scope applies.
## Documentation impact
docs-not-required
## Documentation exemption reason
Removing a deprecation warning does not change documented behavior.
{dependency_line}
"""


def _dependencies_check(result):
    matches = [c for c in result.report.checks if c.name == "dependencies"]
    assert len(matches) == 1
    return matches[0]


def test_b2_prose_declared_blocker_is_tagged_not_canonical():
    """Stale-blocker prose scan: a prose-only blocker is distinguishable."""
    result = evaluate_issue_readiness(_tier_zero_body("Blocked by: #9999"))
    assert result.outcome == ReadinessOutcome.BLOCKED
    check = _dependencies_check(result)
    assert check.status is Status.FAIL
    assert "code=prose-declared-blocker" in check.evidence
    assert "evidence_source=body-prose" in check.evidence
    assert "declared=#9999" in check.evidence
    assert "code=dependency-blocked" not in check.evidence
    assert "A required dependency is blocked." not in result.report.blockers


def test_b2_canonical_blocked_keeps_canonical_code():
    """Canonical precedence: the structured signal wins and keeps its code."""
    result = evaluate_issue_readiness(
        _tier_zero_body("Blocked by: #9999"), dependency_blocked=True
    )
    assert result.outcome == ReadinessOutcome.BLOCKED
    check = _dependencies_check(result)
    assert check.status is Status.FAIL
    assert "code=dependency-blocked" in check.evidence
    assert "evidence_source=structured-dependency-signal" in check.evidence
    assert "A required dependency is blocked." in result.report.blockers


def test_b2_injected_clear_supersedes_stale_prose():
    """Injected DependencyState=CLEAR + stale body prose: reconciliation, not BLOCKED."""
    result = evaluate_issue_readiness(
        _tier_zero_body("Blocked by: #9999"), dependency_state_clear=True
    )
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert not result.report.blockers
    check = _dependencies_check(result)
    assert check.status is Status.MANUAL_REVIEW
    assert "code=prose-blocker-superseded-by-canonical-clear" in check.evidence
    assert "evidence_source=body-prose" in check.evidence
    assert any("canonical CLEAR" in item for item in result.report.manual_review_items)


def test_b2_injected_clear_with_canonical_blocked_stays_blocked():
    """Canonical blocked is never softened by the reconciliation rule."""
    result = evaluate_issue_readiness(
        _tier_zero_body("Blocked by: #9999"),
        dependency_blocked=True,
        dependency_state_clear=True,
    )
    assert result.outcome == ReadinessOutcome.BLOCKED
    check = _dependencies_check(result)
    assert "code=dependency-blocked" in check.evidence


def test_b2_prose_blocker_with_needs_decision_field():
    """Needs-decision prose scan: the prose blocker check coexists with the
    needs-decision manual-review signal, and the concrete prose blocker still
    fails closed when no canonical state was injected."""
    result = evaluate_issue_readiness(_tier_zero_body("Blockers: #9999\nOwner: needs-decision"))
    assert result.outcome == ReadinessOutcome.BLOCKED
    check = _dependencies_check(result)
    assert "code=prose-declared-blocker" in check.evidence
    unresolved = [c for c in result.report.checks if c.name == "unresolved decisions"]
    assert unresolved and unresolved[0].status is Status.MANUAL_REVIEW


def test_b2_declared_absence_still_not_a_blocker():
    """Control: 'Blockers: none' remains a declaration of absence."""
    result = evaluate_issue_readiness(_tier_zero_body("Blockers: none"))
    assert result.outcome == ReadinessOutcome.READY
    assert [c for c in result.report.checks if c.name == "dependencies"] == []


def test_b2_labels_path_forwards_injected_clear():
    """The labels-combined path forwards the injected canonical CLEAR."""
    label_report = AcceptanceReport(
        linked_issue=None, overall_status=Status.PASS, checks=[]
    )
    result = evaluate_issue_readiness_with_labels(
        _tier_zero_body("Blocked by: #9999"),
        label_report,
        dependency_state_clear=True,
    )
    assert result.outcome == ReadinessOutcome.NEEDS_DECISION
    assert not result.report.blockers
