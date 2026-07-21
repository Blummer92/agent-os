"""Execute one frozen RC6 case through existing report-only interfaces."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping

from reusable_capability_registry.models import (
    DiscoveryResult,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)
from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_acceptance.report import render_report
from scripts.agent_os_issue_acceptance.reuse_readiness import attach_reuse_evidence

from .case_builders import build_execution_inputs, provenance_state, relevant_findings

_SEVERITY_RANK = {
    ValidationSeverity.PASS: 0,
    ValidationSeverity.WARN: 1,
    ValidationSeverity.MANUAL_REVIEW: 2,
    ValidationSeverity.FAIL: 3,
}


def execute_case(case: Mapping[str, Any], repository_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"rc6-{case['case_id'].lower()}-") as tmp:
        inputs = build_execution_inputs(case, repository_root, Path(tmp))
        augmented = attach_reuse_evidence(
            inputs.base,
            inputs.discovery_for_adapter,  # type: ignore[arg-type]
            inputs.validation_for_adapter,  # type: ignore[arg-type]
        )
        report_text = render_report(augmented.report)
        report = inputs.validation_for_result
        results = inputs.discovery_for_result
        ids = [result.capability.capability_id for result in results]
        findings = relevant_findings(report, ids)
        if report is None:
            rc4_severity = "malformed"
        elif findings:
            rc4_severity = max(
                (finding.severity for finding in findings),
                key=lambda severity: _SEVERITY_RANK[severity],
            ).value
        else:
            rc4_severity = ValidationSeverity.PASS.value
        statuses = [check.status.value for check in augmented.report.informational_checks]
        positive = any(
            check.name.startswith("reuse candidate ")
            and check.status in {Status.PASS, Status.WARN}
            for check in augmented.report.informational_checks
        )
        if not augmented.report.informational_checks:
            evidence_disposition = "none"
        elif any(
            check.name == "reuse-evidence-error"
            for check in augmented.report.informational_checks
        ):
            evidence_disposition = "error"
        elif positive and any(
            check.status is Status.WARN
            for check in augmented.report.informational_checks
        ):
            evidence_disposition = "qualified-positive"
        elif positive:
            evidence_disposition = "positive"
        else:
            evidence_disposition = "suppressed"
        provenance_states = list(
            inputs.provenance_override
            if inputs.provenance_override is not None
            else tuple(
                provenance_state(
                    result.provenance,
                    report.provenance if report else None,
                )
                for result in results
            )
        )
        expected_classes = set(case["threshold_classes"])
        return {
            "rc3_ids": ids,
            "rc3_confidence": [result.confidence.value for result in results],
            "rc3_evidence_basis": [list(result.evidence_basis) for result in results],
            "rc3_manual_review_reasons": [
                list(result.manual_review_reasons) for result in results
            ],
            "rc3_warnings": [list(result.warnings) for result in results],
            "rc3_boundary": inputs.boundary,
            "rc4_severity": rc4_severity,
            "rc4_finding_codes": sorted({finding.code for finding in findings}),
            "provenance_states": provenance_states,
            "rc5_statuses": statuses,
            "rc5_evidence_disposition": evidence_disposition,
            "positive_guidance": positive,
            "readiness_before": inputs.base.outcome.value,
            "readiness_after": augmented.outcome.value,
            "implementation_authorized": False,
            "repository_write_authorized": False,
            "merge_authorized": False,
            "automatic_selection": False,
            "active_exemption_reviewed": (
                "active-exemption" in expected_classes
                and any(
                    finding.code.startswith("exemption.active-")
                    for finding in findings
                )
            ),
            "actual_rc3_results": _serialize_discovery(results),
            "actual_rc4_findings": _serialize_findings(findings),
            "actual_provenance": provenance_states,
            "actual_rc5_render": report_text,
            "actual_base_readiness_after": augmented.outcome.value,
            "human_review_determination": None,
            "recommendation_correct": None,
            "duplicate_implementation_avoided": None,
            "maintenance_effort": None,
            "remaining_risk": [],
        }


def _serialize_discovery(results: tuple[DiscoveryResult, ...]) -> list[dict[str, Any]]:
    return [
        {
            "capability_id": result.capability.capability_id,
            "confidence": result.confidence.value,
            "evidence_basis": list(result.evidence_basis),
            "warnings": list(result.warnings),
            "manual_review_reasons": list(result.manual_review_reasons),
        }
        for result in results
    ]


def _serialize_findings(findings: tuple[ValidationFinding, ...]) -> list[dict[str, Any]]:
    return [
        {
            "code": finding.code,
            "confidence": finding.confidence.value,
            "severity": finding.severity.value,
            "capability_id": finding.capability_id,
            "surface": finding.surface,
            "message": finding.message,
            "manual_review_reason": finding.manual_review_reason,
            "evidence": [
                {
                    "path": item.path,
                    "line": item.line,
                    "symbol": item.symbol,
                    "source_type": item.source_type,
                    "detail": item.detail,
                }
                for item in finding.evidence
            ],
        }
        for finding in findings
    ]
