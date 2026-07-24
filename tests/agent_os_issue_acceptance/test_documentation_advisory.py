from scripts.agent_os_issue_acceptance.acceptance_report_transport import (
    build_acceptance_report_transport,
)
from scripts.agent_os_issue_acceptance.documentation_advisory import (
    attach_documentation_advisory,
)
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    IssueMetadata,
    Status,
)
from scripts.agent_os_issue_acceptance.report import render_report


def _report(status=Status.PASS):
    return AcceptanceReport(
        linked_issue=553,
        overall_status=status,
        checks=[
            CheckResult(
                "required docs",
                Status.PASS,
                "covered",
                ["path=README.md"],
            )
        ],
        manual_review_items=["existing manual review"],
        evidence=["existing evidence"],
        blockers=["existing blocker"],
        remaining_risks=["existing risk"],
    )


def _metadata(**overrides):
    values = dict(
        present=True,
        owner_agent="qa-test-agent",
        required_docs=["scripts/agent_os_issue_acceptance/README.md"],
        documentation_impact="docs-required",
        documentation_expected_change="Document the advisory.",
    )
    values.update(overrides)
    return IssueMetadata(**values)


def _transport(report, workflow_run_id="1"):
    return build_acceptance_report_transport(
        report=report,
        repository="Blummer92/agent-os",
        issue_number=553,
        issue_body="",
        issue_body_sha256="",
        pr_number=556,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=1,
        fresh_issue_body="",
        fresh_pr_head_sha="pr-head-sha",
        observed_at="2026-07-24T00:00:00Z",
    )


def test_docs_required_adds_bounded_advisory_without_changing_decisions():
    report = _report()
    result = attach_documentation_advisory(report, _metadata())

    assert result is not report
    assert result.linked_issue == report.linked_issue
    assert result.overall_status == report.overall_status
    assert result.checks == report.checks
    assert result.manual_review_items == report.manual_review_items
    assert result.blockers == report.blockers
    assert result.evidence[-8:] == [
        "documentation_advisory=present",
        "declared_owner_agent=qa-test-agent",
        "required_docs_count=1",
        "required_docs_coverage_status=pass",
        "expected_change_present=true",
        "ownership_verification=human-review-required",
        "semantic_relevance_verification=human-review-required",
        "authorization=advisory-only-not-readiness-write-or-merge",
    ]
    assert result.remaining_risks[-1] == (
        "Declared documentation ownership, semantic relevance, and sufficiency "
        "require human review."
    )


def test_docs_not_required_returns_fresh_equal_report():
    report = _report()
    result = attach_documentation_advisory(
        report,
        _metadata(documentation_impact="docs-not-required"),
    )

    assert result == report
    assert result is not report
    assert result.evidence is not report.evidence
    assert result.checks is not report.checks
    assert result.checks[0].evidence is not report.checks[0].evidence
    assert render_report(result) == render_report(report)


def test_advisory_evidence_changes_report_hash_but_run_identity_does_not():
    report = _report()
    advisory = attach_documentation_advisory(report, _metadata())

    base_transport = _transport(report)
    advisory_transport = _transport(advisory)
    rerun_transport = _transport(advisory, workflow_run_id="2")

    assert base_transport.report_sha256 != advisory_transport.report_sha256
    assert advisory_transport.report_sha256 == rerun_transport.report_sha256


def test_missing_or_unsafe_metadata_is_conservative_and_bounded():
    sentinel = "DO-NOT-LEAK\n" + "x" * 5000
    result = attach_documentation_advisory(
        _report(Status.MANUAL_REVIEW),
        _metadata(
            present=False,
            owner_agent=sentinel,
            required_docs=[],
            documentation_impact=None,
            documentation_expected_change=sentinel,
        ),
    )

    rendered = "\n".join([*result.evidence, *result.remaining_risks])
    assert sentinel not in rendered
    assert "declared_owner_agent=invalid" in result.evidence
    assert "required_docs_count=0" in result.evidence
    assert "expected_change_present=true" in result.evidence
    assert result.overall_status == Status.MANUAL_REVIEW


def test_missing_or_ambiguous_required_docs_check_reports_missing():
    report = _report()
    report.checks.clear()
    missing = attach_documentation_advisory(report, _metadata())
    assert "required_docs_coverage_status=missing" in missing.evidence

    duplicate_report = _report()
    duplicate_report.checks.append(
        CheckResult("required docs", Status.FAIL, "duplicate")
    )
    duplicate = attach_documentation_advisory(duplicate_report, _metadata())
    assert "required_docs_coverage_status=missing" in duplicate.evidence


def test_repeated_inputs_are_deterministic_and_deduplicated():
    report = _report()
    metadata = _metadata()
    first = attach_documentation_advisory(report, metadata)
    second = attach_documentation_advisory(report, metadata)
    repeated = attach_documentation_advisory(first, metadata)

    assert first == second
    assert repeated == first
    assert repeated.evidence.count("documentation_advisory=present") == 1
    assert repeated.remaining_risks.count(
        "Declared documentation ownership, semantic relevance, and sufficiency "
        "require human review."
    ) == 1


def test_adapter_does_not_mutate_or_alias_inputs():
    report = _report()
    original_evidence = list(report.evidence)
    original_check_evidence = list(report.checks[0].evidence)

    result = attach_documentation_advisory(report, _metadata())
    result.evidence.append("result only")
    result.checks[0].evidence.append("result check only")

    assert report.evidence == original_evidence
    assert report.checks[0].evidence == original_check_evidence
