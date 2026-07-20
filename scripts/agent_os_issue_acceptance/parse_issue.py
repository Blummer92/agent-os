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

_BLOCKING_FINDINGS = frozenset(
    {
        ScanFinding.METADATA_DUPLICATED_IDENTICAL,
        ScanFinding.METADATA_CONFLICTING,
        ScanFinding.METADATA_MALFORMED,
        ScanFinding.SOURCE_PARTIAL,
        ScanFinding.SOURCE_INACCESSIBLE,
        ScanFinding.SOURCE_UNSUPPORTED,
        ScanFinding.SOURCE_STALE,
        ScanFinding.UNKNOWN_GOVERNED_FIELD,
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
    retrieval_complete: bool = True,
    pagination_complete: bool = True,
    accessible: bool = True,
    expected_revision: str | None = None,
) -> ScanResult:
    """Run the canonical scanner for an issue body.

    The default compatibility call is intentionally source-unbound: it uses an
    explicit compatibility locator and an empty revision rather than fabricating
    GitHub identity or freshness evidence.
    """

    return scan_issueplan_source(
        SourceEnvelope(
            source_locator=source_locator,
            source_revision=source_revision,
            content=issue_body or "",
            retrieval_complete=retrieval_complete,
            pagination_complete=pagination_complete,
            accessible=accessible,
            expected_revision=expected_revision,
        )
    )


def project_issue_metadata(scan_result: ScanResult) -> IssueMetadata:
    """Project one unambiguous scanner result into the legacy metadata model."""

    findings = set(scan_result.findings)
    if ScanFinding.METADATA_MISSING in findings:
        return IssueMetadata.empty()

    if findings & _BLOCKING_FINDINGS:
        return IssueMetadata(
            present=False,
            manual_review=[
                f"issueplan-scanner:{finding.value}"
                for finding in scan_result.findings
                if finding in _BLOCKING_FINDINGS
            ],
            raw={
                "_scanner_findings": [finding.value for finding in scan_result.findings],
                "_scanner_evidence": list(scan_result.evidence),
            },
        )

    if len(scan_result.candidates) != 1:
        return IssueMetadata(
            present=False,
            manual_review=["issueplan-scanner:unresolved-candidate-set"],
            raw={
                "_scanner_findings": [finding.value for finding in scan_result.findings],
                "_scanner_evidence": list(scan_result.evidence),
            },
        )

    block = scan_result.candidates[0].parsed
    if block is None:
        return IssueMetadata(
            present=False,
            manual_review=["issueplan-scanner:metadata-malformed"],
            raw={
                "_scanner_findings": [finding.value for finding in scan_result.findings],
                "_scanner_evidence": list(scan_result.evidence),
            },
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
