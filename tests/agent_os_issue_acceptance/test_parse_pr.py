from pathlib import Path

from scripts.agent_os_issue_acceptance.parse_pr import (
    missing_final_report_fields,
    parse_linked_issue,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_linked_issue_from_closing_keyword():
    body = (FIXTURES / "pr_body_valid.md").read_text()

    assert parse_linked_issue(body) == 164


def test_missing_linked_issue_returns_none():
    body = (FIXTURES / "pr_body_missing_report_fields.md").read_text()

    assert parse_linked_issue(body) is None


def test_required_final_report_fields_present():
    body = (FIXTURES / "pr_body_valid.md").read_text()

    assert missing_final_report_fields(body) == []


def test_required_final_report_fields_missing():
    body = (FIXTURES / "pr_body_missing_report_fields.md").read_text()

    assert "linked issue" in missing_final_report_fields(body)
    assert "tests run" in missing_final_report_fields(body)
