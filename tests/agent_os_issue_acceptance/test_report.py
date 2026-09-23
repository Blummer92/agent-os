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


def _input(pr_body: str) -> AcceptanceInput:
    return AcceptanceInput(
        issue_body=(FIXTURES / "issue_valid.md").read_text(),
        pr_body=pr_body,
        changed_files=[
            line.strip()
            for line in (FIXTURES / "changed_files_valid.txt").read_text().splitlines()
            if line.strip()
        ],
        diff_text=(FIXTURES / "diff_clean.patch").read_text(),
    )


def test_render_report_contains_ia1_schema_fields():
    report = evaluate_acceptance(_input((FIXTURES / "pr_body_valid.md").read_text()))
    rendered = render_report(report)

    assert "Issue Acceptance Report" in rendered
    assert "Linked issue: #164" in rendered
    assert "Linked issue status: resolved" in rendered
    assert "Overall result: pass" in rendered
    assert "Manual review items:" in rendered
    assert "Remaining risks:" in rendered


def test_render_report_does_not_show_ambiguous_candidate_as_linked_issue():
    body = (FIXTURES / "pr_body_valid.md").read_text().replace(
        "Closes #164", "Closes #223\nFixes #224"
    )
    rendered = render_report(evaluate_acceptance(_input(body)))

    assert "Linked issue: unresolved" in rendered
    assert "Linked issue status: manual-review" in rendered
    assert "Linked issue: #223" not in rendered


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
        "Linked issue status: resolved\n"
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


def _report_with(informational):
    return AcceptanceReport(
        linked_issue=243,
        overall_status=Status.WARN,
        checks=[CheckResult("registry evidence", Status.PASS, "ok", ["records=5"])],
        manual_review_items=[],
        evidence=[],
        blockers=[],
        remaining_risks=["Registry evidence does not authorize merge."],
        informational_checks=informational,
    )


def test_empty_informational_checks_render_byte_for_byte_legacy_output():
    # Adding the defaulted field but leaving it empty must not change the output.
    empty = _report_with(())
    assert "Reusable-capability evidence" not in render_report(empty)
    assert render_report(empty) == (
        "Issue Acceptance Report\n"
        "Linked issue: #243\n"
        "Linked issue status: resolved\n"
        "Overall result: warn\n"
        "Checks:\n"
        "- registry evidence: pass - ok\n"
        "  - evidence: records=5\n"
        "Manual review items:\n"
        "- none\n"
        "Evidence:\n"
        "- none\n"
        "Blockers:\n"
        "- none\n"
        "Remaining risks:\n"
        "- Registry evidence does not authorize merge.\n"
    )


def test_populated_informational_section_renders_after_remaining_risks():
    report = _report_with(
        (
            CheckResult("reuse candidate alpha", Status.PASS, "positive match", ["capability_id=alpha"]),
        )
    )
    rendered = render_report(report)
    tail = rendered.split("Remaining risks:\n- Registry evidence does not authorize merge.\n", 1)[1]
    assert tail == (
        "Reusable-capability evidence (informational):\n"
        "- notice: Reusable-capability evidence is informational only; it does not authorize "
        "implementation, repository writes, readiness changes, or merge, and matching "
        "registry provenance proves only same-snapshot identity, not correctness, "
        "compatibility, ownership, approval, or readiness.\n"
        "- reuse candidate alpha: pass - positive match\n"
        "  - evidence: capability_id=alpha\n"
    )
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")
