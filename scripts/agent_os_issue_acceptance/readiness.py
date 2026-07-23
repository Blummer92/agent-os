from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .issueplan_scanner import ScanFinding
from .models import AcceptanceReport, CheckResult, IssueMetadata, Status, strongest_status
from .parse_issue import project_issue_metadata, scan_issue_metadata
from .path_contract import (
    DeclaredPathError,
    declared_path_matches,
    normalize_declared_path,
    normalize_declared_pattern,
)


class ReadinessOutcome(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True)
class ReadinessResult:
    outcome: ReadinessOutcome
    report: AcceptanceReport


_TIER_REQUIRED_SECTIONS = {
    0: ("objective", "owner", "allowed", "validation", "completion"),
    1: (
        "objective",
        "value",
        "owner",
        "scope",
        "non-goals",
        "allowed",
        "validation",
        "documentation",
        "dependencies",
        "acceptance criteria",
        "definition of done",
    ),
    2: (
        "objective",
        "value",
        "owner",
        "scope",
        "non-goals",
        "allowed",
        "validation",
        "documentation",
        "dependencies",
        "acceptance criteria",
        "definition of done",
        "authorization",
        "source of truth",
        "external",
        "rollback",
        "approval",
        "stop conditions",
        "compatibility",
    ),
}

_FIELD_ALIASES = {
    "objective": ("objective", "objective and value"),
    "value": ("value", "objective and value"),
    "owner": ("owner", "owner routing", "owner and source of truth", "primary owner"),
    "scope": ("scope", "scope and non-goals"),
    "non-goals": ("non-goals", "scope and non-goals"),
    "allowed": (
        "allowed files",
        "allowed files or areas",
        "allowed files, areas, or governed surfaces",
        "allowed and protected areas",
    ),
    "validation": (
        "validation",
        "required tests or validation",
        "required tests, validation, and documentation",
        "validation and documentation",
    ),
    "documentation": (
        "documentation",
        "required docs updates",
        "required tests, validation, and documentation",
        "validation and documentation",
    ),
    "dependencies": ("dependencies", "dependencies and blockers", "dependencies / blockers"),
    "acceptance criteria": ("acceptance criteria", "acceptance criteria and definition of done"),
    "definition of done": ("definition of done", "acceptance criteria and definition of done"),
    "completion": ("completion", "completion criterion", "definition of done", "acceptance criteria and definition of done"),
    "authorization": ("authorization", "tier 2 controls, when applicable"),
    "source of truth": ("source of truth", "owner and source of truth", "tier 2 controls, when applicable"),
    "external": ("external write boundary", "external write surface", "tier 2 controls, when applicable"),
    "rollback": ("rollback", "tier 2 controls, when applicable"),
    "approval": ("approval requirements", "human approval", "tier 2 controls, when applicable"),
    "stop conditions": ("stop conditions", "tier 2 controls, when applicable"),
    "compatibility": ("migration or compatibility planning", "compatibility", "tier 2 controls, when applicable"),
}

_FENCED_RE = re.compile(r"```.*?```", re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")

_NO_RESPONSE = "_No response_"
_KNOWN_DOCUMENTATION_IMPACT_VALUES = {"docs-required", "docs-not-required", "docs-needs-decision"}
_DOC_HEADING_FIELD_MAP = {
    "documentation impact": "documentation_impact",
    "required documentation paths or bounded areas": "required_docs",
    "expected documentation change": "documentation_expected_change",
    "documentation exemption reason": "documentation_exemption_reason",
}
_PRIOR_SCOPE_HEADING = "prior scope, duplicate, and supersession review"


@dataclass(frozen=True)
class _FieldResolution:
    status: str  # "missing" | "ok" | "conflict" | "malformed"
    value: str | None = None
    yaml_present: bool = False
    body_present: bool = False
    malformed_source: str | None = None
    malformed_type: str | None = None


@dataclass(frozen=True)
class _ListFieldResolution:
    status: str  # "missing" | "ok" | "conflict"
    values: list[str]
    yaml_count: int
    body_count: int


def evaluate_issue_readiness(
    issue_body: str,
    *,
    dependency_blocked: bool = False,
    validation_pending: bool = False,
) -> ReadinessResult:
    """Evaluate one issue locally without network calls or metadata writes."""
    body = issue_body or ""
    scan_result = scan_issue_metadata(body)
    metadata = project_issue_metadata(scan_result)
    sections = _markdown_sections(body)
    tier = _parse_tier(body, metadata.raw.get("tier") if metadata.present else None)

    checks: list[CheckResult] = []
    blockers: list[str] = []
    manual_review_items: list[str] = []

    scanner_review_items = [
        item for item in metadata.manual_review if item.startswith("issueplan-scanner:")
    ]
    declared_review_items = [
        item for item in metadata.manual_review if not item.startswith("issueplan-scanner:")
    ]
    if scanner_review_items:
        checks.append(
            CheckResult(
                "issue metadata",
                Status.MANUAL_REVIEW,
                "Issue metadata scanner requires human review.",
                scanner_review_items,
            )
        )
        manual_review_items.extend(scanner_review_items)

    if tier is None:
        checks.append(CheckResult("issue tier", Status.MANUAL_REVIEW, "Issue tier is missing or invalid."))
        manual_review_items.append("Choose Tier 0, Tier 1, or Tier 2.")
    else:
        checks.append(CheckResult("issue tier", Status.PASS, f"Detected Tier {tier}."))
        missing = [name for name in _TIER_REQUIRED_SECTIONS[tier] if not _contains_field(sections, name)]
        if missing:
            checks.append(
                CheckResult(
                    "required issue fields",
                    Status.FAIL,
                    "Required fields are missing for the selected tier.",
                    [f"missing={name}" for name in missing],
                )
            )
            blockers.extend(f"Missing required field: {name}." for name in missing)
        else:
            checks.append(CheckResult("required issue fields", Status.PASS, "Required tier fields are present."))

    source_check = _check_source_of_truth_evidence(sections, metadata)
    if source_check is not None:
        checks.append(source_check)
        if source_check.status == Status.MANUAL_REVIEW:
            manual_review_items.append("Resolve conflicting source-of-truth evidence.")

    path_checks, path_manual_review_items = _check_declared_forbidden_paths(metadata)
    checks.extend(path_checks)
    manual_review_items.extend(path_manual_review_items)
    blockers.extend(check.message for check in path_checks if check.status == Status.FAIL)

    documentation_check = _evaluate_documentation_impact(metadata, body)
    checks.append(documentation_check)
    if documentation_check.status == Status.FAIL:
        blockers.append(documentation_check.message)
    elif documentation_check.status == Status.MANUAL_REVIEW:
        manual_review_items.append(documentation_check.message)

    prior_scope_check = _check_prior_scope_review(sections)
    checks.append(prior_scope_check)
    if prior_scope_check.status == Status.MANUAL_REVIEW:
        manual_review_items.append(
            "Provide visible prior-scope, duplicate, and supersession review evidence."
        )

    if declared_review_items:
        checks.append(
            CheckResult(
                "declared decisions",
                Status.MANUAL_REVIEW,
                "The issue declares items requiring human judgment.",
                declared_review_items,
            )
        )
        manual_review_items.extend(declared_review_items)

    if _contains_needs_decision(body):
        checks.append(CheckResult("unresolved decisions", Status.MANUAL_REVIEW, "The issue contains an unresolved decision value."))
        manual_review_items.append("Resolve all needs-decision fields.")

    if dependency_blocked or _declares_blocked_dependency(body):
        checks.append(CheckResult("dependencies", Status.FAIL, "A required dependency is blocked."))
        blockers.append("A required dependency is blocked.")

    if validation_pending:
        checks.append(CheckResult("required validation", Status.FAIL, "Required validation is pending."))
        blockers.append("Required validation is pending.")

    scanner_evidence = [
        f"issueplan_adoption_class={scan_result.adoption_class.value}",
        f"issueplan_candidate_count={len(scan_result.candidates)}",
        *(f"issueplan_scan_finding={finding.value}" for finding in scan_result.findings),
    ]
    return _build_result(checks, manual_review_items, blockers, scanner_evidence)


def evaluate_issue_readiness_with_labels(
    issue_body: str,
    label_report: AcceptanceReport,
    *,
    dependency_blocked: bool = False,
    validation_pending: bool = False,
) -> ReadinessResult:
    """Combine readiness with an existing report-only label evidence report."""
    base = evaluate_issue_readiness(
        issue_body,
        dependency_blocked=dependency_blocked,
        validation_pending=validation_pending,
    )
    return _build_result(
        [*base.report.checks, *label_report.checks],
        [*base.report.manual_review_items, *label_report.manual_review_items],
        [*base.report.blockers, *label_report.blockers],
        [*base.report.evidence, "label_evidence_consumed=true", *label_report.evidence],
        [*base.report.remaining_risks, *label_report.remaining_risks],
    )


def _build_result(
    checks: list[CheckResult],
    manual_review_items: list[str],
    blockers: list[str],
    extra_evidence: list[str],
    remaining_risks: list[str] | None = None,
) -> ReadinessResult:
    overall = strongest_status(checks)
    outcome = _map_outcome(overall)
    report = AcceptanceReport(
        linked_issue=None,
        overall_status=overall,
        checks=checks,
        manual_review_items=_dedupe(manual_review_items),
        blockers=_dedupe(blockers),
        evidence=[f"readiness_outcome={outcome.value}", *_dedupe(extra_evidence)],
        remaining_risks=_dedupe(
            remaining_risks
            or ["A ready result is evidence only and does not authorize implementation or merge."]
        ),
    )
    return ReadinessResult(outcome=outcome, report=report)


def _check_source_of_truth_evidence(
    sections: dict[str, str], metadata: IssueMetadata
) -> CheckResult | None:
    values: list[str] = []
    if metadata.source_of_truth:
        values.append(str(metadata.source_of_truth))
    for heading, content in sections.items():
        if heading == "source of truth" and content:
            values.append(content.splitlines()[0].strip())
        elif heading in {"owner and source of truth", "tier 2 controls, when applicable"}:
            match = re.search(
                r"(?im)^\s*(?:[-*]\s*)?source of truth\s*:\s*(.+?)\s*$",
                content,
            )
            if match:
                values.append(match.group(1).strip())

    normalized = {_normalize_source_value(value) for value in values if value.strip()}
    if not normalized:
        return None
    evidence = [f"observed={value}" for value in sorted(normalized)]
    if len(normalized) > 1:
        return CheckResult(
            "source-of-truth evidence",
            Status.MANUAL_REVIEW,
            "Conflicting source-of-truth evidence requires a decision.",
            evidence,
        )
    return CheckResult(
        "source-of-truth evidence",
        Status.PASS,
        "Source-of-truth evidence is consistent.",
        evidence,
    )


def _check_prior_scope_review(sections: dict[str, str]) -> CheckResult:
    """Report-only prior-scope, duplicate, and supersession review check.

    Passes only when visible text exists under the canonical
    ``Prior scope, duplicate, and supersession review`` heading. Quoted, fenced,
    and HTML-commented content is already stripped by ``_markdown_sections``, so
    those plus blank, ``_No response_``, or absent evidence fail closed to
    ``MANUAL_REVIEW`` (overall ``needs-decision``), never ``blocked``. Required
    for every tier. The check never parses or validates live links; substantive
    adequacy remains human review.
    """
    content = sections.get(_PRIOR_SCOPE_HEADING, "").strip()
    if content and content != _NO_RESPONSE:
        return CheckResult(
            "prior scope review",
            Status.PASS,
            "Prior-scope, duplicate, and supersession review evidence is present.",
            ["field=prior_scope_review; code=evidence-present"],
        )
    return CheckResult(
        "prior scope review",
        Status.MANUAL_REVIEW,
        "Prior-scope, duplicate, and supersession review evidence is missing or not visible.",
        ["field=prior_scope_review; code=prior-scope-review-missing"],
    )


def _check_declared_forbidden_paths(
    metadata: IssueMetadata,
) -> tuple[list[CheckResult], list[str]]:
    if not metadata.present:
        return [], []

    syntax_evidence: list[str] = []
    valid_paths: list[str] = []
    valid_patterns: list[str] = []

    for value in metadata.required_files:
        try:
            valid_paths.append(normalize_declared_path(value))
        except DeclaredPathError as error:
            syntax_evidence.append(_path_syntax_evidence("required_files", value, error.code))

    for value in metadata.forbidden_paths:
        try:
            valid_patterns.append(normalize_declared_pattern(value))
        except DeclaredPathError as error:
            syntax_evidence.append(_path_syntax_evidence("forbidden_paths", value, error.code))

    checks: list[CheckResult] = []
    manual_review_items: list[str] = []
    ordered_syntax_evidence = sorted(syntax_evidence)
    if ordered_syntax_evidence:
        checks.append(
            CheckResult(
                "declared path syntax",
                Status.MANUAL_REVIEW,
                "Malformed declared paths or patterns require human review.",
                ordered_syntax_evidence,
            )
        )
        manual_review_items.extend(
            f"Review malformed declared path evidence: {item}."
            for item in ordered_syntax_evidence
        )
    else:
        checks.append(
            CheckResult(
                "declared path syntax",
                Status.PASS,
                "Declared paths and patterns use the approved bounded syntax.",
            )
        )

    violations = sorted(
        {
            path
            for path in valid_paths
            for pattern in valid_patterns
            if declared_path_matches(path, pattern)
        }
    )
    if violations:
        checks.append(
            CheckResult(
                "declared forbidden paths",
                Status.FAIL,
                "Required files include declared forbidden paths.",
                violations,
            )
        )
    else:
        checks.append(
            CheckResult(
                "declared forbidden paths",
                Status.PASS,
                "Required files do not include declared forbidden paths.",
            )
        )

    return checks, manual_review_items


def _path_syntax_evidence(field: str, value: object, code: str) -> str:
    bounded_value = repr(value)
    if len(bounded_value) > 120:
        bounded_value = f"{bounded_value[:117]}..."
    return f"field={field}; value={bounded_value}; code={code}"


def _documentation_heading_occurrences(body: str) -> dict[str, list[str]]:
    """Group content by canonical documentation heading, preserving duplicates."""
    visible = _sanitize(body)
    occurrences: dict[str, list[str]] = {}
    current_field: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_field, current_lines
        if current_field is not None:
            occurrences.setdefault(current_field, []).append("\n".join(current_lines).strip())
        current_field = None
        current_lines = []

    for line in visible.splitlines():
        if line.lstrip().startswith(">"):
            continue
        match = _HEADING_RE.match(line.strip())
        if match:
            flush()
            current_field = _DOC_HEADING_FIELD_MAP.get(_normalize(match.group(1)))
            continue
        if current_field is not None:
            current_lines.append(line)
    flush()
    return occurrences


def _duplicate_heading_evidence(occurrences: dict[str, list[str]]) -> list[str]:
    return [
        f"field={field}; code=duplicate-heading; count={len(occurrences[field])}"
        for field in sorted(occurrences)
        if len(occurrences[field]) > 1
    ]


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None


def _live_lines(text: str | None) -> list[str]:
    if not text:
        return []
    return [
        stripped
        for stripped in (line.strip() for line in text.splitlines())
        if stripped and stripped != _NO_RESPONSE
    ]


def _free_text_value(text: str | None) -> str | None:
    """Treat an entire multiline block as one free-text value."""
    if not text:
        return None
    stripped = text.strip()
    if not stripped or stripped == _NO_RESPONSE:
        return None
    return stripped


def _malformed_type_name(value: object) -> str | None:
    """Return the YAML runtime type name when a value is present but not a string."""
    if value is None or isinstance(value, str):
        return None
    return type(value).__name__


def _resolve_scalar_field(
    yaml_value: object,
    body_text: str | None,
    *,
    collapse_whitespace: bool,
    allow_multiline: bool,
) -> _FieldResolution:
    malformed_type = _malformed_type_name(yaml_value)
    if malformed_type is not None:
        return _FieldResolution("malformed", malformed_source="yaml", malformed_type=malformed_type)
    yaml_text = yaml_value if isinstance(yaml_value, str) else None

    if allow_multiline:
        yaml_resolved = _free_text_value(yaml_text)
        body_resolved = _free_text_value(body_text)
    else:
        yaml_values = _live_lines(yaml_text)
        body_values = _live_lines(body_text)
        if len(yaml_values) > 1 or len(body_values) > 1:
            return _FieldResolution(
                "conflict", yaml_present=bool(yaml_values), body_present=bool(body_values)
            )
        yaml_resolved = yaml_values[0] if yaml_values else None
        body_resolved = body_values[0] if body_values else None

    yaml_present = yaml_resolved is not None
    body_present = body_resolved is not None

    if yaml_present and body_present:
        left, right = yaml_resolved, body_resolved
        if collapse_whitespace:
            left = re.sub(r"\s+", " ", left)
            right = re.sub(r"\s+", " ", right)
        if left == right:
            return _FieldResolution("ok", yaml_resolved, yaml_present=True, body_present=True)
        return _FieldResolution("conflict", yaml_present=True, body_present=True)
    if yaml_present:
        return _FieldResolution("ok", yaml_resolved, yaml_present=True, body_present=False)
    if body_present:
        return _FieldResolution("ok", body_resolved, yaml_present=False, body_present=True)
    return _FieldResolution("missing")


def _resolve_required_docs(yaml_values: list[str], body_text: str | None) -> _ListFieldResolution:
    body_values = _live_lines(body_text)
    yaml_set = sorted({value.strip() for value in yaml_values if value.strip()})
    body_set = sorted({value.strip() for value in body_values if value.strip()})

    if yaml_set and body_set:
        if yaml_set == body_set:
            return _ListFieldResolution("ok", yaml_set, len(yaml_set), len(body_set))
        return _ListFieldResolution("conflict", [], len(yaml_set), len(body_set))
    if yaml_set:
        return _ListFieldResolution("ok", yaml_set, len(yaml_set), 0)
    if body_set:
        return _ListFieldResolution("ok", body_set, 0, len(body_set))
    return _ListFieldResolution("missing", [], 0, 0)


def _malformed_evidence(field: str, source: str | None, type_name: str | None) -> str:
    return f"field={field}; code=documentation-source-malformed; source={source}; type={type_name}"


def _conflict_evidence(field: str, code: str, resolution: _FieldResolution) -> str:
    yaml_present = "true" if resolution.yaml_present else "false"
    body_present = "true" if resolution.body_present else "false"
    return f"field={field}; code={code}; yaml_present={yaml_present}; body_present={body_present}"


def _required_docs_conflict_evidence(resolution: _ListFieldResolution) -> str:
    return (
        "field=required_docs; code=documentation-path-conflict; "
        f"yaml_count={resolution.yaml_count}; body_count={resolution.body_count}"
    )


def _evaluate_documentation_impact(metadata: IssueMetadata, body: str) -> CheckResult:
    occurrences = _documentation_heading_occurrences(body)
    duplicate_evidence = _duplicate_heading_evidence(occurrences)
    if duplicate_evidence:
        return CheckResult(
            "documentation impact",
            Status.MANUAL_REVIEW,
            "Duplicate canonical documentation headings require human review.",
            duplicate_evidence,
        )

    impact = _resolve_scalar_field(
        metadata.documentation_impact,
        _first(occurrences.get("documentation_impact")),
        collapse_whitespace=False,
        allow_multiline=False,
    )
    if impact.status == "malformed":
        return CheckResult(
            "documentation impact",
            Status.MANUAL_REVIEW,
            "Documentation-impact YAML value has an unsupported type.",
            [_malformed_evidence("documentation_impact", impact.malformed_source, impact.malformed_type)],
        )
    if impact.status == "conflict":
        return CheckResult(
            "documentation impact",
            Status.MANUAL_REVIEW,
            "Conflicting documentation-impact evidence requires human review.",
            [_conflict_evidence("documentation_impact", "documentation-source-conflict", impact)],
        )
    if impact.status == "missing":
        return CheckResult(
            "documentation impact",
            Status.MANUAL_REVIEW,
            "Documentation-impact evidence is missing.",
            ["field=documentation_impact; code=legacy-metadata-missing"],
        )

    impact_value = impact.value or ""
    if impact_value not in _KNOWN_DOCUMENTATION_IMPACT_VALUES:
        return CheckResult(
            "documentation impact",
            Status.MANUAL_REVIEW,
            "Documentation-impact value is not recognized.",
            ["field=documentation_impact; code=documentation-impact-unknown"],
        )
    if impact_value == "docs-needs-decision":
        return CheckResult(
            "documentation impact",
            Status.MANUAL_REVIEW,
            "Documentation impact explicitly needs a human decision.",
            ["field=documentation_impact; code=documentation-needs-decision"],
        )

    docs = _resolve_required_docs(
        metadata.required_docs, _first(occurrences.get("required_docs"))
    )
    expected = _resolve_scalar_field(
        metadata.documentation_expected_change,
        _first(occurrences.get("documentation_expected_change")),
        collapse_whitespace=True,
        allow_multiline=True,
    )
    exemption = _resolve_scalar_field(
        metadata.documentation_exemption_reason,
        _first(occurrences.get("documentation_exemption_reason")),
        collapse_whitespace=True,
        allow_multiline=True,
    )

    if impact_value == "docs-required":
        return _evaluate_docs_required(docs, expected, exemption)
    return _evaluate_docs_not_required(docs, expected, exemption)


def _evaluate_docs_required(
    docs: _ListFieldResolution,
    expected: _FieldResolution,
    exemption: _FieldResolution,
) -> CheckResult:
    evidence = ["impact=docs-required"]
    fail = False
    manual = False

    if docs.status == "missing":
        fail = True
        evidence.append("field=required_docs; code=documentation-path-missing")
    elif docs.status == "conflict":
        manual = True
        evidence.append(_required_docs_conflict_evidence(docs))
    else:
        malformed: list[str] = []
        valid_paths: list[str] = []
        for value in docs.values:
            try:
                valid_paths.append(normalize_declared_path(value))
            except DeclaredPathError as error:
                malformed.append(_path_syntax_evidence("required_docs", value, error.code))
        if malformed:
            manual = True
            evidence.extend(sorted(malformed))
        evidence.extend(f"evidence_path={path}" for path in sorted(valid_paths))

    if expected.status == "malformed":
        manual = True
        evidence.append(
            _malformed_evidence("documentation_expected_change", expected.malformed_source, expected.malformed_type)
        )
    elif expected.status == "missing":
        fail = True
        evidence.append("field=documentation_expected_change; code=documentation-expected-change-missing")
    elif expected.status == "conflict":
        manual = True
        evidence.append(
            _conflict_evidence("documentation_expected_change", "documentation-expected-change-conflict", expected)
        )
    else:
        evidence.append("expected_change_present=true")

    if exemption.status == "malformed":
        manual = True
        evidence.append(
            _malformed_evidence("documentation_exemption_reason", exemption.malformed_source, exemption.malformed_type)
        )
    elif exemption.status == "conflict":
        manual = True
        evidence.append(
            _conflict_evidence("documentation_exemption_reason", "documentation-exemption-conflict", exemption)
        )
    elif exemption.status == "ok":
        manual = True
        evidence.append("field=documentation_exemption_reason; code=documentation-exemption-conflict")

    if fail:
        return CheckResult(
            "documentation impact",
            Status.FAIL,
            "Documentation impact requires documentation, but required evidence is missing.",
            evidence,
        )
    if manual:
        return CheckResult(
            "documentation impact",
            Status.MANUAL_REVIEW,
            "Documentation impact requires human review of conflicting or malformed evidence.",
            evidence,
        )
    return CheckResult(
        "documentation impact",
        Status.PASS,
        "Documentation impact evidence is complete and consistent.",
        evidence,
    )


def _evaluate_docs_not_required(
    docs: _ListFieldResolution,
    expected: _FieldResolution,
    exemption: _FieldResolution,
) -> CheckResult:
    evidence = ["impact=docs-not-required"]
    manual = False

    if exemption.status == "malformed":
        manual = True
        evidence.append(
            _malformed_evidence("documentation_exemption_reason", exemption.malformed_source, exemption.malformed_type)
        )
    elif exemption.status == "missing":
        manual = True
        evidence.append("field=documentation_exemption_reason; code=documentation-exemption-missing")
    elif exemption.status == "conflict":
        manual = True
        evidence.append(
            _conflict_evidence("documentation_exemption_reason", "documentation-exemption-conflict", exemption)
        )
    else:
        evidence.append("exemption_reason_present=true")

    if docs.status == "conflict":
        manual = True
        evidence.append(_required_docs_conflict_evidence(docs))
    elif docs.status == "ok" and docs.values:
        manual = True
        evidence.append(_required_docs_conflict_evidence(docs))

    if expected.status == "malformed":
        manual = True
        evidence.append(
            _malformed_evidence("documentation_expected_change", expected.malformed_source, expected.malformed_type)
        )
    elif expected.status == "conflict":
        manual = True
        evidence.append(
            _conflict_evidence("documentation_expected_change", "documentation-expected-change-conflict", expected)
        )
    elif expected.status == "ok":
        manual = True
        evidence.append("field=documentation_expected_change; code=documentation-expected-change-conflict")

    if manual:
        return CheckResult(
            "documentation impact",
            Status.MANUAL_REVIEW,
            "Documentation impact requires human review of unexpected documentation evidence.",
            evidence,
        )
    return CheckResult(
        "documentation impact",
        Status.PASS,
        "Documentation impact evidence indicates no documentation change is required.",
        evidence,
    )


def _normalize_source_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _map_outcome(status: Status) -> ReadinessOutcome:
    if status == Status.FAIL:
        return ReadinessOutcome.BLOCKED
    if status == Status.MANUAL_REVIEW:
        return ReadinessOutcome.NEEDS_DECISION
    return ReadinessOutcome.READY


def _parse_tier(body: str, metadata_tier: object) -> int | None:
    values = [metadata_tier]
    visible = _sanitize(body)
    for pattern in (
        r"(?im)^\s*(?:issue\s+)?tier\s*[:|-]\s*(?:tier:)?\s*([012])\b",
        r"(?im)^\s*tier:([012])(?:-|\b)",
    ):
        match = re.search(pattern, visible)
        if match:
            values.append(match.group(1))
    for value in values:
        try:
            tier = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if tier in _TIER_REQUIRED_SECTIONS:
            return tier
    return None


def _markdown_sections(body: str) -> dict[str, str]:
    visible = _sanitize(body)
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in visible.splitlines():
        if line.lstrip().startswith(">"):
            continue
        match = _HEADING_RE.match(line.strip())
        if match:
            current = _normalize(match.group(1))
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _contains_field(sections: dict[str, str], name: str) -> bool:
    aliases = {_normalize(alias) for alias in _FIELD_ALIASES.get(name, (name,))}
    for heading, content in sections.items():
        if heading not in aliases:
            continue
        if not content or content == "_No response_":
            continue
        if heading == "tier 2 controls, when applicable" and name not in {
            "authorization",
            "source of truth",
            "external",
            "rollback",
            "approval",
            "stop conditions",
            "compatibility",
        }:
            continue
        if heading == "tier 2 controls, when applicable":
            return _contains_labeled_value(content, name)
        return True
    return False


def _contains_labeled_value(content: str, name: str) -> bool:
    labels = {
        "authorization": ("authorization",),
        "source of truth": ("source of truth", "canonical surface"),
        "external": ("external write", "external surface"),
        "rollback": ("rollback",),
        "approval": ("approval", "human approval"),
        "stop conditions": ("stop conditions",),
        "compatibility": ("compatibility", "migration"),
    }[name]
    return any(
        re.search(
            rf"(?im)^\s*(?:[-*]\s*)?{re.escape(label)}\s*:\s*\S.+$",
            content,
        )
        for label in labels
    )


def _contains_needs_decision(body: str) -> bool:
    visible = _sanitize(body)
    return bool(
        re.search(
            r"(?im)^\s*(?:[-*]\s*)?(?:(?:owner|source of truth|external write boundary|authorization|readiness candidate)\s*:\s*)?(?:status:)?needs[- ]decision\s*$",
            visible,
        )
    )


def _declares_blocked_dependency(body: str) -> bool:
    visible = _sanitize(body)
    return bool(re.search(r"(?im)^\s*(?:blocked by|blockers?)\s*:\s*(?!none\b|not applicable\b).+", visible))


def _sanitize(body: str) -> str:
    without_comments = _COMMENT_RE.sub("", body or "")
    return _FENCED_RE.sub("", without_comments)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())
