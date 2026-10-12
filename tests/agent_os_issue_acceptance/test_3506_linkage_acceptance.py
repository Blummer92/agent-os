"""#3506 linkage-acceptance tests (Slice 2a+2b).

Part A: the transport reason-code split — `no-authoritative-linkage` vs
`missing-provenance` — with fail-closed semantics unchanged.
Part B: intentional non-closing linkage via an explicit `Non-closing:` directive,
which yields INFORMATIONAL (never an issue_number) without weakening any
fail-closed behavior.
"""

import hashlib
from pathlib import Path

from scripts.agent_os_issue_acceptance.acceptance_report_transport import (
    build_acceptance_report_transport,
)
from scripts.agent_os_issue_acceptance.checks import linked_issue as linked_issue_check
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceInput,
    AcceptanceReport,
    LinkedIssueCandidate,
    LinkedIssueParseResult,
    LinkedIssueParseStatus,
    Status,
)
from scripts.agent_os_issue_acceptance.parse_pr import (
    parse_linked_issue,
    parse_linked_issue_result,
)
from scripts.agent_os_issue_acceptance.policy import evaluate_acceptance

FIXTURES = Path(__file__).parent / "fixtures"

OBSERVED_AT = "2026-10-12T00:00:00Z"


def _bare(number: int) -> LinkedIssueCandidate:
    return LinkedIssueCandidate(
        issue_number=number,
        repository=None,
        keyword=None,
        source="body",
        position=0,
        raw_target=f"#{number}",
        explicit=False,
    )


def _manual_review_result() -> LinkedIssueParseResult:
    return LinkedIssueParseResult(
        status=LinkedIssueParseStatus.MANUAL_REVIEW,
        bare_references=[_bare(3372)],
        reasons=["Only non-authoritative issue references were detected: #3372."],
    )


def _transport(*, report, issue_number, issue_body_retrieval_failed=False, pr_head_sha="pr-head-sha", fresh=True):
    fresh_kwargs = (
        {"fresh_issue_body": "Issue body", "fresh_pr_head_sha": "pr-head-sha"}
        if fresh
        else {}
    )
    return build_acceptance_report_transport(
        report=report,
        repository="Blummer92/agent-os",
        issue_number=issue_number,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=42,
        pr_head_sha=pr_head_sha,
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        observed_at=OBSERVED_AT,
        issue_body_retrieval_failed=issue_body_retrieval_failed,
        **fresh_kwargs,
    )


# ---------------------------------------------------------------------------
# Part A: reason-code split
# ---------------------------------------------------------------------------


def test_authoritative_link_ok_is_snapshot_current():
    report = AcceptanceReport(
        linked_issue=323,
        overall_status=Status.PASS,
        checks=[],
        linked_issue_result=LinkedIssueParseResult(
            status=LinkedIssueParseStatus.RESOLVED, issue_number=323
        ),
    )
    transport = _transport(report=report, issue_number=323)

    assert transport.transport_state == "snapshot-current"
    assert transport.reason_codes == ()
    assert transport.execution_authorized is False


def test_non_authoritative_link_emits_no_authoritative_linkage():
    report = AcceptanceReport(
        linked_issue=None,
        overall_status=Status.MANUAL_REVIEW,
        checks=[],
        linked_issue_result=_manual_review_result(),
    )
    transport = _transport(report=report, issue_number=None)

    assert transport.transport_state == "no-authoritative-linkage"
    assert transport.reason_codes == ("no-authoritative-linkage",)
    assert transport.to_envelope()["issueplan_current_state_evidence_id"] == ""
    assert transport.execution_authorized is False


def test_attempted_readback_failed_stays_missing_provenance():
    report = AcceptanceReport(
        linked_issue=None,
        overall_status=Status.MANUAL_REVIEW,
        checks=[],
        linked_issue_result=_manual_review_result(),
    )
    transport = _transport(
        report=report, issue_number=None, issue_body_retrieval_failed=True
    )

    assert transport.transport_state == "missing-provenance"
    assert transport.reason_codes == ("missing-provenance",)


def test_missing_inputs_stay_missing_provenance():
    report = AcceptanceReport(
        linked_issue=None, overall_status=Status.FAIL, checks=[], linked_issue_result=None
    )
    transport = _transport(report=report, issue_number=None, pr_head_sha="")

    assert transport.transport_state == "missing-provenance"
    assert transport.reason_codes == ("missing-provenance",)


def test_manual_review_with_explicit_candidates_stays_missing_provenance():
    # MANUAL_REVIEW arising from repository-qualified explicit targets is not
    # "only non-authoritative references": it keeps the legacy code.
    report = AcceptanceReport(
        linked_issue=None,
        overall_status=Status.MANUAL_REVIEW,
        checks=[],
        linked_issue_result=LinkedIssueParseResult(
            status=LinkedIssueParseStatus.MANUAL_REVIEW,
            explicit_candidates=[
                LinkedIssueCandidate(
                    issue_number=1,
                    repository="other/repo",
                    keyword="closes",
                    source="body",
                    position=0,
                    raw_target="other/repo#1",
                    explicit=True,
                )
            ],
            reasons=["Repository-qualified linked issues are not supported end-to-end."],
        ),
    )
    transport = _transport(report=report, issue_number=None)

    assert transport.transport_state == "missing-provenance"
    assert transport.reason_codes == ("missing-provenance",)


# ---------------------------------------------------------------------------
# Part B: parser negatives
# ---------------------------------------------------------------------------


def test_closing_keyword_anywhere_is_not_informational():
    # Inline (non-line-start) closing keyword: not an explicit directive, but
    # the #3157 GitHub-effective detector still sees it.
    body = "Please fix #200 when you can.\nRefs #3372\nNon-closing: #3372"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert parse_linked_issue(body) is None


def test_directive_contradicting_explicit_close_is_manual_review():
    body = "Closes #3372\nNon-closing: #3372"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert parse_linked_issue(body) is None
    assert any("contradict" in reason for reason in result.reasons)


def test_bare_ref_without_directive_is_unchanged_manual_review():
    body = "Refs #3372"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert parse_linked_issue(body) is None


def test_negated_prose_with_directive_is_still_manual_review():
    # #3157: GitHub treats negated closing prose as closing-looking.
    body = "This does not close #3372.\nRefs #3372\nNon-closing: #3372"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert parse_linked_issue(body) is None


def test_dangling_directive_is_manual_review():
    body = "Non-closing: #9999"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert parse_linked_issue(body) is None


def test_undeclared_bare_reference_is_manual_review():
    body = "Refs #3372, see also #3281\nNon-closing: #3372"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW
    assert parse_linked_issue(body) is None


def test_directive_inside_code_fence_is_not_honored():
    body = "```\nNon-closing: #3372\n```\nRefs #3372"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.MANUAL_REVIEW


# ---------------------------------------------------------------------------
# Part B: positives
# ---------------------------------------------------------------------------


def test_declared_non_closing_is_informational():
    body = "Refs #3372\nNon-closing: #3372"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.INFORMATIONAL
    assert result.issue_number is None
    assert parse_linked_issue(body) is None


def test_declared_non_closing_multiple_targets():
    body = "Refs #3372 and #3281\nNon-closing: #3372, #3281"
    result = parse_linked_issue_result(body)

    assert result.status == LinkedIssueParseStatus.INFORMATIONAL
    assert parse_linked_issue(body) is None


def test_informational_check_passes_and_policy_adds_no_review_items():
    pr_body = (FIXTURES / "pr_body_valid.md").read_text().replace(
        "Closes #164", "Refs #164\nNon-closing: #164"
    )
    data = AcceptanceInput(
        issue_body=(FIXTURES / "issue_valid.md").read_text(),
        pr_body=pr_body,
        changed_files=[
            line.strip()
            for line in (FIXTURES / "changed_files_valid.txt").read_text().splitlines()
            if line.strip()
        ],
        diff_text=(FIXTURES / "diff_clean.patch").read_text(),
    )
    report = evaluate_acceptance(data)

    assert report.linked_issue_result.status == LinkedIssueParseStatus.INFORMATIONAL
    assert report.linked_issue is None
    check = next(c for c in report.checks if c.name == "linked issue")
    assert check.status == Status.PASS
    assert not any(item.startswith("Linked issue:") for item in report.manual_review_items)
    assert report.overall_status == Status.PASS


def test_informational_transport_state():
    pr_body = (FIXTURES / "pr_body_valid.md").read_text().replace(
        "Closes #164", "Refs #164\nNon-closing: #164"
    )
    data = AcceptanceInput(
        issue_body=(FIXTURES / "issue_valid.md").read_text(),
        pr_body=pr_body,
        changed_files=[
            line.strip()
            for line in (FIXTURES / "changed_files_valid.txt").read_text().splitlines()
            if line.strip()
        ],
        diff_text=(FIXTURES / "diff_clean.patch").read_text(),
    )
    report = evaluate_acceptance(data)
    transport = _transport(report=report, issue_number=None)

    assert transport.transport_state == "non-closing-linkage-declared"
    assert transport.reason_codes == ("non-closing-linkage-declared",)
    assert transport.result_status == Status.PASS.value
    assert transport.execution_authorized is False


def test_informational_check_result_shape():
    result = parse_linked_issue_result("Refs #3372\nNon-closing: #3372")
    check = linked_issue_check.check(
        pr_body="Refs #3372\nNon-closing: #3372", parse_result=result
    )

    assert check.name == "linked issue"
    assert check.status == Status.PASS
    assert "non-closing" in check.message
