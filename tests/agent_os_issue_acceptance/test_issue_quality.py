from pathlib import Path

from scripts.agent_os_issue_acceptance.checks import issue_quality
from scripts.agent_os_issue_acceptance.models import CheckResult, Status


_FIXTURES = Path(__file__).parent / "fixtures" / "issue_quality"


def _strong() -> str:
    return (_FIXTURES / "strong_implementation.md").read_text()


def _result(results, name):
    return next(result for result in results if result.name == name)


def test_strong_implementation_required_sections_pass():
    results = issue_quality.check_completeness(_strong(), issue_quality.IssueFamily.IMPLEMENTATION)
    required = {"goal", "scope", "acceptance criteria", "definition of done", "tests / validation"}
    assert all(
        result.status == Status.PASS
        for result in results
        if result.name.removeprefix("section: ") in required
    )


def test_missing_required_section_fails():
    body = _strong().replace("## Scope\nOnly local issue-body analysis.\n\n", "")
    result = _result(
        issue_quality.check_completeness(body, issue_quality.IssueFamily.IMPLEMENTATION),
        "section: scope",
    )
    assert result.status == Status.FAIL


def test_missing_recommended_section_warns():
    body = _strong().replace("## Handoff notes\nReturn validation evidence.\n\n", "")
    result = _result(
        issue_quality.check_completeness(body, issue_quality.IssueFamily.IMPLEMENTATION),
        "section: handoff notes",
    )
    assert result.status == Status.WARN


def test_empty_required_section_fails():
    body = _strong().replace("## Scope\nOnly local issue-body analysis.", "## Scope\n")
    result = _result(
        issue_quality.check_completeness(body, issue_quality.IssueFamily.IMPLEMENTATION),
        "section: scope",
    )
    assert result.status == Status.FAIL


def test_placeholder_required_section_is_manual_review():
    body = _strong().replace("## Scope\nOnly local issue-body analysis.", "## Scope\nTBD")
    result = _result(
        issue_quality.check_completeness(body, issue_quality.IssueFamily.IMPLEMENTATION),
        "section: scope",
    )
    assert result.status == Status.MANUAL_REVIEW


def test_parent_reference_cases():
    assert issue_quality.check_parent_reference(_strong()).status == Status.PASS
    missing = _strong().replace("## Parent\n#163\n\n", "")
    assert issue_quality.check_parent_reference(missing).status == Status.WARN
    malformed = _strong().replace("## Parent\n#163", "## Parent\nparent roadmap")
    assert issue_quality.check_parent_reference(malformed).status == Status.WARN


def test_related_reference_cases():
    assert issue_quality.check_related_references(_strong()).status == Status.PASS
    missing = _strong().replace("## Related issues\n#164\n\n", "")
    assert issue_quality.check_related_references(missing).status == Status.WARN


def test_blocker_cases():
    assert issue_quality.check_blocker_quality(_strong()).status == Status.PASS
    blocked = _strong().replace("No blockers.", "Blocked until #900 is complete.")
    assert issue_quality.check_blocker_quality(blocked).status == Status.PASS
    ambiguous = _strong().replace("No blockers.", "Currently blocked by upstream work.")
    assert issue_quality.check_blocker_quality(ambiguous).status == Status.MANUAL_REVIEW


def test_missing_required_acceptance_criteria_fails():
    body = _strong().replace(
        "## Acceptance criteria\n- Checker returns pass for complete local input.\n- Checker rejects missing required sections.\n\n",
        "",
    )
    results = issue_quality.check_acceptance_criteria(body, issue_quality.IssueFamily.IMPLEMENTATION)
    assert results == [CheckResult("acceptance criteria", Status.FAIL, "Acceptance criteria are missing.")]


def test_vague_acceptance_criteria_is_manual_review():
    body = _strong().replace(
        "- Checker returns pass for complete local input.\n- Checker rejects missing required sections.",
        "- Make it better.",
    )
    results = issue_quality.check_acceptance_criteria(body, issue_quality.IssueFamily.IMPLEMENTATION)
    assert results[0].status == Status.MANUAL_REVIEW


def test_acceptance_validation_support_warns_when_missing_and_passes_when_present():
    assert issue_quality.check_acceptance_criteria(
        _strong(), issue_quality.IssueFamily.IMPLEMENTATION
    )[1].status == Status.PASS
    body = _strong().replace("## Tests / validation\n- Run focused pytest tests.\n\n", "")
    assert issue_quality.check_acceptance_criteria(
        body, issue_quality.IssueFamily.IMPLEMENTATION
    )[1].status == Status.WARN


def test_roadmap_acceptance_criteria_is_recommended_not_required():
    body = "## Goal\nPlan it.\n## Scope\nBound it.\n## Dependencies\nNone.\n"
    results = issue_quality.check_acceptance_criteria(body, issue_quality.IssueFamily.ROADMAP)
    assert results[0].status == Status.WARN


def test_aggregate_is_deterministic_and_reuses_canonical_models():
    first = issue_quality.check(_strong(), issue_quality.IssueFamily.IMPLEMENTATION)
    second = issue_quality.check(_strong(), issue_quality.IssueFamily.IMPLEMENTATION)
    assert first == second
    assert first
    assert all(type(result) is CheckResult for result in first)
    assert all(type(result.status) is Status for result in first)


def test_checker_source_has_no_io_or_network_dependencies():
    names = set(issue_quality.__dict__)
    assert not names.intersection({"requests", "urllib", "socket", "subprocess", "os", "pathlib"})
