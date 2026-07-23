from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .issueplan_current_state import build_issueplan_current_state_evidence
from .issueplan_scanner import SourceEnvelope, scan_issueplan_source
from .models import AcceptanceReport, CheckResult, LinkedIssueCandidate, LinkedIssueParseResult, Status

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
STATE_PRECEDENCE = {
    "unsupported-contract": 0,
    "missing-provenance": 1,
    "stale-pr-head": 2,
    "stale-issue": 3,
    "snapshot-current": 4,
}


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
    observed_at: str,
) -> str:
    if not repository or issue_number is None or issue_body is None:
        raise ValueError("missing provenance")
    envelope = SourceEnvelope(
        source_locator=(
            f"github:{repository}#{issue_number}" if repository and issue_number is not None else "github:issue-body"
        ),
        source_revision=issue_body_sha256,
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
        repository=repository,
        base_branch="main",
    )
    return evidence.evidence_id


def _normalize_observed_at(observed_at: str | None) -> str:
    if observed_at:
        return observed_at
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_issue_body_sha256(issue_body: str, issue_body_sha256: str | None) -> str:
    computed = hashlib.sha256(issue_body.encode("utf-8")).hexdigest()
    if issue_body_sha256 and issue_body_sha256 != computed:
        return computed
    return issue_body_sha256 or computed


def _report_payload(report: AcceptanceReport) -> dict[str, Any]:
    return {
        "linked_issue": report.linked_issue,
        "overall_status": report.overall_status.value,
        "checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "evidence": list(check.evidence),
            }
            for check in report.checks
        ],
        "linked_issue_result": None
        if report.linked_issue_result is None
        else {
            "status": report.linked_issue_result.status.value,
            "issue_number": report.linked_issue_result.issue_number,
            "repository": report.linked_issue_result.repository,
            "explicit_candidates": [
                {
                    "issue_number": candidate.issue_number,
                    "repository": candidate.repository,
                    "keyword": candidate.keyword,
                    "source": candidate.source,
                    "position": candidate.position,
                    "raw_target": candidate.raw_target,
                    "explicit": candidate.explicit,
                }
                for candidate in report.linked_issue_result.explicit_candidates
            ],
            "bare_references": [
                {
                    "issue_number": candidate.issue_number,
                    "repository": candidate.repository,
                    "keyword": candidate.keyword,
                    "source": candidate.source,
                    "position": candidate.position,
                    "raw_target": candidate.raw_target,
                    "explicit": candidate.explicit,
                }
                for candidate in report.linked_issue_result.bare_references
            ],
            "reasons": list(report.linked_issue_result.reasons),
        },
        "manual_review_items": list(report.manual_review_items),
        "evidence": list(report.evidence),
        "blockers": list(report.blockers),
        "remaining_risks": list(report.remaining_risks),
        "informational_checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "evidence": list(check.evidence),
            }
            for check in report.informational_checks
        ],
    }


def build_acceptance_report_transport(
    *,
    report: AcceptanceReport,
    repository: str,
    issue_number: int | None,
    issue_body: str,
    issue_body_sha256: str,
    pr_number: int | None,
    pr_head_sha: str,
    evaluator_sha: str,
    workflow_run_id: str,
    workflow_run_attempt: int,
    fresh_issue_body: str | None = None,
    fresh_pr_head_sha: str | None = None,
    issue_body_retrieval_failed: bool = False,
    contract_version: str = CONTRACT_VERSION,
    observed_at: str | None = None,
) -> AcceptanceReportTransport:
    observed_at = _normalize_observed_at(observed_at)
    resolved_issue_body_sha256 = _resolve_issue_body_sha256(issue_body, issue_body_sha256 or None)
    reason_codes: list[str] = []
    evidence_id = ""

    if contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        reason_codes.append("unsupported-contract")

    if issue_body_retrieval_failed or not repository or issue_number is None or not pr_head_sha or not evaluator_sha or not observed_at:
        reason_codes.append("missing-provenance")
    elif fresh_issue_body is None or fresh_pr_head_sha is None:
        reason_codes.append("missing-provenance")
    elif issue_body is None:
        reason_codes.append("missing-provenance")
    else:
        try:
            evidence_id = _build_issueplan_current_state_evidence_id(
                repository=repository,
                issue_number=issue_number,
                issue_body=issue_body,
                issue_body_sha256=resolved_issue_body_sha256,
                observed_at=observed_at,
            )
        except (TypeError, ValueError):
            reason_codes.append("missing-provenance")
            evidence_id = ""

    if not reason_codes:
        stale_reason_codes: list[str] = []
        if fresh_issue_body is not None and fresh_issue_body != issue_body:
            stale_reason_codes.append("stale-issue")
        if fresh_pr_head_sha is not None and fresh_pr_head_sha != pr_head_sha:
            stale_reason_codes.append("stale-pr-head")
        if stale_reason_codes:
            reason_codes.extend(stale_reason_codes)

    reason_codes = sorted(reason_codes, key=lambda code: STATE_PRECEDENCE[code])
    if "unsupported-contract" in reason_codes:
        transport_state = "unsupported-contract"
    elif "missing-provenance" in reason_codes:
        transport_state = "missing-provenance"
    elif "stale-pr-head" in reason_codes:
        transport_state = "stale-pr-head"
    elif "stale-issue" in reason_codes:
        transport_state = "stale-issue"
    else:
        transport_state = "snapshot-current"

    if transport_state == "snapshot-current" and not evidence_id:
        transport_state = "missing-provenance"
        reason_codes = ["missing-provenance"]
        evidence_id = ""

    result_status = report.overall_status.value
    envelope = {
        "contract_version": contract_version,
        "repository": repository,
        "issue_number": issue_number,
        "issue_body_sha256": resolved_issue_body_sha256,
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
    report_sha256 = hashlib.sha256(canonical_json_bytes(_report_payload(report))).hexdigest()
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
        issue_body_sha256=resolved_issue_body_sha256,
        issueplan_current_state_evidence_id=evidence_id,
        pr_number=pr_number,
        pr_head_sha=pr_head_sha,
        evaluator_sha=evaluator_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        result_status=result_status,
        report_sha256=report_sha256,
        transport_state=transport_state,
        reason_codes=tuple(reason_codes),
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
