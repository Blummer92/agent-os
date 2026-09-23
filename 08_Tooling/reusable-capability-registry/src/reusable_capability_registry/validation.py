"""RC4 report-only registry validation orchestration (#494 / #254).

Deterministic, offline, static, report-only. Reuses ``RegistryReader`` and the
merged ``RegistryProvenance`` (#482); never re-implements canonicalization,
never imports/executes inspected modules, never mutates anything.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from . import inspection as insp
from .inspection import EvidenceOutcome
from .models import (
    VALIDATION_INFORMATIONAL_NOTICE,
    EvidenceConfidence,
    RegistryProvenance,
    UnsupportedProvenanceError,
    ValidationEvidence,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)
from .provenance import compute_registry_provenance
from .reader import (
    RegistryError,
    RegistryFileError,
    RegistryFormatError,
    RegistryReader,
    UnsupportedRegistryVersion,
)

_EXEMPTION_REASON_BOUND = 240

_CODE_MESSAGE = {
    "structure.registry-unreadable": "registry file could not be read",
    "structure.malformed-registry": "registry is malformed or invalid",
    "structure.unsupported-registry-version": "registry version is unsupported",
    "structure.successor-missing": "deprecated_by successor does not resolve to a registry record",
    "structure.provenance-unavailable": "registry provenance could not be computed",
    "structure.provenance-unsupported": "supplied expected provenance uses an unsupported algorithm or version",
    "structure.provenance-mismatch": "computed provenance does not match the supplied expected provenance",
    "path.invalid-format": "registered path is not a valid repository-relative POSIX path",
    "path.traversal": "registered path contains a parent-directory traversal",
    "path.outside-repository": "registered path resolves outside the repository",
    "path.missing": "registered path does not exist",
    "path.case-mismatch": "registered path does not match on-disk case",
    "path.symlink-outside": "registered path is a symlink resolving outside the repository",
    "path.symlink-inside": "registered path is an in-repository symlink",
    "path.noncanonical": "registered path has a non-canonical but resolvable spelling",
    "interface.malformed": "registered interface is not a valid module:Symbol",
    "interface.module-missing": "no registered canonical path maps to the interface module",
    "interface.module-ambiguous": "more than one registered canonical path maps to the interface module",
    "interface.syntax-error": "interface module has a syntax error",
    "interface.symbol-missing": "registered interface symbol has no static binding",
    "interface.dynamic-export": "registered interface symbol may originate dynamically",
    "interface.conditional-binding": "registered interface symbol is bound only conditionally",
    "interface.nested-symbol": "registered interface symbol is dotted/nested",
    "interface.local-source-unregistered": "interface re-export source is not a registered canonical path",
    "interface.non-python": "registered interface maps to a non-Python canonical path",
    "interface.conflicting-binding": "registered interface symbol is deleted or conflictingly rebound",
    "consumer.path-not-operational": "listed consumer path is not an operational source file",
    "consumer.interface-missing": "listed consumer does not reference a registered interface",
    "consumer.package-import-only": "listed consumer imports the package without using a registered symbol",
    "consumer.typing-only": "listed consumer references the interface only under type checking",
    "consumer.weak-text-only": "listed consumer references the interface only in text",
    "consumer.dynamic-usage": "listed consumer reaches the interface only dynamically",
    "consumer.conditional-usage": "listed consumer imports the interface only conditionally",
    "consumer.syntax-error": "listed consumer has a syntax error",
    "test.path-not-test": "listed test path is not a recognized test file",
    "test.import-only": "listed test imports but does not exercise the interface",
    "test.unrelated": "listed test does not reference the interface",
    "test.weak-text-only": "listed test references the interface only in text",
    "test.dynamic-usage": "listed test reaches the interface only dynamically",
    "test.skipped-only": "listed test evidence is skipped or xfailed only",
    "test.syntax-error": "listed test has a syntax error",
    "test.helper-boundary-unresolved": "listed test reaches the interface only through an unresolved helper",
    "owner.unknown-agent": "owner is not a canonical agent",
    "owner.unmapped-alias": "owner alias does not resolve to a canonical agent",
    "owner.ambiguous-alias": "owner alias is provisional or ambiguous",
    "owner.overlay-missing": "canonical agent overlay is missing",
    "owner.source-conflict": "governed ownership sources conflict",
    "owner.duplicate-support": "supporting agent is duplicated",
    "owner.primary-also-support": "primary owner is also listed as a supporting agent",
    "owner.canonical-case": "owner spelling differs from the canonical agent name",
    "exemption.active-no-consumer": "active exemption with no operational consumer",
    "exemption.active-test-only": "active exemption with only test-only consumer evidence",
    "exemption.consumer-unresolved": "active exemption with unresolved consumer evidence",
    "exemption.missing-required": "no operational consumer and no exemption where one is required",
    "exemption.recommend-review": "operational-consumer evidence is present; consider reviewing whether the exemption is still necessary",
}


def _message(code: str) -> str:
    return _CODE_MESSAGE.get(code, code)


def _finding_from_outcome(outcome: EvidenceOutcome, capability_id: str | None) -> ValidationFinding:
    assert outcome.code is not None
    surface = outcome.code.split(".", 1)[0]
    return ValidationFinding(
        code=outcome.code,
        confidence=outcome.confidence,
        severity=outcome.severity,
        capability_id=capability_id,
        surface=surface,
        message=_message(outcome.code),
        evidence=outcome.evidence,
        manual_review_reason=outcome.manual_review_reason,
    )


def _structural_finding(code: str, detail: str) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        confidence=EvidenceConfidence.CONTRADICTED,
        severity=ValidationSeverity.FAIL,
        capability_id=None,
        surface="structure",
        message=_message(code),
        evidence=(ValidationEvidence(None, None, None, "registry", detail[:200] or _message(code)),),
    )


def _structural_fail_report(exc: RegistryError, record_count: int = 0) -> ValidationReport:
    if isinstance(exc, RegistryFileError):
        code = "structure.registry-unreadable"
    elif isinstance(exc, UnsupportedRegistryVersion):
        code = "structure.unsupported-registry-version"
    elif isinstance(exc, RegistryFormatError):
        code = "structure.malformed-registry"
    else:
        code = "structure.malformed-registry"
    finding = _structural_finding(code, str(exc))
    return ValidationReport.from_findings(
        [finding], provenance=None, capabilities_checked=record_count, checks_run=1
    )


def _lifecycle_adjust(outcome: EvidenceOutcome, status: str) -> EvidenceOutcome:
    """Apply the #254 §9 lifecycle-severity matrix to a base outcome."""
    if outcome.code in ("interface.symbol-missing", "interface.module-missing") and status in ("deprecated", "replaced"):
        return replace(outcome, severity=ValidationSeverity.WARN)
    if outcome.code in ("test.unrelated", "test.weak-text-only") and status != "active":
        return replace(outcome, severity=ValidationSeverity.WARN)
    return outcome


def _bounded_reason(reason: str | None) -> str:
    if not reason:
        return "(no exemption reason)"
    if len(reason) <= _EXEMPTION_REASON_BOUND:
        return reason
    return f"{reason[:_EXEMPTION_REASON_BOUND]} …(+{len(reason) - _EXEMPTION_REASON_BOUND} chars)"


# --- bounded governance parsing --------------------------------------------


class _Governance:
    def __init__(self, root: Path) -> None:
        self.canonical: dict[str, tuple[str, str]] = {}   # lower name -> (canonical, overlay slug)
        self.canonical_conflict: set[str] = set()
        self.alias_active: dict[str, str] = {}            # lower alias -> canonical
        self.alias_provisional: set[str] = set()
        self.alias_ambiguous: set[str] = set()
        self._root = root
        self._load()

    def _load(self) -> None:
        inheritance = _read(self._root / "04_Registry" / "agent-inheritance-registry.md")
        for row in _table_rows(inheritance, ("Agent", "Overlay")):
            if len(row) < 3:
                continue
            name = row[0].strip()
            overlay = row[2].strip().strip("`")
            if not name or name.lower() == "agent":
                continue
            key = name.lower()
            if key in self.canonical and self.canonical[key] != (name, overlay):
                self.canonical_conflict.add(key)
            self.canonical[key] = (name, overlay)
        alias = _read(self._root / "04_Registry" / "legacy-agent-alias-registry.md")
        for row in _table_rows(alias, ("Legacy Name / Property", "Canonical Agent", "Status")):
            if len(row) < 4:
                continue
            legacy = row[0].strip().lower()
            canonical = row[1].strip()
            status = row[3].strip().lower()
            if not legacy:
                continue
            if "provisional" in status:
                self.alias_provisional.add(legacy)
            else:
                self.alias_active[legacy] = canonical
        for row in _table_rows(alias, ("Legacy Name / Property", "Default Canonical Agent", "Alternate Canonical Agent")):
            if row and row[0].strip():
                self.alias_ambiguous.add(row[0].strip().lower())

    def overlay_exists(self, slug: str) -> bool:
        return (self._root / "02_Agent_Overlays" / f"{slug}.md").is_file()


def _canonical_of(gov: _Governance, name: str) -> str:
    key = name.strip().lower()
    if key in gov.canonical:
        return gov.canonical[key][0]
    if key in gov.alias_active:
        return gov.alias_active[key]
    return name.strip()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _table_rows(text: str, required_headers: tuple[str, ...]) -> list[list[str]]:
    rows: list[list[str]] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(any(header in cell for cell in cells) for header in required_headers):
            in_table = True
            continue
        if in_table:
            if set("".join(cells)) <= {"-", ":", " "}:  # separator row
                continue
            rows.append(cells)
    return rows


def _agent_evidence(name: str, detail: str) -> tuple[ValidationEvidence, ...]:
    return (ValidationEvidence(None, None, None, "agent-inheritance-registry", detail),)


def _classify_agent(gov: _Governance, name: str) -> EvidenceOutcome | None:
    """Return None when the agent resolves verified, else an owner.* outcome."""
    key = name.strip().lower()
    if key in gov.canonical_conflict:
        return EvidenceOutcome(
            "owner.source-conflict", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW,
            _agent_evidence(name, f"agent {name!r} has conflicting canonical rows"),
            "governed ownership sources conflict",
        )
    if key in gov.canonical:
        canonical, overlay = gov.canonical[key]
        if not gov.overlay_exists(overlay):
            return EvidenceOutcome(
                "owner.overlay-missing", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL,
                _agent_evidence(name, f"overlay {overlay!r} for {canonical!r} is missing"),
            )
        if canonical != name.strip():
            return EvidenceOutcome(
                "owner.canonical-case", EvidenceConfidence.PROBABLE, ValidationSeverity.WARN,
                _agent_evidence(name, f"owner {name!r} canonicalizes to {canonical!r}"),
            )
        return None
    if key in gov.alias_ambiguous or key in gov.alias_provisional:
        return EvidenceOutcome(
            "owner.ambiguous-alias", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW,
            _agent_evidence(name, f"owner {name!r} is a provisional or ambiguous alias"),
            "owner alias requires manual resolution",
        )
    if key in gov.alias_active:
        canonical = gov.alias_active[key]
        if canonical.lower() in gov.canonical:
            return EvidenceOutcome(
                "owner.canonical-case", EvidenceConfidence.PROBABLE, ValidationSeverity.WARN,
                _agent_evidence(name, f"active legacy alias {name!r} resolves to {canonical!r}"),
            )
        return EvidenceOutcome(
            "owner.unmapped-alias", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL,
            _agent_evidence(name, f"alias {name!r} target {canonical!r} is not a canonical agent"),
        )
    return EvidenceOutcome(
        "owner.unknown-agent", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL,
        _agent_evidence(name, f"owner {name!r} is not a canonical agent"),
    )


# --- per-record validation -------------------------------------------------


def _validate_record(root: Path, record, gov: _Governance, known_ids: frozenset[str]) -> tuple[list[ValidationFinding], int]:
    findings: list[ValidationFinding] = []
    checks = 0
    cid = record.capability_id
    status = record.status
    interfaces = record.public_interfaces

    for path in record.canonical_paths:
        checks += 1
        outcome = insp.inspect_canonical_path(root, path)
        if outcome.code is not None:
            findings.append(_finding_from_outcome(outcome, cid))

    for interface in record.public_interfaces:
        checks += 1
        outcome = _lifecycle_adjust(insp.inspect_python_interface(root, interface, record.canonical_paths), status)
        if outcome.code is not None:
            findings.append(_finding_from_outcome(outcome, cid))

    for test_path in record.tests:
        checks += 1
        outcome = _lifecycle_adjust(insp.inspect_test(root, test_path, interfaces), status)
        if outcome.code is not None:
            findings.append(_finding_from_outcome(outcome, cid))

    has_operational = False
    has_test_only_consumer = False
    has_unresolved_consumer = False
    for consumer_path in record.known_consumers:
        checks += 1
        outcome = insp.inspect_consumer(root, consumer_path, interfaces, record.canonical_paths)
        if outcome.code is None:
            has_operational = True
        else:
            findings.append(_finding_from_outcome(outcome, cid))
            if outcome.source_type == "test-only-consumer-evidence":
                has_test_only_consumer = True
            if outcome.code in ("consumer.dynamic-usage", "consumer.conditional-usage"):
                has_unresolved_consumer = True

    findings.extend(_consumer_exemption_findings(
        record, cid, status, has_operational, has_test_only_consumer, has_unresolved_consumer
    ))
    checks += 1

    # ownership
    checks += 1
    owner_outcome = _classify_agent(gov, record.owner_agent)
    if owner_outcome is not None:
        findings.append(_finding_from_outcome(owner_outcome, cid))
    owner_canonical = _canonical_of(gov, record.owner_agent)
    seen_support: set[str] = set()
    for support in record.supporting_agents:
        checks += 1
        support_outcome = _classify_agent(gov, support)
        if support_outcome is not None:
            findings.append(_finding_from_outcome(support_outcome, cid))
        canonical = _canonical_of(gov, support)
        if canonical == owner_canonical:
            findings.append(_owner_finding("owner.primary-also-support", cid, support))
        elif canonical in seen_support:
            findings.append(_owner_finding("owner.duplicate-support", cid, support))
        seen_support.add(canonical)

    # successor
    if status in ("deprecated", "replaced"):
        checks += 1
        successor = record.deprecated_by
        if not successor or successor not in known_ids:
            findings.append(ValidationFinding(
                "structure.successor-missing", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL,
                cid, "structure", _message("structure.successor-missing"),
                (ValidationEvidence(None, None, successor, "registry", f"deprecated_by {successor!r} unresolved"),),
            ))

    return findings, checks


def _owner_finding(code: str, cid: str, support: str) -> ValidationFinding:
    confidence = EvidenceConfidence.PROBABLE
    return ValidationFinding(
        code, confidence, ValidationSeverity.WARN, cid, "owner", _message(code),
        (ValidationEvidence(None, None, None, "support-resolution", f"supporting agent {support!r}"),),
    )


def _consumer_exemption_findings(
    record, cid: str, status: str, has_operational: bool, has_test_only: bool, has_unresolved: bool
) -> list[ValidationFinding]:
    exemption = record.known_consumer_exemption
    evidence = (ValidationEvidence(None, None, None, "exemption-reason", _bounded_reason(exemption)),)
    if exemption is not None:
        if has_operational:
            return [ValidationFinding(
                "exemption.recommend-review", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW,
                cid, "exemption", _message("exemption.recommend-review"), evidence,
                "operational-consumer evidence is present alongside an active exemption",
            )]
        if has_unresolved:
            return [ValidationFinding(
                "exemption.consumer-unresolved", EvidenceConfidence.MANUAL_REVIEW, ValidationSeverity.MANUAL_REVIEW,
                cid, "exemption", _message("exemption.consumer-unresolved"), evidence,
                "consumer evidence for an exempt capability is unresolved",
            )]
        if has_test_only:
            return [ValidationFinding(
                "exemption.active-test-only", EvidenceConfidence.PROBABLE, ValidationSeverity.WARN,
                cid, "exemption", _message("exemption.active-test-only"), evidence,
            )]
        return [ValidationFinding(
            "exemption.active-no-consumer", EvidenceConfidence.UNVERIFIED, ValidationSeverity.WARN,
            cid, "exemption", _message("exemption.active-no-consumer"), evidence,
        )]
    # no exemption
    if not has_operational and status != "internal-only" and not record.known_consumers:
        severity = ValidationSeverity.FAIL if status == "active" else ValidationSeverity.WARN
        return [ValidationFinding(
            "exemption.missing-required", EvidenceConfidence.CONTRADICTED, severity,
            cid, "exemption", _message("exemption.missing-required"),
            (ValidationEvidence(None, None, None, "exemption-reason", "no operational consumer and no exemption"),),
        )]
    return []


# --- public entry point ----------------------------------------------------


def validate_registry(
    repository_root,
    registry_path=None,
    *,
    expected_provenance: RegistryProvenance | None = None,
) -> ValidationReport:
    root = insp.resolve_repository_root(repository_root)
    if registry_path is not None:
        candidate = Path(registry_path)
        reg_path = candidate if candidate.is_absolute() else root / candidate
    else:
        reg_path = root / "04_Registry" / "reusable-capabilities.yml"

    try:
        reader = RegistryReader(reg_path)
    except RegistryError as exc:
        return _structural_fail_report(exc)

    try:
        provenance = compute_registry_provenance(reader)
    except RegistryError as exc:
        finding = _structural_finding("structure.provenance-unavailable", str(exc))
        return ValidationReport.from_findings(
            [finding], provenance=None, capabilities_checked=len(reader.records), checks_run=1
        )

    findings: list[ValidationFinding] = []
    checks_run = 0

    if expected_provenance is not None:
        checks_run += 1
        try:
            expected_provenance.require_supported()
            supported = True
        except UnsupportedProvenanceError:
            supported = False
        if not supported:
            findings.append(_structural_finding(
                "structure.provenance-unsupported",
                f"expected provenance {expected_provenance.algorithm!r} v{expected_provenance.algorithm_version}",
            ))
        elif expected_provenance != provenance:
            differing = [
                name for name in ("algorithm", "algorithm_version", "registry_version", "digest")
                if getattr(expected_provenance, name) != getattr(provenance, name)
            ]
            findings.append(_structural_finding(
                "structure.provenance-mismatch", f"differing provenance fields: {', '.join(differing)}"
            ))

    gov = _Governance(root)
    known_ids = frozenset(record.capability_id for record in reader.records)
    for record in reader.records:
        record_findings, record_checks = _validate_record(root, record, gov, known_ids)
        findings.extend(record_findings)
        checks_run += record_checks

    return ValidationReport.from_findings(
        findings,
        provenance=provenance,
        capabilities_checked=len(reader.records),
        checks_run=checks_run,
    )
