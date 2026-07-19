from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import yaml

_METADATA_KEY = "agent_os_issue_acceptance"
_FENCED_YAML_RE = re.compile(r"```(?:yaml|yml)\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_GOVERNED_FIELDS = {
    "entity_id",
    "owner_agent",
    "source_of_truth",
    "external_writes",
    "required_files",
    "forbidden_paths",
    "required_tests",
    "required_docs",
    "banned_patterns",
    "manual_review",
    "documentation_impact",
    "documentation_expected_change",
    "documentation_exemption_reason",
}


class ScanFinding(str, Enum):
    SCAN_COMPLETE = "scan-complete"
    METADATA_MISSING = "metadata-missing"
    METADATA_SINGLE = "metadata-single"
    METADATA_DUPLICATED_IDENTICAL = "metadata-duplicated-identical"
    METADATA_CONFLICTING = "metadata-conflicting"
    METADATA_MALFORMED = "metadata-malformed"
    SOURCE_PARTIAL = "source-partial"
    SOURCE_INACCESSIBLE = "source-inaccessible"
    SOURCE_UNSUPPORTED = "source-unsupported"
    SOURCE_STALE = "source-stale"
    UNKNOWN_GOVERNED_FIELD = "unknown-governed-field"
    IDENTITY_FINDING_PRESENT = "identity-finding-present"


class AdoptionClass(str, Enum):
    STRICT_NATIVE = "strict-native"
    LEGACY_COMPATIBLE = "legacy-compatible"
    ADOPTION_CANDIDATE = "adoption-candidate"
    ADOPTION_BLOCKED = "adoption-blocked"
    IDENTITY_QUARANTINED = "identity-quarantined"
    NOT_ISSUEPLAN_SOURCE = "not-issueplan-source"


@dataclass(frozen=True)
class SourceEnvelope:
    source_locator: str
    source_revision: str
    content: str
    source_family: str = "github-issue"
    retrieval_complete: bool = True
    pagination_complete: bool = True
    accessible: bool = True
    expected_revision: str | None = None


@dataclass(frozen=True)
class FieldProvenance:
    field_name: str
    normalized_value: Any
    source_locator: str
    source_revision: str
    source_region_or_block: str
    raw_excerpt_or_reference: str
    extraction_status: str
    profile_classification: str


@dataclass(frozen=True)
class MetadataCandidate:
    index: int
    raw: str
    parsed: dict[str, Any] | None
    malformed: bool = False


@dataclass(frozen=True)
class ScanResult:
    source_locator: str
    source_revision: str
    findings: tuple[ScanFinding, ...]
    adoption_class: AdoptionClass
    candidates: tuple[MetadataCandidate, ...] = ()
    provenance: tuple[FieldProvenance, ...] = ()
    strict_valid: bool = False
    execution_authorized: bool = False
    evidence: tuple[str, ...] = field(default_factory=tuple)


def scan_issueplan_source(envelope: SourceEnvelope) -> ScanResult:
    """Scan one bounded source without network calls, mutation, or authorization inference."""
    preflight = _preflight_findings(envelope)
    if preflight:
        adoption = (
            AdoptionClass.NOT_ISSUEPLAN_SOURCE
            if ScanFinding.SOURCE_UNSUPPORTED in preflight
            else AdoptionClass.ADOPTION_BLOCKED
        )
        return _result(envelope, preflight, adoption)

    candidates = tuple(_discover_candidates(envelope.content))
    findings: list[ScanFinding] = [ScanFinding.SCAN_COMPLETE]
    if not candidates:
        findings.append(ScanFinding.METADATA_MISSING)
        return _result(envelope, findings, AdoptionClass.LEGACY_COMPATIBLE)

    malformed = [candidate for candidate in candidates if candidate.malformed]
    valid = [candidate for candidate in candidates if candidate.parsed is not None]
    if malformed:
        findings.append(ScanFinding.METADATA_MALFORMED)

    if len(candidates) == 1:
        findings.append(ScanFinding.METADATA_SINGLE)
    elif _candidates_identical(valid) and not malformed:
        findings.append(ScanFinding.METADATA_DUPLICATED_IDENTICAL)
    else:
        findings.append(ScanFinding.METADATA_CONFLICTING)

    provenance = tuple(_field_provenance(envelope, valid))
    unknown_fields = {
        item.field_name
        for item in provenance
        if item.extraction_status == "unknown-field"
    }
    if unknown_fields:
        findings.append(ScanFinding.UNKNOWN_GOVERNED_FIELD)

    identities = {
        str(candidate.parsed.get("entity_id")).strip()
        for candidate in valid
        if candidate.parsed and candidate.parsed.get("entity_id")
    }
    if len(identities) > 1:
        findings.append(ScanFinding.IDENTITY_FINDING_PRESENT)
        adoption = AdoptionClass.IDENTITY_QUARANTINED
    elif malformed or len(candidates) != 1 or unknown_fields:
        adoption = AdoptionClass.ADOPTION_BLOCKED
    elif identities:
        adoption = AdoptionClass.STRICT_NATIVE
    else:
        adoption = AdoptionClass.ADOPTION_CANDIDATE

    strict_valid = adoption == AdoptionClass.STRICT_NATIVE
    return _result(envelope, findings, adoption, candidates, provenance, strict_valid)


def _preflight_findings(envelope: SourceEnvelope) -> list[ScanFinding]:
    findings: list[ScanFinding] = []
    if envelope.source_family != "github-issue":
        findings.append(ScanFinding.SOURCE_UNSUPPORTED)
    if not envelope.accessible:
        findings.append(ScanFinding.SOURCE_INACCESSIBLE)
    if not envelope.retrieval_complete or not envelope.pagination_complete:
        findings.append(ScanFinding.SOURCE_PARTIAL)
    if envelope.expected_revision and envelope.expected_revision != envelope.source_revision:
        findings.append(ScanFinding.SOURCE_STALE)
    return findings


def _discover_candidates(content: str) -> list[MetadataCandidate]:
    candidates: list[MetadataCandidate] = []
    for index, match in enumerate(_FENCED_YAML_RE.finditer(content or ""), start=1):
        raw = match.group(1)
        try:
            parsed = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            candidates.append(MetadataCandidate(index, raw, None, True))
            continue
        if not isinstance(parsed, dict) or _METADATA_KEY not in parsed:
            continue
        block = parsed.get(_METADATA_KEY)
        if not isinstance(block, dict):
            candidates.append(MetadataCandidate(index, raw, None, True))
            continue
        candidates.append(MetadataCandidate(index, raw, dict(block)))
    return candidates


def _candidates_identical(candidates: list[MetadataCandidate]) -> bool:
    if not candidates:
        return False
    first = candidates[0].parsed
    return all(candidate.parsed == first for candidate in candidates[1:])


def _field_provenance(
    envelope: SourceEnvelope, candidates: list[MetadataCandidate]
) -> list[FieldProvenance]:
    provenance: list[FieldProvenance] = []
    for candidate in candidates:
        assert candidate.parsed is not None
        for field_name in sorted(candidate.parsed):
            value = candidate.parsed[field_name]
            known = field_name in _GOVERNED_FIELDS
            provenance.append(
                FieldProvenance(
                    field_name=field_name,
                    normalized_value=value,
                    source_locator=envelope.source_locator,
                    source_revision=envelope.source_revision,
                    source_region_or_block=f"metadata-block-{candidate.index}",
                    raw_excerpt_or_reference=f"block={candidate.index};field={field_name}",
                    extraction_status="present-valid" if known else "unknown-field",
                    profile_classification="strict" if known else "unclassified",
                )
            )
    return provenance


def _result(
    envelope: SourceEnvelope,
    findings: list[ScanFinding],
    adoption_class: AdoptionClass,
    candidates: tuple[MetadataCandidate, ...] = (),
    provenance: tuple[FieldProvenance, ...] = (),
    strict_valid: bool = False,
) -> ScanResult:
    ordered = tuple(dict.fromkeys(findings))
    return ScanResult(
        source_locator=envelope.source_locator,
        source_revision=envelope.source_revision,
        findings=ordered,
        adoption_class=adoption_class,
        candidates=candidates,
        provenance=provenance,
        strict_valid=strict_valid,
        execution_authorized=False,
        evidence=(
            f"source_locator={envelope.source_locator}",
            f"source_revision={envelope.source_revision}",
            f"candidate_count={len(candidates)}",
        ),
    )
