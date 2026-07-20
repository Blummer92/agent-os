from __future__ import annotations

from typing import Any

from .issueplan_scanner import (
    ScanFinding,
    ScanResult,
    SourceEnvelope,
    scan_issueplan_source,
)
from .models import IssueMetadata

_COMPATIBILITY_SOURCE_LOCATOR = "compatibility:raw-body"
_LEGACY_COMPATIBILITY_FIELDS = frozenset({"tier"})

# Findings that make a legacy compatibility projection unsafe. Strict-field
# incompleteness is intentionally not listed: legacy issue bodies may remain
# readable without being promoted to strict IssuePlan validity. Unknown fields
# are evaluated separately so the historical readiness-only ``tier`` key can be
# read without silently admitting any new governed field.
_BLOCKING_FINDINGS = frozenset(
    {
        ScanFinding.METADATA_DUPLICATED_IDENTICAL,
        ScanFinding.METADATA_CONFLICTING,
        ScanFinding.METADATA_MALFORMED,
        ScanFinding.SOURCE_PARTIAL,
        ScanFinding.SOURCE_INACCESSIBLE,
        ScanFinding.SOURCE_UNSUPPORTED,
        ScanFinding.SOURCE_STALE,
        ScanFinding.PROFILE_VERSION_UNSUPPORTED,
        ScanFinding.IDENTITY_FINDING_PRESENT,
    }
)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return [str(value).strip()]


def scan_issue_metadata(
    issue_body: str,
    *,
    source_locator: str = _COMPATIBILITY_SOURCE_LOCATOR,
    source_revision: str = "",
    source_family: str = "github-issue",
    retrieval_complete: bool = True,
    pagination_complete: bool = True,
    accessible: bool = True,
    expected_revision: str | None = None,
) -> ScanResult:
    """Scan one issue body through the canonical all-candidates-first scanner.

    The compatibility defaults are deliberately source-unbound. They identify the
    input as a raw body without fabricating a GitHub issue identity, source revision,
    or freshness claim.
    """

    return scan_issueplan_source(
        SourceEnvelope(
            source_locator=source_locator,
            source_revision=source_revision,
            source_family=source_family,
            content=issue_body or "",
            retrieval_complete=retrieval_complete,
            pagination_complete=pagination_complete,
            accessible=accessible,
            expected_revision=expected_revision,
        )
    )


def _unknown_field_names(scan_result: ScanResult) -> set[str]:
    return {
        item.field_name
        for item in scan_result.provenance
        if item.extraction_status == "unknown-field"
    }


def scanner_manual_review_items(scan_result: ScanResult) -> list[str]:
    """Return stable compatibility reason codes for unsafe scanner findings."""

    items = [
        f"issueplan-scanner:{finding.value}"
        for finding in scan_result.findings
        if finding in _BLOCKING_FINDINGS
    ]
    unknown_fields = _unknown_field_names(scan_result)
    unsupported_unknowns = unknown_fields - _LEGACY_COMPATIBILITY_FIELDS
    if unsupported_unknowns:
        items.append("issueplan-scanner:unknown-governed-field")
    if len(scan_result.candidates) != 1 and not items:
        items.append("issueplan-scanner:unresolved-candidate-set")
    return items


def _scanner_raw_evidence(scan_result: ScanResult) -> dict[str, Any]:
    """Preserve bounded scanner evidence when no safe legacy projection exists."""

    return {
        "_scanner_findings": [finding.value for finding in scan_result.findings],
        "_scanner_adoption_class": scan_result.adoption_class.value,
        "_scanner_evidence": list(scan_result.evidence),
        "_scanner_candidates": [
            {
                "index": candidate.index,
                "malformed": candidate.malformed,
                "parsed": dict(candidate.parsed) if candidate.parsed is not None else None,
            }
            for candidate in scan_result.candidates
        ],
        "_scanner_provenance": [
            {
                "field_name": item.field_name,
                "normalized_value": item.normalized_value,
                "source_locator": item.source_locator,
                "source_revision": item.source_revision,
                "source_region_or_block": item.source_region_or_block,
                "raw_excerpt_or_reference": item.raw_excerpt_or_reference,
                "extraction_status": item.extraction_status,
                "profile_classification": item.profile_classification,
            }
            for item in scan_result.provenance
        ],
    }


def project_issue_metadata(scan_result: ScanResult) -> IssueMetadata:
    """Project one safe scanner result into the legacy ``IssueMetadata`` model.

    Missing metadata remains the historical empty value. Malformed, duplicate,
    conflicting, stale, partial, inaccessible, unsupported, truly unknown-field,
    and identity-quarantined evidence remains distinct and fails closed. The
    historical readiness-only ``tier`` key is the sole bounded compatibility field.
    """

    findings = set(scan_result.findings)
    if ScanFinding.METADATA_MISSING in findings and not scan_result.candidates:
        return IssueMetadata.empty()

    manual_review = scanner_manual_review_items(scan_result)
    candidate = scan_result.candidates[0] if len(scan_result.candidates) == 1 else None
    block = candidate.parsed if candidate is not None else None

    if manual_review or block is None:
        declared_manual_review = _as_list(block.get("manual_review")) if block else []
        return IssueMetadata(
            present=False,
            manual_review=[*declared_manual_review, *manual_review],
            raw=_scanner_raw_evidence(scan_result),
        )

    return IssueMetadata(
        present=True,
        owner_agent=block.get("owner_agent"),
        source_of_truth=block.get("source_of_truth"),
        external_writes=block.get("external_writes"),
        required_files=_as_list(block.get("required_files")),
        forbidden_paths=_as_list(block.get("forbidden_paths")),
        required_tests=_as_list(block.get("required_tests")),
        required_docs=_as_list(block.get("required_docs")),
        banned_patterns=_as_list(block.get("banned_patterns")),
        manual_review=_as_list(block.get("manual_review")),
        raw=dict(block),
        documentation_impact=block.get("documentation_impact"),
        documentation_expected_change=block.get("documentation_expected_change"),
        documentation_exemption_reason=block.get("documentation_exemption_reason"),
    )


def parse_issue_metadata(issue_body: str) -> IssueMetadata:
    """Compatibility facade backed exclusively by the canonical IssuePlan scanner."""

    return project_issue_metadata(scan_issue_metadata(issue_body))
