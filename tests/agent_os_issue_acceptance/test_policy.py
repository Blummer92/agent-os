from pathlib import Path

from scripts.agent_os_issue_acceptance.models import AcceptanceInput, LinkedIssueParseStatus, Status
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def _changed(name: str) -> list[str]:
    return [line.strip() for line in _read(name).splitlines() if line.strip()]


def _result(report, name: str):
    return next(check for check in report.checks if check.name == name)


def _input(pr_body: str) -> AcceptanceInput:
    return AcceptanceInput(
        issue_body=_read("issue_valid.md"),
        pr_body=pr_body,
        changed_files=_changed("changed_files_valid.txt"),
        diff_text=_read("diff_clean.patch"),
    )


def test_valid_fixture_produces_pass_report():
    report = evaluate_acceptance(_input(_read("pr_body_valid.md")))

    assert report.linked_issue == 164
    assert report.linked_issue_result.status == LinkedIssueParseStatus.RESOLVED
    assert report.overall_status == Status.PASS
    assert all(check.status == Status.PASS for check in report.checks)
    assert "issueplan_scan_finding=metadata-single" in report.evidence


def test_missing_linked_issue_fails_and_remains_distinct_from_ambiguity():
    report = evaluate_acceptance(_input(_read("pr_body_missing_report_fields.md")))

    assert _result(report, "linked issue").status == Status.FAIL
    assert report.linked_issue_result.status == LinkedIssueParseStatus.NONE
    assert report.overall_status == Status.FAIL


def test_ambiguous_linked_issue_requires_manual_review():
    body = _read("pr_body_valid.md").replace("Closes #164", "Closes #223\nFixes #224")
    report = evaluate_acceptance(_input(body))

    assert report.linked_issue is None
    assert report.linked_issue_result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert _result(report, "linked issue").status == Status.MANUAL_REVIEW
    assert report.overall_status == Status.MANUAL_REVIEW
    assert any(item.startswith("Linked issue:") for item in report.manual_review_items)


def test_bare_only_linked_issue_requires_manual_review():
    body = _read("pr_body_valid.md").replace("Closes #164", "Related to #164")
    report = evaluate_acceptance(_input(body))

    assert report.linked_issue_result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert report.overall_status == Status.MANUAL_REVIEW


def test_required_files_missing_fails():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read("issue_valid.md"),
            pr_body=_read("pr_body_valid.md"),
            changed_files=["tests/agent_os_issue_acceptance/test_policy.py"],
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert _result(report, "required files").status == Status.FAIL


def test_forbidden_paths_violated_fails():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read("issue_valid.md"),
            pr_body=_read("pr_body_valid.md"),
            changed_files=_changed("changed_files_forbidden_path.txt"),
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert _result(report, "forbidden paths").status == Status.FAIL


def test_required_docs_missing_fails():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read("issue_valid.md"),
            pr_body=_read("pr_body_valid.md"),
            changed_files=[
                "scripts/agent_os_issue_acceptance/policy.py",
                "tests/agent_os_issue_acceptance/test_policy.py",
            ],
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert _result(report, "required docs").status == Status.FAIL


def test_required_tests_can_be_satisfied_by_pr_report():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read("issue_valid.md"),
            pr_body=_read("pr_body_valid.md"),
            changed_files=[
                "scripts/agent_os_issue_acceptance/policy.py",
                "scripts/agent_os_issue_acceptance/README.md",
            ],
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert _result(report, "required tests").status == Status.PASS


def test_banned_pattern_detection_fails():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read("issue_valid.md"),
            pr_body=_read("pr_body_valid.md"),
            changed_files=_changed("changed_files_valid.txt"),
            diff_text=_read("diff_with_banned_import.patch"),
        )
    )

    assert _result(report, "banned patterns").status == Status.FAIL


def test_missing_metadata_requires_manual_review():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read("issue_missing_metadata.md"),
            pr_body=_read("pr_body_valid.md"),
            changed_files=_changed("changed_files_valid.txt"),
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert report.overall_status == Status.MANUAL_REVIEW
    assert _result(report, "required files").status == Status.MANUAL_REVIEW
    assert "issueplan_scan_finding=metadata-missing" in report.evidence
    assert "Issue metadata block is missing." in report.manual_review_items


def test_malformed_metadata_is_not_normalized_to_missing():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body="```yaml\nagent_os_issue_acceptance: [\n```",
            pr_body=_read("pr_body_valid.md"),
            changed_files=_changed("changed_files_valid.txt"),
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert report.overall_status == Status.MANUAL_REVIEW
    assert "issueplan_scan_finding=metadata-malformed" in report.evidence
    assert "issueplan-scanner:metadata-malformed" in report.manual_review_items
    assert "Issue metadata block is missing." not in report.manual_review_items


def test_duplicate_and_conflicting_candidates_remain_distinct():
    first = "```yaml\nagent_os_issue_acceptance:\n  owner_agent: qa-test-agent\n```"
    duplicate = evaluate_acceptance(
        AcceptanceInput(
            issue_body=f"{first}\n{first}",
            pr_body=_read("pr_body_valid.md"),
            changed_files=_changed("changed_files_valid.txt"),
            diff_text=_read("diff_clean.patch"),
        )
    )
    conflict = evaluate_acceptance(
        AcceptanceInput(
            issue_body=(
                f"{first}\n```yaml\nagent_os_issue_acceptance:\n"
                "  owner_agent: integration-manager\n```"
            ),
            pr_body=_read("pr_body_valid.md"),
            changed_files=_changed("changed_files_valid.txt"),
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert "issueplan_scan_finding=metadata-duplicated-identical" in duplicate.evidence
    assert "issueplan_scan_finding=metadata-conflicting" in conflict.evidence
    assert duplicate.overall_status == Status.MANUAL_REVIEW
    assert conflict.overall_status == Status.MANUAL_REVIEW
