from __future__ import annotations

import re
from dataclasses import replace

from . import metadata_validation
from .checks import (
    banned_patterns,
    final_report_fields,
    forbidden_paths,
    issue_quality,
    linked_issue,
    required_docs,
    required_files,
    required_tests,
    validation_commands,
)
from .issueplan_scanner import ScanFinding
from .models import (
    AcceptanceInput,
    AcceptanceReport,
    CheckResult,
    LinkedIssueParseStatus,
    Status,
    strongest_status,
)
from .parse_issue import project_issue_metadata, scan_issue_metadata
from .parse_pr import parse_linked_issue_result


def _unavailable_evidence_check(name: str, input_name: str) -> CheckResult:
    return CheckResult(
        name,
        Status.MANUAL_REVIEW,
        f"{input_name} evidence was supplied but is empty; this check cannot be completed safely.",
        [f"input={input_name}; state=empty-supplied"],
    )


# Report-only registration (#3282). The issue-quality and metadata-validation
# checkers are implemented and tested but the acceptance policy never ran them.
# They are registered here as strictly informational evidence via
# AcceptanceReport.informational_checks, mirroring the reuse_readiness.py
# precedent. They never enter report.checks, overall_status, blockers,
# manual_review_items, remaining_risks, or exit_code_for().

# Tier -> issue-family mapping (#3282 precondition (a)). The issue template
# defines Tier 0 as "small safe maintenance", Tier 1 as "standard
# implementation", and Tier 2 as "governed or cross-system work". Tier 1 and
# Tier 2 map by direct name correspondence; Tier 0 maps to the lightest family
# contract (cleanup: goal + scope). The tier is read from the "Issue tier" body
# section, which the template keeps as body evidence rather than a label. When
# that section holds no canonical tier value, no family is guessed: only the
# family-independent checkers run, plus one note recording the skip.
_TIER_TO_ISSUE_FAMILY: dict[str, issue_quality.IssueFamily] = {
    "tier:0-small-maintenance": issue_quality.IssueFamily.CLEANUP,
    "tier:1-standard-implementation": issue_quality.IssueFamily.IMPLEMENTATION,
    "tier:2-governed-cross-system": issue_quality.IssueFamily.GOVERNANCE,
}

_ISSUE_QUALITY_PREFIX = "issue-quality: "

# Metadata field-extraction contract (#3282 precondition (b)): issue-form body
# section -> metadata_validation field. Only sections holding a real
# (non-empty, non-placeholder) value produce a check; absent or
# placeholder-only sections produce no check at all, so unfilled optional
# fields never emit manual-review noise on a report. Labels are intentionally
# not consumed: evaluate_acceptance receives only the issue body, and the
# issue template keeps tier, readiness, owner, source-of-truth, and
# external-write evidence in the body.
_METADATA_SECTION_FIELDS: dict[str, str] = {
    "issue tier": "issue_tier",
    "readiness candidate": "readiness_candidate",
    "documentation impact": "documentation_impact",
    "primary owner": "primary_owner",
    "source of truth": "source_route",
    "external write boundary": "external_write_boundary",
}

# Mirrors the placeholder set in checks/issue_quality.py (_PLACEHOLDER_RE) plus
# the issue-form "_No response_" marker: placeholder-only values carry no
# evidence and therefore produce no metadata check.
_METADATA_PLACEHOLDER_RE = re.compile(
    r"^(?:tbd|todo|_?no response_?|n/a\?|placeholder)[.!\s]*$", re.IGNORECASE
)


def _first_value_line(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _derive_issue_family(issue_body: str) -> issue_quality.IssueFamily | None:
    sections = issue_quality.parse_sections(issue_body)
    tier_value = _first_value_line(sections.get("issue tier", ""))
    return _TIER_TO_ISSUE_FAMILY.get(tier_value)


def _issue_quality_informational(issue_body: str) -> list[CheckResult]:
    family = _derive_issue_family(issue_body)
    if family is not None:
        results = issue_quality.check(issue_body, family)
    else:
        results = [
            issue_quality.check_parent_reference(issue_body),
            issue_quality.check_related_references(issue_body),
            issue_quality.check_blocker_quality(issue_body),
            CheckResult(
                "family",
                Status.MANUAL_REVIEW,
                "No canonical tier value in the Issue tier section; "
                "family-dependent checks were not run and no family was guessed.",
                ["tier=unknown-or-absent"],
            ),
        ]
    return [
        replace(check, name=f"{_ISSUE_QUALITY_PREFIX}{check.name}")
        for check in results
    ]


def _metadata_informational(issue_body: str) -> list[CheckResult]:
    sections = issue_quality.parse_sections(issue_body)
    results: list[CheckResult] = []
    for section, field in _METADATA_SECTION_FIELDS.items():
        value = _first_value_line(sections.get(section, ""))
        if not value or _METADATA_PLACEHOLDER_RE.fullmatch(value):
            continue
        results.append(
            metadata_validation.validate_metadata_evidence(field, value).to_check()
        )
    results.extend(_legacy_metadata_informational(issue_body))
    return results


def _legacy_metadata_informational(issue_body: str) -> list[CheckResult]:
    prefixes = metadata_validation.LEGACY_METADATA_PREFIXES
    seen: list[str] = []
    for line in issue_body.splitlines():
        for token in line.split():
            cleaned = token.strip("`\"'.,;:!?()[]{}*_~")
            if (
                any(cleaned.startswith(prefix) and len(cleaned) > len(prefix)
                    for prefix in prefixes)
                and cleaned not in seen
            ):
                seen.append(cleaned)
    return [
        metadata_validation.validate_metadata_evidence("legacy_metadata", token).to_check()
        for token in seen
    ]


def evaluate_acceptance(data: AcceptanceInput, pr_title: str = "") -> AcceptanceReport:
    """Run IA2 v1 checks against offline issue, PR, file-list, and diff inputs."""
    scan_result = scan_issue_metadata(data.issue_body)
    metadata = project_issue_metadata(scan_result)
    linked_issue_result = parse_linked_issue_result(data.pr_body, pr_title)

    changed_file_evidence_unavailable = data.changed_files_supplied and not data.changed_files
    diff_evidence_unavailable = data.diff_supplied and not data.diff_text.strip()

    checks: list[CheckResult] = [
        linked_issue.check(data.pr_body, pr_title, parse_result=linked_issue_result),
        final_report_fields.check(data.pr_body),
        (
            _unavailable_evidence_check("required files", "changed-files")
            if changed_file_evidence_unavailable
            else required_files.check(metadata, data.changed_files)
        ),
        (
            _unavailable_evidence_check("forbidden paths", "changed-files")
            if changed_file_evidence_unavailable
            else forbidden_paths.check(metadata, data.changed_files)
        ),
        (
            _unavailable_evidence_check("required docs", "changed-files")
            if changed_file_evidence_unavailable
            else required_docs.check(metadata, data.changed_files)
        ),
        required_tests.check(metadata, data.changed_files, data.pr_body),
        (
            _unavailable_evidence_check("banned patterns", "diff")
            if diff_evidence_unavailable
            else banned_patterns.check(metadata, data.diff_text)
        ),
        validation_commands.check(data.pr_body),
    ]

    manual_review_items = list(metadata.manual_review)
    if linked_issue_result.status == LinkedIssueParseStatus.MANUAL_REVIEW:
        manual_review_items.extend(
            f"Linked issue: {reason}" for reason in linked_issue_result.reasons
        )
    if not metadata.present:
        if ScanFinding.METADATA_MISSING in scan_result.findings:
            manual_review_items.append("Issue metadata block is missing.")
        else:
            manual_review_items.append(
                "Issue metadata scanner could not produce one safe compatibility projection."
            )
    if metadata.external_writes and metadata.external_writes != "none":
        manual_review_items.append(f"External writes declared: {metadata.external_writes}")

    overall = strongest_status(checks)
    if manual_review_items and overall not in {Status.FAIL, Status.MANUAL_REVIEW}:
        overall = Status.MANUAL_REVIEW

    evidence = [
        f"changed_files={len(data.changed_files)}",
        f"changed_files_supplied={str(data.changed_files_supplied).lower()}",
        f"diff_supplied={str(data.diff_supplied).lower()}",
        f"metadata_present={metadata.present}",
        f"linked_issue_status={linked_issue_result.status.value}",
        f"issueplan_adoption_class={scan_result.adoption_class.value}",
        f"issueplan_candidate_count={len(scan_result.candidates)}",
    ]
    evidence.extend(
        f"issueplan_scan_finding={finding.value}" for finding in scan_result.findings
    )
    evidence.extend(
        f"linked_issue_reason={reason}" for reason in linked_issue_result.reasons
    )
    blockers = [check.message for check in checks if check.status == Status.FAIL]
    risks = [
        check.message
        for check in checks
        if check.status in {Status.WARN, Status.MANUAL_REVIEW}
    ]

    # Report-only registration (#3282): the issue-quality and
    # metadata-validation checkers run here as informational evidence only.
    # overall_status, blockers, manual_review_items, remaining_risks, and the
    # workflow exit code are computed from report.checks above and are
    # provably unchanged by anything appended below.
    informational: list[CheckResult] = []
    informational.extend(_issue_quality_informational(data.issue_body))
    informational.extend(_metadata_informational(data.issue_body))

    return AcceptanceReport(
        linked_issue=(
            linked_issue_result.issue_number
            if linked_issue_result.status == LinkedIssueParseStatus.RESOLVED
            else None
        ),
        linked_issue_result=linked_issue_result,
        overall_status=overall,
        checks=checks,
        manual_review_items=manual_review_items,
        evidence=evidence,
        blockers=blockers,
        remaining_risks=risks,
        informational_checks=tuple(informational),
    )
