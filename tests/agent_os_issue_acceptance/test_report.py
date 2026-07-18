from pathlib import Path

from scripts.agent_os_issue_acceptance.models import (
    AcceptanceInput,
    AcceptanceReport,
    CheckResult,
    Status,
)
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance
from scripts.agent_os_issue_acceptance.report import exit_code_for, render_report

FIXTURES = Path(__file__).parent / "fixtures"


def test_render_report_contains_ia1_schema_fields():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=(FIXTURES / "issue_valid.md").read_text(),
            pr_body=(FIXTURES / "pr_body_valid.md").read_text(),
            changed_files=[line.strip() for line in (FIXTURES / "changed_files_valid.txt").read_text().splitlines() if line.strip()],
            diff_text=(FIXTURES / "diff_clean.patch").read_text(),
        )
    )

    rendered = render_report(report)

    assert "Issue Acceptance Report" in rendered
    assert "Linked issue: #164" in rendered
    assert "Overall result: pass" in rendered
    assert "Manual review items:" in rendered
    assert "Remaining risks:" in rendered


def test_render_report_exact_output_is_backward_compatible():
    report = AcceptanceReport(
        linked_issue=243,
        overall_status=Status.WARN,
        checks=[
            CheckResult(
                name="registry evidence",
                status=Status.PASS,
                message="five records verified",
                evidence=["records=5"],
            )
        ],
        manual_review_items=["confirm temporary consumer exemption"],
        evidence=["registry_version=0.1.0"],
        blockers=[],
        remaining_risks=["Registry evidence does not authorize merge."],
    )

    assert render_report(report) == (
        "Issue Acceptance Report\n"
        "Linked issue: #243\n"
        "Overall result: warn\n"
        "Checks:\n"
        "- registry evidence: pass - five records verified\n"
        "  - evidence: records=5\n"
        "Manual review items:\n"
        "- confirm temporary consumer exemption\n"
        "Evidence:\n"
        "- registry_version=0.1.0\n"
        "Blockers:\n"
        "- none\n"
        "Remaining risks:\n"
        "- Registry evidence does not authorize merge.\n"
    )


def test_exit_code_is_nonzero_only_for_fail():
    assert exit_code_for(Status.PASS) == 0
    assert exit_code_for(Status.WARN) == 0
    assert exit_code_for(Status.MANUAL_REVIEW) == 0
    assert exit_code_for(Status.FAIL) == 1
