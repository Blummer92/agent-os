import hashlib
import json

from scripts.agent_os_issue_acceptance.acceptance_report_transport import (
    AcceptanceReportTransport,
    build_acceptance_report_transport,
    canonical_json_bytes,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    build_issueplan_current_state_evidence,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import SourceEnvelope, scan_issueplan_source
from scripts.agent_os_issue_acceptance.models import AcceptanceReport, Status


def _build_expected_evidence_id(
    issue_body: str,
    repository: str,
    issue_number: int | None,
    observed_at: str,
) -> str:
    source_revision = hashlib.sha256(issue_body.encode("utf-8")).hexdigest()
    envelope = SourceEnvelope(
        source_locator=f"github:{repository}#{issue_number}" if repository and issue_number is not None else "github:issue-body",
        source_revision=source_revision,
        content=issue_body,
        source_family="github-issue",
        retrieval_complete=True,
        pagination_complete=True,
        accessible=True,
    )
    scan_result = scan_issueplan_source(envelope)
    evidence = build_issueplan_current_state_evidence(
        envelope,
        scan_result,
        observed_at=observed_at,
        freshness_boundary="workflow-summary",
        repository=repository or None,
        base_branch="main",
    )
    return evidence.evidence_id


def _build_report() -> AcceptanceReport:
    return AcceptanceReport(
        linked_issue=323,
        overall_status=Status.PASS,
        checks=[],
        evidence=["doc coverage verified"],
    )


def test_transport_uses_real_issueplan_current_state_evidence_id():
    issue_body = "Issue body"
    observed_at = "2026-07-23T00:00:00Z"
    transport = build_acceptance_report_transport(
        report=_build_report(),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body=issue_body,
        issue_body_sha256=hashlib.sha256(issue_body.encode("utf-8")).hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        observed_at=observed_at,
        fresh_issue_body=issue_body,
        fresh_pr_head_sha="pr-head-sha",
    )

    assert isinstance(transport, AcceptanceReportTransport)
    assert transport.execution_authorized is False
    assert transport.transport_state == "snapshot-current"
    assert transport.reason_codes == ()
    assert transport.to_envelope()["issueplan_current_state_evidence_id"] == _build_expected_evidence_id(
        issue_body, "Blummer92/agent-os", 323, observed_at
    )


def test_transport_reports_missing_provenance_when_rechecks_are_missing():
    transport = build_acceptance_report_transport(
        report=AcceptanceReport(linked_issue=323, overall_status=Status.MANUAL_REVIEW, checks=[]),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body=None,
        fresh_pr_head_sha="pr-head-sha",
    )

    assert transport.transport_state == "missing-provenance"
    assert transport.reason_codes == ("missing-provenance",)
    assert transport.to_envelope()["issueplan_current_state_evidence_id"] == ""


def test_transport_treats_successful_empty_body_as_valid_retrieval():
    transport = build_acceptance_report_transport(
        report=_build_report(),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="",
        issue_body_sha256=hashlib.sha256(b"").hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body="",
        fresh_pr_head_sha="pr-head-sha",
    )

    assert transport.transport_state == "snapshot-current"
    assert transport.reason_codes == ()
    assert transport.to_envelope()["issueplan_current_state_evidence_id"]


def test_transport_derives_digest_from_captured_body_when_supplied_digest_is_wrong():
    issue_body = "Issue body\n"
    transport = build_acceptance_report_transport(
        report=_build_report(),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body=issue_body,
        issue_body_sha256="deadbeef",
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body=issue_body,
        fresh_pr_head_sha="pr-head-sha",
    )

    assert transport.to_envelope()["issue_body_sha256"] == hashlib.sha256(issue_body.encode("utf-8")).hexdigest()


def test_transport_report_sha256_is_independent_of_workflow_identity():
    base = build_acceptance_report_transport(
        report=_build_report(),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="1",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body="Issue body",
        fresh_pr_head_sha="pr-head-sha",
    )
    changed_identity = build_acceptance_report_transport(
        report=_build_report(),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="2",
        workflow_run_attempt=2,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body="Issue body",
        fresh_pr_head_sha="pr-head-sha",
    )

    assert base.report_sha256 == changed_identity.report_sha256


def test_transport_report_sha256_changes_when_report_changes():
    base = build_acceptance_report_transport(
        report=_build_report(),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="1",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body="Issue body",
        fresh_pr_head_sha="pr-head-sha",
    )
    changed_report = _build_report()
    changed_report.evidence.append("new evidence")
    changed = build_acceptance_report_transport(
        report=changed_report,
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="1",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body="Issue body",
        fresh_pr_head_sha="pr-head-sha",
    )

    assert base.report_sha256 != changed.report_sha256


def test_transport_prefers_stale_pr_head_over_stale_issue():
    transport = build_acceptance_report_transport(
        report=_build_report(),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body="different-issue-body",
        fresh_pr_head_sha="different-pr-head",
    )

    assert transport.transport_state == "stale-pr-head"
    assert transport.reason_codes == ("stale-pr-head", "stale-issue")


def test_transport_envelope_is_bounded_and_canonical():
    transport = build_acceptance_report_transport(
        report=_build_report(),
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body="Issue body",
        fresh_pr_head_sha="pr-head-sha",
    )

    payload = transport.to_envelope()
    assert len(canonical_json_bytes(payload)) <= 64 * 1024
    assert json.loads(json.dumps(payload, sort_keys=True, separators=(",", ":"))) == payload
