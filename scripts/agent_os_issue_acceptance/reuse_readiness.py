"""Informational reusable-capability evidence adapter (RC5B / #470).

Sole cross-package boundary between issue readiness and the reusable-capability
registry. It attaches caller-supplied RC3 discovery evidence and corrected-RC4
validation evidence to an already-computed ``ReadinessResult`` as a strictly
informational layer, per the binding #248 contract (``#issuecomment-5035396385``)
composing #471 (provenance), #472 (report compatibility), #475/#476.

Guarantees (see the #248 contract):

* Reusable-capability evidence may inform readiness but may never determine it.
  The returned result's ``outcome`` and every ordinary ``AcceptanceReport`` field
  (checks, overall status, blockers, manual-review items, evidence, remaining
  risks) are identical to the base result; only ``informational_checks`` is added.
* Empty discovery evidence returns the original ``ReadinessResult`` unchanged.
* Malformed input returns the base readiness plus one informational error entry —
  never an ordinary blocker or ordinary manual-review item.
* Provenance is compared using caller-supplied ``RegistryProvenance`` values only
  (strict, version-aware whole-object equality). This module never reads the
  registry, recomputes canonicalization, or invokes ``RegistryReader``, discovery
  ranking, or RC4 validation/serialization orchestration.
* Pure, offline, deterministic, and mutation-free; output is invariant under
  input ordering.

The base ``readiness.py`` does not import this module, so base issue readiness
remains usable without the reusable-capability package installed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from .models import CheckResult, Status
from .readiness import ReadinessResult

# Direct-submodule import of registry *data types only* (no reader/discovery/
# validation/serialization orchestration is invoked from this module).
from reusable_capability_registry.models import (
    Confidence,
    DiscoveryResult,
    EvidenceConfidence,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)

__all__ = ["attach_reuse_evidence"]

_SEVERITY_ORDER = {
    ValidationSeverity.PASS: 0,
    ValidationSeverity.WARN: 1,
    ValidationSeverity.MANUAL_REVIEW: 2,
    ValidationSeverity.FAIL: 3,
}

_AUTHORIZATION_EVIDENCE = "authorization=evidence-only-not-implementation-write-or-merge"


def attach_reuse_evidence(
    readiness: ReadinessResult,
    discovery_results: Iterable[DiscoveryResult],
    validation_report: ValidationReport,
) -> ReadinessResult:
    """Attach informational reuse evidence without changing base readiness."""
    try:
        results = list(discovery_results)
    except TypeError:
        return _with_informational(readiness, [_error_check("discovery evidence is not iterable")])

    if not results:
        # No reuse evidence supplied: return the original result unchanged.
        return readiness

    try:
        checks = _build_informational_checks(results, validation_report)
    except Exception as exc:  # noqa: BLE001 - fail closed, never crash the readiness path
        return _with_informational(readiness, [_error_check(f"unusable reuse evidence ({type(exc).__name__})")])

    return _with_informational(readiness, checks)


# --- result assembly -------------------------------------------------------


def _with_informational(readiness: ReadinessResult, checks: list[CheckResult]) -> ReadinessResult:
    """Return a new ReadinessResult with only ``informational_checks`` populated."""
    report = replace(readiness.report, informational_checks=tuple(checks))
    return ReadinessResult(outcome=readiness.outcome, report=report)


def _error_check(detail: str) -> CheckResult:
    return CheckResult(
        "reuse-evidence-error",
        Status.MANUAL_REVIEW,
        "Reuse evidence could not be interpreted; base readiness is unchanged.",
        [f"error={detail}"],
    )


def _build_informational_checks(
    results: list[DiscoveryResult], validation_report: ValidationReport
) -> list[CheckResult]:
    if not isinstance(validation_report, ValidationReport):
        raise TypeError("validation_report must be a ValidationReport")
    if not all(isinstance(item, DiscoveryResult) for item in results):
        raise TypeError("discovery_results must contain DiscoveryResult values")

    # Full-value dedup (frozen-dataclass equality); identical duplicates collapse.
    unique: list[DiscoveryResult] = []
    for item in results:
        if item not in unique:
            unique.append(item)

    grouped: dict[str, list[DiscoveryResult]] = {}
    for item in unique:
        grouped.setdefault(item.capability.capability_id, []).append(item)

    discovered_ids = set(grouped)
    checks: list[CheckResult] = []
    for cap_id in sorted(grouped):
        group = grouped[cap_id]
        if len(group) > 1:
            checks.append(_conflicting_check(cap_id, group))
        else:
            checks.append(_candidate_check(group[0], validation_report))

    unmatched = [
        finding
        for finding in validation_report.findings
        if finding.capability_id is None or finding.capability_id not in discovered_ids
    ]
    if unmatched:
        checks.append(_unmatched_findings_check(unmatched))

    return checks


# --- classification --------------------------------------------------------


def _worst_severity(findings: tuple[ValidationFinding, ...]) -> ValidationSeverity:
    worst = ValidationSeverity.PASS
    for finding in findings:
        if _SEVERITY_ORDER[finding.severity] > _SEVERITY_ORDER[worst]:
            worst = finding.severity
    return worst


def _provenance_state(disc_prov, val_prov) -> str:
    """Compare caller-supplied provenance values only (never read the registry)."""
    if disc_prov is None or val_prov is None:
        return "missing"
    if disc_prov != val_prov:
        return "mismatch"
    if not disc_prov.is_supported:
        return "unsupported"
    return "matched"


def _candidate_check(discovery: DiscoveryResult, report: ValidationReport) -> CheckResult:
    cap = discovery.capability
    matched = tuple(f for f in report.findings if f.capability_id == cap.capability_id)
    prov_state = _provenance_state(discovery.provenance, report.provenance)
    status, message = _classify(discovery, matched, prov_state)
    evidence = _candidate_evidence(discovery, matched, prov_state)
    return CheckResult(f"reuse candidate {cap.capability_id}", status, message, evidence)


def _classify(
    discovery: DiscoveryResult, matched: tuple[ValidationFinding, ...], prov_state: str
) -> tuple[Status, str]:
    cap_id = discovery.capability.capability_id
    exemption = bool(discovery.capability.known_consumer_exemption)

    if prov_state != "matched":
        return (
            Status.MANUAL_REVIEW,
            f"Reusable capability {cap_id}: registry provenance {prov_state}; positive reuse "
            "guidance is suppressed. Base readiness is unchanged.",
        )

    worst = _worst_severity(matched)
    contradicted = any(f.confidence is EvidenceConfidence.CONTRADICTED for f in matched)

    if worst is ValidationSeverity.FAIL or contradicted:
        return (
            Status.FAIL,
            f"Reusable capability {cap_id}: positive reuse guidance is suppressed by failing or "
            "contradicted validation evidence; the evidence is retained below.",
        )
    if worst is ValidationSeverity.MANUAL_REVIEW:
        return (
            Status.MANUAL_REVIEW,
            f"Reusable capability {cap_id}: validation manual-review evidence prevents an "
            "unqualified recommendation; human review is required.",
        )
    if worst is ValidationSeverity.WARN:
        if discovery.confidence is Confidence.VERIFIED:
            return (
                Status.WARN,
                f"Reusable capability {cap_id}: qualified informational match (verified discovery "
                "with validation warnings); review the warnings before reuse.",
            )
        return (
            Status.MANUAL_REVIEW,
            f"Reusable capability {cap_id}: {discovery.confidence.value} discovery with validation "
            "warnings; human review is required and no positive reuse guidance is given.",
        )

    # No matched findings: with matched provenance the whole-registry validation
    # evaluated this capability, so absence of a finding is evaluated-clean.
    if discovery.confidence is Confidence.VERIFIED:
        if exemption:
            return (
                Status.WARN,
                f"Reusable capability {cap_id}: active consumer exemption; treated as a qualified "
                "match with an explicit warning and no verified-consumer claim.",
            )
        return (
            Status.PASS,
            f"Reusable capability {cap_id}: positive informational match (verified discovery, "
            "clean same-snapshot validation).",
        )
    return (
        Status.MANUAL_REVIEW,
        f"Reusable capability {cap_id}: {discovery.confidence.value} discovery evidence; "
        "informational manual-review advisory, no positive reuse guidance.",
    )


# --- evidence rendering ----------------------------------------------------


def _candidate_evidence(
    discovery: DiscoveryResult, matched: tuple[ValidationFinding, ...], prov_state: str
) -> list[str]:
    cap = discovery.capability
    evidence = [
        f"capability_id={cap.capability_id}",
        f"lifecycle_status={cap.status}",
        f"discovery_confidence={discovery.confidence.value}",
        f"provenance={prov_state}",
    ]
    evidence.extend(f"discovery_evidence={item}" for item in discovery.evidence_basis)
    evidence.extend(f"interface={item}" for item in cap.public_interfaces)
    evidence.extend(f"discovery_warning={item}" for item in discovery.warnings)
    evidence.extend(f"discovery_manual_review={item}" for item in discovery.manual_review_reasons)
    for finding in matched:
        evidence.append(
            f"validation_finding={finding.code}; surface={finding.surface}; "
            f"severity={finding.severity.value}; confidence={finding.confidence.value}"
        )
    if cap.known_consumer_exemption:
        evidence.append(f"consumer_exemption={cap.known_consumer_exemption}")
    else:
        evidence.extend(f"known_consumer={item}" for item in cap.known_consumers)
    evidence.extend(f"test={item}" for item in cap.tests)
    if cap.reuse_guidance:
        evidence.append(f"reuse_guidance={cap.reuse_guidance}")
    evidence.extend(f"side_effect={item}" for item in cap.side_effects)
    evidence.extend(f"invariant={item}" for item in cap.invariants)
    evidence.extend(f"compatibility={item}" for item in cap.compatibility)
    if not cap.compatibility and not cap.invariants:
        evidence.append("remaining_risk=behavioral-contract-not-evaluated")
    evidence.append(_AUTHORIZATION_EVIDENCE)
    return evidence


def _disc_sort_key(discovery: DiscoveryResult) -> tuple:
    return (
        discovery.confidence.value,
        discovery.provenance.digest if discovery.provenance is not None else "",
        discovery.evidence_basis,
        discovery.warnings,
        discovery.manual_review_reasons,
    )


def _conflicting_check(cap_id: str, group: list[DiscoveryResult]) -> CheckResult:
    evidence = [f"capability_id={cap_id}", f"conflicting_discovery_results={len(group)}"]
    for index, discovery in enumerate(sorted(group, key=_disc_sort_key)):
        evidence.append(
            f"variant={index}; confidence={discovery.confidence.value}; "
            f"provenance={'present' if discovery.provenance is not None else 'absent'}"
        )
    evidence.append(_AUTHORIZATION_EVIDENCE)
    return CheckResult(
        f"reuse candidate {cap_id}",
        Status.MANUAL_REVIEW,
        f"Reusable capability {cap_id}: multiple conflicting discovery results were supplied; "
        "positive reuse guidance is suppressed and every variant is preserved for human review.",
        evidence,
    )


def _unmatched_findings_check(unmatched: list[ValidationFinding]) -> CheckResult:
    ordered = sorted(
        unmatched,
        key=lambda f: (f.capability_id or "", f.code, f.surface, f.severity.value),
    )
    evidence = [
        f"validation_finding={finding.code}; capability_id={finding.capability_id or 'none'}; "
        f"surface={finding.surface}; severity={finding.severity.value}; "
        f"confidence={finding.confidence.value}"
        for finding in ordered
    ]
    evidence.append(_AUTHORIZATION_EVIDENCE)
    return CheckResult(
        "reuse unmatched validation findings",
        Status.MANUAL_REVIEW,
        "Validation findings without a matching discovery candidate are shown for human review "
        "and are not attached to any candidate.",
        evidence,
    )
