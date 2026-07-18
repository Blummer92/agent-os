from __future__ import annotations

from collections.abc import Iterable

from .models import CapabilityRecord, Confidence, DiscoveryResult
from .reader import RegistryFormatError, RegistryReader, normalize_keyword

INFORMATIONAL_NOTICE = (
    "Discovery evidence is informational and does not authorize implementation, "
    "repository writes, readiness changes, or merge."
)


def _unique_sorted(records: Iterable[CapabilityRecord]) -> tuple[CapabilityRecord, ...]:
    by_id = {record.capability_id: record for record in records}
    return tuple(by_id[key] for key in sorted(by_id))


def _intersection(groups: list[tuple[CapabilityRecord, ...]]) -> tuple[CapabilityRecord, ...]:
    if not groups:
        return ()
    common = {record.capability_id for record in groups[0]}
    for group in groups[1:]:
        common &= {record.capability_id for record in group}
    return _unique_sorted(record for group in groups for record in group if record.capability_id in common)


def _warnings(record: CapabilityRecord) -> tuple[str, ...]:
    warnings = {"behavioral-compatibility-not-evaluated", "ownership-not-validated"}
    if record.known_consumers or record.known_consumer_exemption:
        warnings.add("consumer-evidence-not-validated")
    if record.tests:
        warnings.add("test-evidence-not-validated")
    if record.known_consumer_exemption:
        warnings.add("known-consumer-exemption-active")
    if any(":" in interface for interface in record.public_interfaces):
        warnings.add("direct-module-stability-commitment")
    if not record.tests or (not record.known_consumers and not record.known_consumer_exemption):
        warnings.add("optional-registry-evidence-missing")
    return tuple(sorted(warnings))


def _keyword_evidence(record: CapabilityRecord, keywords: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
    evidence: list[str] = []
    normalized_used = False
    normalized_record_keywords = {normalize_keyword(value) for value in record.keywords}
    for keyword in keywords:
        if keyword in record.keywords:
            evidence.append("exact-keyword-match")
        elif normalize_keyword(keyword) in normalized_record_keywords:
            evidence.append("normalized-keyword-match")
            normalized_used = True
        else:
            raise RegistryFormatError("internal discovery mismatch for keyword evidence")
    return tuple(sorted(set(evidence))), normalized_used


def discover_capabilities(
    reader: RegistryReader,
    *,
    capability_id: str | None = None,
    keywords: Iterable[str] = (),
    owner: str | None = None,
    status: str | None = None,
    canonical_path: str | None = None,
    public_interface: str | None = None,
) -> tuple[DiscoveryResult, ...]:
    keyword_values = tuple(value for value in keywords if value and value.strip())
    if not any((capability_id, keyword_values, owner, status, canonical_path, public_interface)):
        raise RegistryFormatError("at least one lookup option is required")

    groups: list[tuple[CapabilityRecord, ...]] = []
    fixed_evidence: list[str] = []

    if capability_id:
        record = reader.by_id(capability_id)
        groups.append((record,) if record else ())
        fixed_evidence.append("exact-capability-id-match")
    for keyword in keyword_values:
        groups.append(reader.lookup("keyword", keyword))
    for field, value, code in (
        ("owner", owner, "owner-field-match"),
        ("status", status, "status-field-match"),
        ("canonical_path", canonical_path, "canonical-path-match"),
        ("public_interface", public_interface, "public-interface-match"),
    ):
        if value:
            groups.append(reader.lookup(field, value))
            fixed_evidence.append(code)

    records = _intersection(groups)
    ambiguous_keyword_only = bool(keyword_values) and len(records) > 1 and not any(
        (capability_id, owner, status, canonical_path, public_interface)
    )

    results: list[DiscoveryResult] = []
    for record in records:
        keyword_evidence, normalized_keyword_used = _keyword_evidence(record, keyword_values)
        manual_review_reasons: tuple[str, ...] = ()
        if ambiguous_keyword_only:
            confidence = Confidence.MANUAL_REVIEW
            manual_review_reasons = ("multiple-equally-plausible-candidates",)
        elif normalized_keyword_used:
            confidence = Confidence.PROBABLE
        else:
            confidence = Confidence.VERIFIED
        results.append(
            DiscoveryResult(
                capability=record,
                confidence=confidence,
                evidence_basis=tuple(sorted(set(fixed_evidence) | set(keyword_evidence))),
                warnings=_warnings(record),
                manual_review_reasons=manual_review_reasons,
            )
        )
    return tuple(results)
