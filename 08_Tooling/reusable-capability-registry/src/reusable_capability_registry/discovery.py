from __future__ import annotations

from collections.abc import Iterable

from .models import CapabilityRecord, Confidence, DiscoveryResult
from .reader import RegistryFormatError, RegistryReader

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
    return _unique_sorted(
        record for group in groups for record in group if record.capability_id in common
    )


def _warnings(record: CapabilityRecord) -> tuple[str, ...]:
    warnings = {
        "behavioral-compatibility-not-evaluated",
        "ownership-not-validated",
    }
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
    evidence: list[str] = []
    normalized_keyword_used = False

    if capability_id:
        record = reader.by_id(capability_id)
        groups.append((record,) if record else ())
        evidence.append("exact-capability-id-match")
    for keyword in keyword_values:
        matches = reader.lookup("keyword", keyword)
        groups.append(matches)
        exact = any(keyword == item for record in matches for item in record.keywords)
        evidence.append("exact-keyword-match" if exact else "normalized-keyword-match")
        normalized_keyword_used = normalized_keyword_used or not exact
    for field, value, code in (
        ("owner", owner, "owner-field-match"),
        ("status", status, "status-field-match"),
        ("canonical_path", canonical_path, "canonical-path-match"),
        ("public_interface", public_interface, "public-interface-match"),
    ):
        if value:
            groups.append(reader.lookup(field, value))
            evidence.append(code)

    records = _intersection(groups)
    ambiguous_keyword_only = bool(keyword_values) and len(records) > 1 and not any(
        (capability_id, owner, status, canonical_path, public_interface)
    )

    results: list[DiscoveryResult] = []
    for record in records:
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
                evidence_basis=tuple(sorted(set(evidence))),
                warnings=_warnings(record),
                manual_review_reasons=manual_review_reasons,
            )
        )
    return tuple(results)
