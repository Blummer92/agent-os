from __future__ import annotations

from pathlib import Path

from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    Status,
    strongest_status,
)

from .issue_metadata import load_issue_form_fields, parse_issue_form_body
from .label_map import expected_labels, load_label_map

_REQUIRED_FIELDS = {"phase", "epic", "owner", "status", "type", "source-of-truth", "external-write"}


def evaluate_issue_labels(
    issue_body: str,
    existing_labels: list[str],
    issue_form_path: str | Path,
    label_map_path: str | Path,
) -> AcceptanceReport:
    label_map = load_label_map(label_map_path)
    form_fields = load_issue_form_fields(issue_form_path)
    metadata = parse_issue_form_body(issue_body, form_fields)
    expected, unknown_values = expected_labels(metadata, label_map)
    existing = set(existing_labels)
    missing = sorted(expected - existing)
    present = sorted(expected & existing)
    extra = sorted(existing - expected)
    manual_review = _manual_review_items(metadata, unknown_values)
    checks = [
        _check_write_boundary(label_map.rules),
        _check_governance_boundary(),
        _check_metadata(metadata),
        _check_unknown_values(unknown_values),
        _check_label_comparison(missing, present, extra),
        _check_manual_review(manual_review),
    ]
    overall = strongest_status(checks)
    return AcceptanceReport(
        linked_issue=None,
        overall_status=overall,
        checks=checks,
        manual_review_items=manual_review,
        evidence=[
            "report model: scripts.agent_os_issue_acceptance.models.AcceptanceReport",
            f"expected labels: {', '.join(sorted(expected)) or 'none'}",
            f"present expected labels: {', '.join(present) or 'none'}",
            f"missing expected labels: {', '.join(missing) or 'none'}",
            f"extra existing labels: {', '.join(extra) or 'none'}",
        ],
        blockers=[] if overall != Status.FAIL else ["Label checker input contract is invalid."],
        remaining_risks=[
            "Report-only label findings do not apply, remove, replace, or approve labels.",
            "Label findings do not authorize merge, readiness, approval, or source-of-truth changes.",
        ],
    )


def _check_write_boundary(rules: dict) -> CheckResult:
    unsafe = []
    if rules.get("apply_labels") is not False:
        unsafe.append("apply_labels must be false")
    if rules.get("remove_labels") is not False:
        unsafe.append("remove_labels must be false")
    if rules.get("replace_labels") is not False:
        unsafe.append("replace_labels must be false")
    if rules.get("additive_only") is not True:
        unsafe.append("additive_only must be true")
    if unsafe:
        return CheckResult("label write boundary", Status.FAIL, "unsafe label-map rules", unsafe)
    return CheckResult("label write boundary", Status.PASS, "label map is report-only and additive-safe")


def _check_governance_boundary() -> CheckResult:
    return CheckResult(
        "label governance boundary",
        Status.PASS,
        "label findings are acceptance evidence only and do not imply approval or readiness",
        [
            "IA1 outcome rules still govern merge, readiness, approval, and source-of-truth decisions",
            "L5 additive label behavior remains a separate follow-up decision",
        ],
    )


def _check_metadata(metadata: dict[str, list[str]]) -> CheckResult:
    missing = sorted(_REQUIRED_FIELDS - set(metadata))
    if missing:
        return CheckResult("issue metadata", Status.MANUAL_REVIEW, "required issue-form fields missing", missing)
    return CheckResult("issue metadata", Status.PASS, "required issue-form fields are present")


def _check_unknown_values(unknown_values: list[str]) -> CheckResult:
    if unknown_values:
        return CheckResult("label map values", Status.MANUAL_REVIEW, "unmapped issue-form values found", unknown_values)
    return CheckResult("label map values", Status.PASS, "all parsed values are mapped")


def _check_label_comparison(missing: list[str], present: list[str], extra: list[str]) -> CheckResult:
    evidence = [
        f"present={', '.join(present) or 'none'}",
        f"missing={', '.join(missing) or 'none'}",
        f"extra={', '.join(extra) or 'none'}",
    ]
    if missing:
        return CheckResult("expected labels", Status.WARN, "expected labels are missing", evidence)
    return CheckResult("expected labels", Status.PASS, "expected labels are present", evidence)


def _check_manual_review(items: list[str]) -> CheckResult:
    if items:
        return CheckResult("label manual review", Status.MANUAL_REVIEW, "label metadata requires review", items)
    return CheckResult("label manual review", Status.PASS, "no label manual-review signals found")


def _manual_review_items(metadata: dict[str, list[str]], unknown_values: list[str]) -> list[str]:
    items: list[str] = []
    for field, values in metadata.items():
        if "needs-decision" in values:
            items.append(f"{field} includes needs-decision")
    if "external-write-requested" in metadata.get("external-write", []):
        items.append("external-write field requests review before any automation")
    for value in unknown_values:
        items.append(f"unmapped value requires review: {value}")
    return items
