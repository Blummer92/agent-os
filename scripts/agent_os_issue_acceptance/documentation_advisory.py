from __future__ import annotations

import re
from dataclasses import replace

from .models import (
    AcceptanceReport,
    CheckResult,
    IssueMetadata,
    LinkedIssueParseResult,
)

_REQUIRED_DOCS_CHECK = "required docs"
_ADVISORY_RISK = (
    "Declared documentation ownership, semantic relevance, and sufficiency "
    "require human review."
)
_SAFE_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}\Z")


def attach_documentation_advisory(
    report: AcceptanceReport,
    metadata: IssueMetadata,
) -> AcceptanceReport:
    """Return a fresh report with bounded, advisory-only documentation evidence.

    This adapter never changes acceptance status, checks, blockers, manual-review
    items, linked-issue evidence, or exit behavior. It consumes only the canonical
    ``IssueMetadata`` projection and the existing ``required docs`` check.
    """

    cloned = _clone_report(report)
    if metadata.present and metadata.documentation_impact == "docs-not-required":
        return cloned

    advisory_evidence = [
        "documentation_advisory=present",
        f"declared_owner_agent={_owner_value(metadata.owner_agent)}",
        f"required_docs_count={len(metadata.required_docs)}",
        f"required_docs_coverage_status={_required_docs_status(report.checks)}",
        f"expected_change_present={_expected_change_present(metadata)}",
        "ownership_verification=human-review-required",
        "semantic_relevance_verification=human-review-required",
        "authorization=advisory-only-not-readiness-write-or-merge",
    ]

    return replace(
        cloned,
        evidence=_deduplicate([*cloned.evidence, *advisory_evidence]),
        remaining_risks=_deduplicate([*cloned.remaining_risks, _ADVISORY_RISK]),
    )


def _clone_report(report: AcceptanceReport) -> AcceptanceReport:
    linked_issue_result = _clone_linked_issue_result(report.linked_issue_result)
    return replace(
        report,
        checks=[_clone_check(check) for check in report.checks],
        linked_issue_result=linked_issue_result,
        manual_review_items=list(report.manual_review_items),
        evidence=list(report.evidence),
        blockers=list(report.blockers),
        remaining_risks=list(report.remaining_risks),
        informational_checks=tuple(_clone_check(check) for check in report.informational_checks),
    )


def _clone_check(check: CheckResult) -> CheckResult:
    return replace(check, evidence=list(check.evidence))


def _clone_linked_issue_result(
    result: LinkedIssueParseResult | None,
) -> LinkedIssueParseResult | None:
    if result is None:
        return None
    return replace(
        result,
        explicit_candidates=list(result.explicit_candidates),
        bare_references=list(result.bare_references),
        reasons=list(result.reasons),
    )


def _expected_change_present(metadata: IssueMetadata) -> str:
    value = metadata.documentation_expected_change
    return str(bool(value and value.strip())).lower()


def _owner_value(owner_agent: str | None) -> str:
    if owner_agent is None:
        return "missing"
    normalized = owner_agent.strip()
    if not normalized:
        return "missing"
    if _SAFE_OWNER.fullmatch(normalized) is None:
        return "invalid"
    return normalized


def _required_docs_status(checks: list[CheckResult]) -> str:
    matches = [check for check in checks if check.name == _REQUIRED_DOCS_CHECK]
    if len(matches) != 1:
        return "missing"
    status = matches[0].status.value
    if status not in {"pass", "warn", "fail", "manual-review"}:
        return "missing"
    return status


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
