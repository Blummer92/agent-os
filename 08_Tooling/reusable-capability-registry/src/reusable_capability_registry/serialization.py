from __future__ import annotations

import json
from collections.abc import Iterable

from .discovery import INFORMATIONAL_NOTICE
from .models import (
    CapabilityRecord,
    DiscoveryResult,
    ValidationEvidence,
    ValidationFinding,
    ValidationReport,
)


def _record_to_payload(record: CapabilityRecord) -> dict[str, object]:
    return {
        "capability_id": record.capability_id,
        "name": record.name,
        "summary": record.summary,
        "status": record.status,
        "canonical_paths": list(record.canonical_paths),
        "public_interfaces": list(record.public_interfaces),
        "owner_agent": record.owner_agent,
        "supporting_agents": list(record.supporting_agents),
        "known_consumers": list(record.known_consumers),
        "known_consumer_exemption": record.known_consumer_exemption,
        "tests": list(record.tests),
        "keywords": list(record.keywords),
        "reuse_guidance": record.reuse_guidance,
        "side_effects": list(record.side_effects),
        "inputs": list(record.inputs),
        "outputs": list(record.outputs),
        "extension_points": list(record.extension_points),
        "invariants": list(record.invariants),
        "failure_modes": list(record.failure_modes),
        "compatibility": list(record.compatibility),
        "documentation_handoff": list(record.documentation_handoff),
        "deprecated_by": record.deprecated_by,
    }


def discovery_result_to_payload(result: DiscoveryResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "capability": _record_to_payload(result.capability),
        "discovery": {
            "confidence": result.confidence.value,
            "evidence_basis": list(result.evidence_basis),
            "warnings": list(result.warnings),
            "manual_review_reasons": list(result.manual_review_reasons),
        },
        "informational_notice": INFORMATIONAL_NOTICE,
    }
    # Populated provenance is serialized deterministically; absent provenance is
    # omitted so approved legacy output is preserved byte-for-byte.
    if result.provenance is not None:
        payload["provenance"] = result.provenance.to_payload()
    return payload


def serialize_discovery_results(results: Iterable[DiscoveryResult]) -> str:
    payload = {
        "informational_notice": INFORMATIONAL_NOTICE,
        "results": [discovery_result_to_payload(result) for result in results],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _evidence_to_payload(evidence: ValidationEvidence) -> dict[str, object]:
    return {
        "path": evidence.path,
        "line": evidence.line,
        "symbol": evidence.symbol,
        "source_type": evidence.source_type,
        "detail": evidence.detail,
    }


def _finding_to_payload(finding: ValidationFinding) -> dict[str, object]:
    return {
        "code": finding.code,
        "confidence": finding.confidence.value,
        "severity": finding.severity.value,
        "capability_id": finding.capability_id,
        "surface": finding.surface,
        "message": finding.message,
        "evidence": [_evidence_to_payload(item) for item in finding.evidence],
        "manual_review_reason": finding.manual_review_reason,
    }


def validation_report_to_payload(report: ValidationReport) -> dict[str, object]:
    """Deterministic projection of a validation report (keys sorted by the serializer)."""
    return {
        "report_version": report.report_version,
        "informational_notice": report.informational_notice,
        "provenance": report.provenance.to_payload() if report.provenance is not None else None,
        "summary": {
            "severity": report.severity.value,
            "capabilities_checked": report.capabilities_checked,
            "checks_run": report.checks_run,
            "confidence_counts": {label: count for label, count in report.confidence_counts},
            "severity_counts": {label: count for label, count in report.severity_counts},
        },
        "findings": [_finding_to_payload(finding) for finding in report.findings],
    }


def serialize_validation_report(report: ValidationReport) -> str:
    """Canonical validation JSON: UTF-8, sorted keys, compact, exactly one final newline."""
    payload = validation_report_to_payload(report)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def render_text_results(results: Iterable[DiscoveryResult]) -> str:
    result_list = list(results)
    lines = [INFORMATIONAL_NOTICE]
    for result in result_list:
        lines.extend(
            [
                "",
                f"{result.capability.capability_id} [{result.confidence.value}]",
                f"  name: {result.capability.name}",
                f"  owner: {result.capability.owner_agent}",
                f"  status: {result.capability.status}",
                f"  evidence: {', '.join(result.evidence_basis)}",
                f"  warnings: {', '.join(result.warnings)}",
            ]
        )
        if result.manual_review_reasons:
            lines.append(f"  manual_review: {', '.join(result.manual_review_reasons)}")
    return "\n".join(lines) + "\n"
