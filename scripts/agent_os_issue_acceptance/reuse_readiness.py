"""Attach informational reusable-capability evidence without changing readiness."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import fields, replace

from .models import CheckResult, Status
from .readiness import ReadinessResult
from reusable_capability_registry.models import (
    CapabilityRecord,
    Confidence,
    DiscoveryResult,
    EvidenceConfidence,
    RegistryProvenance,
    ValidationEvidence,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)

__all__ = ["attach_reuse_evidence"]
_AUTH = "authorization=evidence-only-not-implementation-write-or-merge"
_RANK = {
    ValidationSeverity.PASS: 0,
    ValidationSeverity.WARN: 1,
    ValidationSeverity.MANUAL_REVIEW: 2,
    ValidationSeverity.FAIL: 3,
}


def attach_reuse_evidence(
    readiness: ReadinessResult,
    discovery_results: Iterable[DiscoveryResult],
    validation_report: ValidationReport,
) -> ReadinessResult:
    try:
        results = list(discovery_results)
    except (TypeError, ValueError):
        return _attach(readiness, [_error("discovery evidence is not iterable")])
    if not results:
        return readiness
    problem = _input_problem(results, validation_report)
    if problem:
        return _attach(readiness, [_error(problem)])
    return _attach(readiness, _checks(results, validation_report))


def _input_problem(results: list[DiscoveryResult], report: object) -> str | None:
    if not isinstance(report, ValidationReport):
        return "validation_report must be a ValidationReport"
    if report.provenance is not None and not isinstance(report.provenance, RegistryProvenance):
        return "validation report provenance is malformed"
    if not isinstance(report.findings, tuple) or not all(
        isinstance(x, ValidationFinding) for x in report.findings
    ):
        return "validation report findings are malformed"
    for finding in report.findings:
        if not isinstance(finding.evidence, tuple) or not all(
            isinstance(x, ValidationEvidence) for x in finding.evidence
        ):
            return "validation finding evidence is malformed"
    for result in results:
        if not isinstance(result, DiscoveryResult):
            return "discovery_results must contain DiscoveryResult values"
        if not isinstance(result.capability, CapabilityRecord):
            return "discovery capability is malformed"
        if not isinstance(result.confidence, Confidence):
            return "discovery confidence is malformed"
        if result.provenance is not None and not isinstance(result.provenance, RegistryProvenance):
            return "discovery provenance is malformed"
        for name in ("evidence_basis", "warnings", "manual_review_reasons"):
            value = getattr(result, name)
            if not isinstance(value, tuple) or not all(isinstance(x, str) for x in value):
                return f"discovery {name} is malformed"
    return None


def _attach(readiness: ReadinessResult, info: list[CheckResult]) -> ReadinessResult:
    base = readiness.report
    report = replace(
        base,
        checks=[replace(x, evidence=list(x.evidence)) for x in base.checks],
        manual_review_items=list(base.manual_review_items),
        evidence=list(base.evidence),
        blockers=list(base.blockers),
        remaining_risks=list(base.remaining_risks),
        informational_checks=tuple(info),
    )
    return ReadinessResult(readiness.outcome, report)


def _error(detail: str) -> CheckResult:
    return CheckResult(
        "reuse-evidence-error",
        Status.MANUAL_REVIEW,
        "Reuse evidence could not be interpreted; base readiness is unchanged.",
        [f"error={detail}"],
    )


def _checks(results: list[DiscoveryResult], report: ValidationReport) -> list[CheckResult]:
    unique: list[DiscoveryResult] = []
    for result in results:
        if result not in unique:
            unique.append(result)
    grouped: dict[str, list[DiscoveryResult]] = {}
    for result in unique:
        grouped.setdefault(result.capability.capability_id, []).append(result)
    output = [
        _conflict(cap_id, group) if len(group) > 1 else _candidate(group[0], report)
        for cap_id, group in sorted(grouped.items())
    ]
    ids = set(grouped)
    unmatched = [x for x in report.findings if x.capability_id is None or x.capability_id not in ids]
    if unmatched:
        output.append(_unmatched(unmatched))
    return output


def _provenance(a: RegistryProvenance | None, b: RegistryProvenance | None) -> str:
    if a is None or b is None:
        return "missing"
    if a != b:
        return "mismatch"
    return "matched" if a.is_supported else "unsupported"


def _candidate(result: DiscoveryResult, report: ValidationReport) -> CheckResult:
    cap = result.capability
    findings = tuple(x for x in report.findings if x.capability_id == cap.capability_id)
    provenance = _provenance(result.provenance, report.provenance)
    status, message = _classification(result, findings, provenance)
    evidence = [
        f"capability_id={cap.capability_id}",
        f"lifecycle_status={cap.status}",
        f"discovery_confidence={result.confidence.value}",
        f"provenance={provenance}",
    ]
    evidence += [f"discovery_evidence={x}" for x in result.evidence_basis]
    evidence += [f"interface={x}" for x in cap.public_interfaces]
    evidence += [f"discovery_warning={x}" for x in result.warnings]
    evidence += [f"discovery_manual_review={x}" for x in result.manual_review_reasons]
    for finding in sorted(findings, key=lambda x: x.sort_key()):
        evidence += _finding_lines(finding)
    if cap.known_consumer_exemption:
        evidence.append(f"consumer_exemption={cap.known_consumer_exemption}")
    else:
        evidence += [f"known_consumer={x}" for x in cap.known_consumers]
    evidence += [f"test={x}" for x in cap.tests]
    if cap.reuse_guidance:
        evidence.append(f"reuse_guidance={cap.reuse_guidance}")
    evidence += [f"side_effect={x}" for x in cap.side_effects]
    evidence += [f"invariant={x}" for x in cap.invariants]
    evidence += [f"compatibility={x}" for x in cap.compatibility]
    if not cap.compatibility and not cap.invariants:
        evidence.append("remaining_risk=behavioral-contract-not-evaluated")
    evidence.append(_AUTH)
    return CheckResult(f"reuse candidate {cap.capability_id}", status, message, evidence)


def _classification(
    result: DiscoveryResult, findings: tuple[ValidationFinding, ...], provenance: str
) -> tuple[Status, str]:
    cap_id = result.capability.capability_id
    if provenance != "matched":
        return Status.MANUAL_REVIEW, (
            f"Reusable capability {cap_id}: registry provenance {provenance}; positive reuse "
            "guidance is suppressed. Base readiness is unchanged."
        )
    worst = max((x.severity for x in findings), key=lambda x: _RANK[x], default=ValidationSeverity.PASS)
    contradicted = any(x.confidence is EvidenceConfidence.CONTRADICTED for x in findings)
    if worst is ValidationSeverity.FAIL or contradicted:
        return Status.FAIL, (
            f"Reusable capability {cap_id}: positive reuse guidance is suppressed by failing or "
            "contradicted validation evidence; the evidence is retained below."
        )
    if worst is ValidationSeverity.MANUAL_REVIEW:
        return Status.MANUAL_REVIEW, (
            f"Reusable capability {cap_id}: validation manual-review evidence prevents an "
            "unqualified recommendation; human review is required."
        )
    if worst is ValidationSeverity.WARN:
        if result.confidence is Confidence.VERIFIED:
            return Status.WARN, (
                f"Reusable capability {cap_id}: qualified informational match (verified discovery "
                "with validation warnings); review the warnings before reuse."
            )
        return Status.MANUAL_REVIEW, (
            f"Reusable capability {cap_id}: {result.confidence.value} discovery with validation "
            "warnings; human review is required and no positive reuse guidance is given."
        )
    if result.confidence is Confidence.VERIFIED:
        if result.capability.known_consumer_exemption:
            return Status.WARN, (
                f"Reusable capability {cap_id}: active consumer exemption; treated as a qualified "
                "match with an explicit warning and no verified-consumer claim."
            )
        return Status.PASS, (
            f"Reusable capability {cap_id}: positive informational match (verified discovery, "
            "clean same-snapshot validation)."
        )
    return Status.MANUAL_REVIEW, (
        f"Reusable capability {cap_id}: {result.confidence.value} discovery evidence; "
        "informational manual-review advisory, no positive reuse guidance."
    )


def _finding_lines(finding: ValidationFinding) -> list[str]:
    lines = [
        f"validation_finding={finding.code}; capability_id={finding.capability_id or 'none'}; "
        f"surface={finding.surface}; severity={finding.severity.value}; "
        f"confidence={finding.confidence.value}; message={finding.message}"
    ]
    if finding.manual_review_reason:
        lines.append(
            f"validation_finding={finding.code}; manual_review_reason={finding.manual_review_reason}"
        )
    for item in sorted(finding.evidence, key=lambda x: x.sort_key()):
        lines.append(
            f"validation_finding={finding.code}; validation_evidence="
            f"path={item.path or 'none'}; line={item.line if item.line is not None else 'none'}; "
            f"symbol={item.symbol or 'none'}; source_type={item.source_type}; detail={item.detail}"
        )
    return lines


def _provenance_key(value: RegistryProvenance | None) -> tuple:
    if value is None:
        return ("", 0, "", "")
    return (value.algorithm, value.algorithm_version, value.registry_version, value.digest)


def _result_key(result: DiscoveryResult) -> tuple:
    cap = tuple((x.name, getattr(result.capability, x.name)) for x in fields(result.capability))
    return (
        result.confidence.value,
        _provenance_key(result.provenance),
        result.evidence_basis,
        result.warnings,
        result.manual_review_reasons,
        cap,
    )


def _conflict(cap_id: str, group: list[DiscoveryResult]) -> CheckResult:
    ordered = sorted(group, key=_result_key)
    differing = [
        x.name
        for x in fields(ordered[0].capability)
        if len({repr(getattr(r.capability, x.name)) for r in ordered}) > 1
    ]
    evidence = [f"capability_id={cap_id}", f"conflicting_discovery_results={len(group)}"]
    for index, result in enumerate(ordered):
        prefix = f"variant={index}"
        evidence.append(f"{prefix}; confidence={result.confidence.value}")
        if result.provenance is None:
            evidence.append(f"{prefix}; provenance=absent")
        else:
            p = result.provenance
            evidence.append(
                f"{prefix}; provenance_algorithm={p.algorithm}; "
                f"provenance_algorithm_version={p.algorithm_version}; "
                f"provenance_registry_version={p.registry_version}; provenance_digest={p.digest}"
            )
        evidence += [f"{prefix}; evidence_basis={x}" for x in result.evidence_basis]
        evidence += [f"{prefix}; warning={x}" for x in result.warnings]
        evidence += [f"{prefix}; manual_review_reason={x}" for x in result.manual_review_reasons]
        evidence += [f"{prefix}; capability_{x}={getattr(result.capability, x)!r}" for x in differing]
    evidence.append(_AUTH)
    return CheckResult(
        f"reuse candidate {cap_id}",
        Status.MANUAL_REVIEW,
        f"Reusable capability {cap_id}: multiple conflicting discovery results were supplied; "
        "positive reuse guidance is suppressed and every variant is preserved for human review.",
        evidence,
    )


def _unmatched(findings: list[ValidationFinding]) -> CheckResult:
    evidence: list[str] = []
    for finding in sorted(findings, key=lambda x: x.sort_key()):
        evidence += _finding_lines(finding)
    evidence.append(_AUTH)
    return CheckResult(
        "reuse unmatched validation findings",
        Status.MANUAL_REVIEW,
        "Validation findings without a matching discovery candidate are shown for human review "
        "and are not attached to any candidate.",
        evidence,
    )
