"""Lane A (#3506) red/green tests for the QA-report E2/E4/E8 false passes.

Scenarios are the ones reproduced in QA-REPORT-satisfaction-gate.md §5-6:
prose test mentions, negated validation statements, green-wrapper masking
(at the checker level: a failing report must keep a non-zero exit code),
and report-only evaluation of unambiguously non-closing PRs.
"""
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import AcceptanceInput, LinkedIssueParseStatus, Status
from scripts.agent_os_issue_acceptance.parse_pr import (
    has_validation_command,
    parse_linked_issue_result,
    report_only_issue_number,
)
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance
from scripts.agent_os_issue_acceptance.report import exit_code_for

FIXTURES = Path(__file__).parent / "fixtures"

def _read(name): return (FIXTURES/name).read_text()
def _result(report, name): return next(c for c in report.checks if c.name==name)

def test_prose_pytest_mention_is_not_a_validation_command():
    assert has_validation_command("We discussed pytest as an option for this change.") is False
    assert has_validation_command("Mentions of pytest appear in the linked issue.") is False

def test_negated_validation_statement_is_not_a_validation_command():
    assert has_validation_command("## Tests run\n\n- No pytest run was performed.\n") is False
    assert has_validation_command("- pytest was not run\n") is False
    assert has_validation_command("No tests ran; pytest was not performed.") is False

def test_command_shaped_validation_counts():
    assert has_validation_command("- python -m pytest tests/agent_os_issue_acceptance -q\n") is True
    assert has_validation_command("./scripts/validate-all.sh --focused tests/x.py\n") is True
    assert has_validation_command("pytest tests/ -q\n") is True

def test_e2e_defective_pr_with_prose_evidence_does_not_pass():
    # Breaks required behaviour, changes no required test, says no tests ran.
    body = _read("pr_body_valid.md").replace(
        "- python -m pytest tests/agent_os_issue_acceptance\n- ./scripts/validate-all.sh\n",
        "No pytest run was performed. tests/agent_os_issue_acceptance/ is mentioned here only.\n",
    )
    report = evaluate_acceptance(AcceptanceInput(
        issue_body=_read("issue_valid.md"), pr_body=body,
        changed_files=["scripts/agent_os_issue_acceptance/policy.py","scripts/agent_os_issue_acceptance/README.md"],
        diff_text=_read("diff_clean.patch")))
    assert report.overall_status != Status.PASS
    assert _result(report, "required tests").status == Status.MANUAL_REVIEW
    assert _result(report, "validation commands").status != Status.PASS
    assert report.overall_status == Status.MANUAL_REVIEW  # not PASS; exit-code masking is the workflow-gated E3 issue

def test_fail_report_exit_code_is_nonzero():
    # E3 checker-level invariant: a failed acceptance report cannot be
    # represented as success by the checker itself. (The workflow step
    # that masks this exit code is a separate, owner-gated change --
    # see the prepared workflow patch in the campaign report.)
    assert exit_code_for(Status.FAIL) != 0
    assert exit_code_for(Status.PASS) == 0

def test_report_only_number_for_unambiguous_non_closing():
    body = "## Linked issue\n\nPart of #3506\n\nNon-closing: #3506\n"
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.INFORMATIONAL
    assert result.issue_number is None  # never a closure resolution
    assert report_only_issue_number(result) == 3506

def test_report_only_number_ambiguous_non_closing_is_none():
    body = "Part of #3506 and #3489\n\nNon-closing: #3506, #3489\n"
    result = parse_linked_issue_result(body)
    assert result.status == LinkedIssueParseStatus.INFORMATIONAL
    assert report_only_issue_number(result) is None

def test_report_only_number_for_closing_is_resolved_issue():
    result = parse_linked_issue_result("Closes #3506\n")
    assert report_only_issue_number(result) == 3506

# --- Independent QA bypass set (2026-10-22 re-QA): non-performance and
# prose-subject phrasings that a first repair draft still accepted. ---
import pytest as _pytest

@_pytest.mark.parametrize("line", [
    "pytest was skipped", "pytest skipped", "validate-all.sh was skipped",
    "cloudbuild was skipped", "pytest has not been run",
    "pytest hasn't been run", "pytest didn't run",
    "python -m pytest hasn't been run", "pytest not actually run",
    "pytest not yet run", "pytest will be run later",
    "pytest to be run later", "pytest should be run",
    "pytest documentation was reviewed in this PR",
    "pytest is a testing framework for Python",
    "cloudbuild is mentioned in the docs",
    "validate-all.sh is documented in the README",
    "gcloud builds are discussed in the plan",
])
def test_qa_bypass_lines_are_not_validation_commands(line):
    assert has_validation_command(line) is False

@_pytest.mark.parametrize("line", [
    "- python -m pytest tests/agent_os_issue_acceptance -q",
    "./scripts/validate-all.sh --focused tests/x.py",
    "pytest tests/ -q", "- ./scripts/validate-all.sh",
    "Run: pytest tests/unit", "pytest tests",
    "gcloud builds submit --config cloudbuild.yaml",
])
def test_genuine_command_shapes_still_count(line):
    assert has_validation_command(line) is True

# --- Re-QA bypass set RB-1/RB-2/RB-3 (2026-10-22): plain-word remainders,
# shorthand-token early-accept, and hyphenated negations. ---
@_pytest.mark.parametrize("line", [
    "pytest pending", "pytest omitted", "pytest deferred", "pytest cancelled",
    "pytest tomorrow", "validate-all.sh pending", "python -m pytest pending",
    "gcloud builds pending", "pytest tests are pending execution",
    "pytest tests won't run", "pytest tests aren't run",
    "pytest tests wasn't executed", "pytest tests will be executed tomorrow",
    "pytest tests are discussed in the notes", "pytest not-run",
    "pytest non-run", "pytest test-suite is pending",
])
def test_reqa_bypass_lines_are_not_validation_commands(line):
    assert has_validation_command(line) is False

# --- M02 bypass set (mutation-escape repair, 2026-10-22): a
# non-execution claim encoded purely as path segments. The v3 grammar
# exempted every path/file token from the negation scan, so each line
# below returned True on the #3706 head (and on main, whose matcher is
# a bare substring check). Extensionless path segments carrying a
# non-execution stem are now negation claims. ---
@_pytest.mark.parametrize("line", [
    # The four exact M02 strings.
    "pytest abandoned/dropped/ignored/waived",
    "pytest tests/never executed/ok",
    "pytest tests/waived/ok",
    "pytest tests/unrun/ok",
    # Single-word / path-segment variants of the same class.
    "pytest waived", "pytest tests/waived", "pytest dropped/ok",
    "pytest ignored", "pytest abandoned",
    "pytest tests/abandoned/ok", "pytest tests/dropped/ok",
    "pytest tests/ignored/ok", "pytest tests/never/ok",
    "pytest never/run", "pytest tests/not-run/ok",
    "pytest tests/skipped/ok", "pytest tests/blocked/ok",
    "pytest tests/incomplete/ok",
    # A negated directory segment stays a negation even when a real
    # filename follows it.
    "pytest tests/waived/test_x.py", "pytest tests/never-run/test_x.py",
])
def test_m02_path_segment_bypass_lines_are_not_validation_commands(line):
    assert has_validation_command(line) is False

@_pytest.mark.parametrize("line", [
    "pytest tests/test_parse_pr.py",
    "pytest tests/test_x.py::test_y -q",
    # Tradeoff controls: a filename whose *topic* is negation is a
    # concrete file target, not a non-execution claim, and must still
    # count -- including a node-id naming a negation-topic test.
    "pytest tests/test_non_run.py", "pytest tests/test_skipped_case.py",
    "pytest tests/test_waived_flag.py -q",
    "pytest tests/test_x.py::test_waived_case",
])
def test_m02_filename_topic_controls_still_count(line):
    assert has_validation_command(line) is True
