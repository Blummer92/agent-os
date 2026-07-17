from pathlib import Path

from scripts.agent_os_issue_acceptance.models import AcceptanceInput, Status
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def _changed(name: str) -> list[str]:
    return [line.strip() for line in _read(name).splitlines() if line.strip()]


def _result(report, name: str):
    return next(check for check in report.checks if check.name == name)


def test_valid_fixture_produces_pass_report():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read("issue_valid.md"),
            pr_body=_read("pr_body_valid.md"),
            changed_files=_changed("changed_files_valid.txt"),
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert report.linked_issue == 164
    assert report.overall_status == Status.PASS
    assert all(check.status == Status.PASS for check in report.checks)


def test_missing_linked_issue_fails():
    report = evaluate_acceptance(
        AcceptanceInput(
            issue_body=_read("issue_valid.md"),
            pr_body=_read("pr_body_missing_report_fields.md"),
            changed_files=_changed("changed_files_valid.txt"),
            diff_text=_read("diff_clean.patch"),
        )
    )

    assert _result(report, "linked issue").status == Status.FAIL
    assert report.overall_status == Status.FAIL


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
