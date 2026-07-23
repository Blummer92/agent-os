from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .issueplan_current_state import build_issueplan_current_state_evidence
from .issueplan_scanner import SourceEnvelope, scan_issueplan_source
from .models import AcceptanceReport, Status

CONTRACT_VERSION = "agent-os-acceptance-report-transport/v1"
SUPPORTED_CONTRACT_VERSIONS = {CONTRACT_VERSION}
ALLOWED_TRANSPORT_STATES = {
    "snapshot-current",
    "stale-issue",
    "stale-pr-head",
    "unsupported-contract",
    "missing-provenance",
}
MAX_ENVELOPE_BYTES = 64 * 1024
MAX_SUMMARY_BYTES = 64 * 1024


@dataclass(frozen=True)
class AcceptanceReportTransport:
    contract_version: str
    repository: str
    issue_number: int | None
    issue_body_sha256: str
    issueplan_current_state_evidence_id: str
    pr_number: int | None
    pr_head_sha: str
    evaluator_sha: str
    workflow_run_id: str
    workflow_run_attempt: int
    result_status: str
    report_sha256: str
    transport_state: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    execution_authorized: Literal[False] = field(default=False, init=False)

    def to_envelope(self) -> dict[str, Any]:
        payload = {
            "contract_version": self.contract_version,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "issue_body_sha256": self.issue_body_sha256,
            "issueplan_current_state_evidence_id": self.issueplan_current_state_evidence_id,
            "pr_number": self.pr_number,
            "pr_head_sha": self.pr_head_sha,
            "evaluator_sha": self.evaluator_sha,
            "workflow_run_id": self.workflow_run_id,
            "workflow_run_attempt": self.workflow_run_attempt,
            "result_status": self.result_status,
            "report_sha256": self.report_sha256,
            "transport_state": self.transport_state,
            "reason_codes": list(self.reason_codes),
            "execution_authorized": False,
        }
        if len(canonical_json_bytes(payload)) > MAX_ENVELOPE_BYTES:
            raise ValueError("transport envelope exceeds 64 KiB limit")
        return payload


def _build_issueplan_current_state_evidence_id(
    *,
    repository: str,
    issue_number: int | None,
    issue_body: str,
    issue_body_sha256: str,
) -> str:
    if not repository or issue_number is None or issue_body is None:
        raise ValueError("missing provenance")
    envelope = SourceEnvelope(
        source_locator=(
            f"github:{repository}#{issue_number}" if repository and issue_number is not None else "github:issue-body"
        ),
        source_revision=issue_body_sha256 or hashlib.sha256(issue_body.encode("utf-8")).hexdigest(),
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
        repository=repository,
        base_branch="main",
        evaluated_repository_sha="a" * 40,
        implementation_contract_fingerprint="b" * 64,
    )
    return evidence.evidence_id


def build_acceptance_report_transport(
    *,
    report: AcceptanceReport,
    repository: str,
    issue_number: int | None,
    issue_body: str,
    issue_body_sha256: str,
    issueplan_current_state_evidence_id: str,
    pr_number: int | None,
    pr_head_sha: str,
    evaluator_sha: str,
    workflow_run_id: str,
    workflow_run_attempt: int,
    fresh_issue_body: str | None = None,
    fresh_pr_head_sha: str | None = None,
    issue_body_retrieval_failed: bool = False,
    contract_version: str = CONTRACT_VERSION,
) -> AcceptanceReportTransport:
    if issue_body_retrieval_failed or not repository or issue_number is None or not issue_body_sha256 or not pr_head_sha or not evaluator_sha:
        transport_state = "missing-provenance"
        reason_codes = ("missing-provenance",)
        evidence_id = ""
    else:
        try:
            evidence_id = _build_issueplan_current_state_evidence_id(
                repository=repository,
                issue_number=issue_number,
                issue_body=issue_body,
                issue_body_sha256=issue_body_sha256,
            )
        except (TypeError, ValueError):
            transport_state = "missing-provenance"
            reason_codes = ("missing-provenance",)
            evidence_id = ""
        else:
            if not evidence_id:
                transport_state = "missing-provenance"
                reason_codes = ("missing-provenance",)
            elif contract_version not in SUPPORTED_CONTRACT_VERSIONS:
                transport_state = "unsupported-contract"
                reason_codes = ("unsupported-contract",)
            else:
                if fresh_issue_body is not None and fresh_issue_body != issue_body:
                    transport_state = "stale-issue"
                    reason_codes = ("stale-issue",)
                elif fresh_pr_head_sha is not None and fresh_pr_head_sha != pr_head_sha:
                    transport_state = "stale-pr-head"
                    reason_codes = ("stale-pr-head",)
                else:
                    transport_state = "snapshot-current"
                    reason_codes = ()

    result_status = report.overall_status.value
    envelope = {
        "contract_version": contract_version,
        "repository": repository,
        "issue_number": issue_number,
        "issue_body_sha256": issue_body_sha256,
        "issueplan_current_state_evidence_id": evidence_id,
        "pr_number": pr_number,
        "pr_head_sha": pr_head_sha,
        "evaluator_sha": evaluator_sha,
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "result_status": result_status,
        "report_sha256": "",
        "transport_state": transport_state,
        "reason_codes": list(reason_codes),
        "execution_authorized": False,
    }
    report_sha256 = hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()
    envelope["report_sha256"] = report_sha256
    if len(canonical_json_bytes(envelope)) > MAX_ENVELOPE_BYTES:
        raise ValueError("transport envelope exceeds 64 KiB limit")
    if transport_state not in ALLOWED_TRANSPORT_STATES:
        raise ValueError("unsupported transport state")
    if reason_codes:
        for code in reason_codes:
            if code not in {"missing-provenance", "unsupported-contract", "stale-issue", "stale-pr-head"}:
                raise ValueError("unsupported reason code")
    return AcceptanceReportTransport(
        contract_version=contract_version,
        repository=repository,
        issue_number=issue_number,
        issue_body_sha256=issue_body_sha256,
        issueplan_current_state_evidence_id=evidence_id,
        pr_number=pr_number,
        pr_head_sha=pr_head_sha,
        evaluator_sha=evaluator_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        result_status=result_status,
        report_sha256=report_sha256,
        transport_state=transport_state,
        reason_codes=reason_codes,
    )


def render_transport_summary(transport: AcceptanceReportTransport, report: AcceptanceReport) -> str:
    summary = [
        "## Acceptance report transport",
        "",
        f"- contract: {transport.contract_version}",
        f"- transport_state: {transport.transport_state}",
        f"- result_status: {transport.result_status}",
        f"- report_sha256: {transport.report_sha256}",
        f"- issueplan_current_state_evidence_id: {transport.issueplan_current_state_evidence_id}",
        f"- execution_authorized: {str(transport.execution_authorized).lower()}",
    ]
    if transport.reason_codes:
        summary.append(f"- reason_codes: {', '.join(transport.reason_codes)}")
    if report.evidence:
        summary.append(f"- evidence: {', '.join(report.evidence)}")
    rendered = "\n".join(summary) + "\n"
    if len(rendered.encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise ValueError("transport summary exceeds 64 KiB limit")
    return rendered


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
