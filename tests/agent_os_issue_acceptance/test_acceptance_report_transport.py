import hashlib
import json

from scripts.agent_os_issue_acceptance.acceptance_report_transport import (
    AcceptanceReportTransport,
    build_acceptance_report_transport,
    canonical_json_bytes,
    render_transport_summary,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    build_issueplan_current_state_evidence,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import SourceEnvelope, scan_issueplan_source
from scripts.agent_os_issue_acceptance.models import AcceptanceReport, Status


def _build_expected_evidence_id(issue_body: str, repository: str, issue_number: int | None) -> str:
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
        observed_at="2026-07-23T00:00:00Z",
        freshness_boundary="workflow-summary",
        repository=repository or None,
        base_branch="main",
        evaluated_repository_sha="a" * 40,
        implementation_contract_fingerprint="b" * 64,
    )
    return evidence.evidence_id


def test_transport_uses_real_issueplan_current_state_evidence_id():
    report = AcceptanceReport(
        linked_issue=323,
        overall_status=Status.PASS,
        checks=[],
        evidence=["doc coverage verified"],
    )
    issue_body = "Issue body"
    transport = build_acceptance_report_transport(
        report=report,
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body=issue_body,
        issue_body_sha256=hashlib.sha256(issue_body.encode("utf-8")).hexdigest(),
        issueplan_current_state_evidence_id="placeholder-evidence-id",
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        fresh_issue_body=issue_body,
        fresh_pr_head_sha="pr-head-sha",
    )

    assert isinstance(transport, AcceptanceReportTransport)
    assert transport.execution_authorized is False
    assert transport.transport_state == "snapshot-current"
    assert transport.reason_codes == ()
    assert transport.to_envelope()["issueplan_current_state_evidence_id"] == _build_expected_evidence_id(
        issue_body, "Blummer92/agent-os", 323
    )
    assert transport.to_envelope()["issueplan_current_state_evidence_id"] != "placeholder-evidence-id"


def test_transport_ignores_caller_provided_evidence_id_and_missing_provenance():
    report = AcceptanceReport(linked_issue=323, overall_status=Status.MANUAL_REVIEW, checks=[])

    missing = build_acceptance_report_transport(
        report=report,
        repository="",
        issue_number=None,
        issue_body="",
        issue_body_sha256="",
        issueplan_current_state_evidence_id="placeholder-evidence-id",
        pr_number=42,
        pr_head_sha="",
        evaluator_sha="",
        workflow_run_id="",
        workflow_run_attempt=1,
    )

    assert missing.transport_state == "missing-provenance"
    assert missing.reason_codes == ("missing-provenance",)
    assert missing.to_envelope()["issueplan_current_state_evidence_id"] == ""
    assert missing.to_envelope()["transport_state"] != "snapshot-current"


def test_transport_marks_missing_provenance_when_issue_body_lookup_fails():
    report = AcceptanceReport(linked_issue=323, overall_status=Status.MANUAL_REVIEW, checks=[])

    missing = build_acceptance_report_transport(
        report=report,
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="",
        issue_body_sha256="sha256",
        issueplan_current_state_evidence_id="caller-evidence-id",
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        issue_body_retrieval_failed=True,
    )

    assert missing.transport_state == "missing-provenance"
    assert missing.reason_codes == ("missing-provenance",)
    assert missing.to_envelope()["issueplan_current_state_evidence_id"] == ""


def test_transport_treats_successful_empty_body_as_valid_retrieval():
    report = AcceptanceReport(linked_issue=323, overall_status=Status.PASS, checks=[])

    transport = build_acceptance_report_transport(
        report=report,
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="",
        issue_body_sha256=hashlib.sha256(b"").hexdigest(),
        issueplan_current_state_evidence_id="caller-evidence-id",
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
    )

    assert transport.transport_state == "snapshot-current"
    assert transport.reason_codes == ()
    assert transport.to_envelope()["issueplan_current_state_evidence_id"]


def test_transport_uses_same_captured_issue_body_for_evidence_and_hash():
    report = AcceptanceReport(linked_issue=323, overall_status=Status.PASS, checks=[])
    issue_body = "Issue body"
    transport = build_acceptance_report_transport(
        report=report,
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body=issue_body,
        issue_body_sha256=hashlib.sha256(issue_body.encode("utf-8")).hexdigest(),
        issueplan_current_state_evidence_id="placeholder-evidence-id",
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
    )

    evidence_id = transport.to_envelope()["issueplan_current_state_evidence_id"]
    assert evidence_id == _build_expected_evidence_id(issue_body, "Blummer92/agent-os", 323)
    assert transport.to_envelope()["issue_body_sha256"] == hashlib.sha256(issue_body.encode("utf-8")).hexdigest()


def test_transport_envelope_is_bounded_and_canonical():
    report = AcceptanceReport(linked_issue=323, overall_status=Status.PASS, checks=[])

    transport = build_acceptance_report_transport(
        report=report,
        repository="Blummer92/agent-os",
        issue_number=323,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256("Issue body".encode("utf-8")).hexdigest(),
        issueplan_current_state_evidence_id="placeholder-evidence-id",
        pr_number=42,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
    )

    payload = transport.to_envelope()
    assert len(canonical_json_bytes(payload)) <= 64 * 1024
    assert json.loads(json.dumps(payload, sort_keys=True, separators=(",", ":"))) == payload
