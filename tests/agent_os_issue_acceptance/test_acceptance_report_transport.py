import hashlib
import json

import pytest

from scripts.agent_os_issue_acceptance.acceptance_report_transport import (
    AcceptanceReportTransport,
    acceptance_report_from_payload,
    acceptance_report_to_payload,
    build_acceptance_report_transport,
    canonical_json_bytes,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    build_issueplan_current_state_evidence,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import SourceEnvelope, scan_issueplan_source
from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    LinkedIssueCandidate,
    LinkedIssueParseResult,
    LinkedIssueParseStatus,
    Status,
)


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


# --------------------------------------------------------------------------
# Canonical AcceptanceReport payload ownership (#750 review finding 3).
# This module is the single owner of AcceptanceReport payload shape; the
# candidate-packet stage reuses these helpers instead of a second serializer.
# --------------------------------------------------------------------------


def _build_rich_report() -> AcceptanceReport:
    candidate = LinkedIssueCandidate(
        issue_number=750,
        repository="Blummer92/agent-os",
        keyword="Refs",
        source="pr_body",
        position=12,
        raw_target="Blummer92/agent-os#750",
        explicit=True,
    )
    bare = LinkedIssueCandidate(
        issue_number=749,
        repository=None,
        keyword=None,
        source="issue_body",
        position=3,
        raw_target="#749",
        explicit=False,
    )
    return AcceptanceReport(
        linked_issue=750,
        overall_status=Status.MANUAL_REVIEW,
        checks=[
            CheckResult("scope", Status.PASS, "allowlist respected", ["files=7"]),
            CheckResult("docs", Status.MANUAL_REVIEW, "needs a human", []),
        ],
        linked_issue_result=LinkedIssueParseResult(
            status=LinkedIssueParseStatus.RESOLVED,
            issue_number=750,
            repository="Blummer92/agent-os",
            explicit_candidates=[candidate],
            bare_references=[bare],
            reasons=["explicit reference found"],
        ),
        manual_review_items=["confirm doc impact"],
        evidence=["19 focused tests passed"],
        blockers=["awaiting review"],
        remaining_risks=["baseline aggregate failure"],
        informational_checks=(
            CheckResult("reuse", Status.PASS, "canonical reuse verified", ["reuse=ok"]),
        ),
    )


def test_acceptance_report_payload_round_trip_preserves_every_field():
    report = _build_rich_report()
    payload = acceptance_report_to_payload(report)
    reconstructed = acceptance_report_from_payload(payload)

    assert reconstructed == report
    assert acceptance_report_to_payload(reconstructed) == payload
    assert isinstance(reconstructed.informational_checks, tuple)
    assert canonical_json_bytes(
        acceptance_report_to_payload(reconstructed)
    ) == canonical_json_bytes(payload)


def test_acceptance_report_payload_round_trip_handles_minimal_report():
    report = AcceptanceReport(linked_issue=None, overall_status=Status.PASS, checks=[])
    payload = acceptance_report_to_payload(report)
    assert acceptance_report_from_payload(payload) == report


def test_acceptance_report_from_payload_rejects_unsupported_field():
    payload = acceptance_report_to_payload(_build_rich_report())
    payload["unexpected"] = "value"
    with pytest.raises(ValueError, match="unsupported field"):
        acceptance_report_from_payload(payload)


def test_acceptance_report_from_payload_rejects_missing_field():
    payload = acceptance_report_to_payload(_build_rich_report())
    del payload["blockers"]
    with pytest.raises(ValueError, match="missing field"):
        acceptance_report_from_payload(payload)


def test_acceptance_report_from_payload_rejects_boolean_linked_issue():
    payload = acceptance_report_to_payload(_build_rich_report())
    payload["linked_issue"] = True
    with pytest.raises(ValueError, match="linked_issue must be an int"):
        acceptance_report_from_payload(payload)


def test_acceptance_report_from_payload_rejects_unsupported_status():
    payload = acceptance_report_to_payload(_build_rich_report())
    payload["overall_status"] = "not-a-status"
    with pytest.raises(ValueError, match="unsupported value"):
        acceptance_report_from_payload(payload)


def test_acceptance_report_from_payload_rejects_malformed_collections():
    payload = acceptance_report_to_payload(_build_rich_report())
    payload["checks"] = {"name": "scope"}
    with pytest.raises(ValueError, match="checks must be a list"):
        acceptance_report_from_payload(payload)

    payload = acceptance_report_to_payload(_build_rich_report())
    payload["evidence"] = ["ok", 5]
    with pytest.raises(ValueError, match="only strings"):
        acceptance_report_from_payload(payload)

    payload = acceptance_report_to_payload(_build_rich_report())
    payload["checks"][0]["status"] = "bogus"
    with pytest.raises(ValueError, match="unsupported value"):
        acceptance_report_from_payload(payload)


def test_acceptance_report_from_payload_rejects_non_mapping():
    with pytest.raises(ValueError, match="must be a mapping"):
        acceptance_report_from_payload(["not", "a", "mapping"])


def test_acceptance_report_from_payload_rejects_malformed_candidate():
    payload = acceptance_report_to_payload(_build_rich_report())
    del payload["linked_issue_result"]["explicit_candidates"][0]["raw_target"]
    with pytest.raises(ValueError, match="missing field"):
        acceptance_report_from_payload(payload)


def test_transport_report_sha256_uses_the_canonical_payload():
    report = _build_rich_report()
    transport = build_acceptance_report_transport(
        report=report,
        repository="Blummer92/agent-os",
        issue_number=750,
        issue_body="Issue body",
        issue_body_sha256=hashlib.sha256(b"Issue body").hexdigest(),
        pr_number=765,
        pr_head_sha="pr-head-sha",
        evaluator_sha="evaluator-sha",
        workflow_run_id="12345",
        workflow_run_attempt=1,
        observed_at="2026-07-23T00:00:00Z",
        fresh_issue_body="Issue body",
        fresh_pr_head_sha="pr-head-sha",
    )
    expected = hashlib.sha256(
        canonical_json_bytes(acceptance_report_to_payload(report))
    ).hexdigest()
    assert transport.report_sha256 == expected
