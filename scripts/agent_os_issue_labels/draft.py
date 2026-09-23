from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from scripts.agent_os_issue_acceptance.models import (
    AcceptanceReport,
    CheckResult,
    Status,
    strongest_status,
)
from scripts.agent_os_issue_acceptance.report import render_report

from .checker import evaluate_issue_labels
from .issue_metadata import (
    IssueFormField,
    IssueFormSchema,
    canonical_field_id,
    load_issue_form_schema,
    metadata_contract,
    parse_issue_form_body,
)
from .label_map import expected_labels, load_label_map
from .report import report_to_dict


@dataclass(frozen=True)
class IssueDraftInput:
    title: str
    fields: tuple[tuple[str, tuple[str, ...]], ...]
    input_issues: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "IssueDraftInput":
        issues: list[str] = []
        unknown_top_level = sorted(str(key) for key in payload if key not in {"title", "fields"})
        for key in unknown_top_level:
            issues.append(f"unknown top-level input key: {key}")

        raw_title = payload.get("title", "")
        if isinstance(raw_title, str):
            title = _normalize_text(raw_title)
        else:
            title = ""
            issues.append("title must be a string")

        raw_fields = payload.get("fields", {})
        if not isinstance(raw_fields, Mapping):
            issues.append("fields must be a mapping")
            raw_fields = {}

        fields: list[tuple[str, tuple[str, ...]]] = []
        for raw_key in sorted(raw_fields, key=lambda value: str(value)):
            if not isinstance(raw_key, str):
                issues.append(f"field key must be a string: {raw_key!r}")
                continue
            values = _normalize_input_values(raw_key, raw_fields[raw_key], issues)
            fields.append((raw_key, values))

        return cls(
            title=title,
            fields=tuple(fields),
            input_issues=tuple(sorted(set(issues))),
        )

    def field_mapping(self) -> dict[str, tuple[str, ...]]:
        return dict(self.fields)


@dataclass(frozen=True)
class IssueDraftResult:
    title: str
    body: str
    metadata_contract: str
    proposed_labels: tuple[str, ...]
    form_default_labels: tuple[str, ...]
    form_default_assignees: tuple[str, ...]
    form_issue_type: str | None
    form_projects: tuple[str, ...]
    report: AcceptanceReport
    manual_review_reasons: tuple[str, ...]
    mutation_performed: bool = False
    write_authorized: bool = False


@dataclass(frozen=True)
class _DraftValidation:
    schema_reasons: tuple[str, ...]
    input_reasons: tuple[str, ...]
    required_reasons: tuple[str, ...]
    option_reasons: tuple[str, ...]

    @property
    def all_reasons(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                set(
                    self.schema_reasons
                    + self.input_reasons
                    + self.required_reasons
                    + self.option_reasons
                )
            )
        )


def build_issue_draft(
    payload: Mapping[str, object] | IssueDraftInput,
    issue_form_path: str | Path,
    label_map_path: str | Path,
) -> IssueDraftResult:
    draft_input = (
        payload if isinstance(payload, IssueDraftInput) else IssueDraftInput.from_mapping(payload)
    )
    schema = load_issue_form_schema(issue_form_path)
    selected, validation = _select_field_values(schema, draft_input)
    body = _render_body(schema, selected)
    title, title_reason = _render_title(schema.title_prefix, draft_input.title)

    fields = {field.canonical_id: field.label for field in schema.fields}
    metadata = parse_issue_form_body(body, fields)
    label_map = load_label_map(label_map_path)
    proposed, _ = expected_labels(metadata, label_map)
    proposed_labels = tuple(sorted(proposed))

    label_report = evaluate_issue_labels(
        issue_body=body,
        existing_labels=list(proposed_labels),
        issue_form_path=issue_form_path,
        label_map_path=label_map_path,
    )

    input_reasons = list(validation.input_reasons)
    if title_reason:
        input_reasons.append(title_reason)
    validation = _DraftValidation(
        schema_reasons=validation.schema_reasons,
        input_reasons=tuple(sorted(set(input_reasons))),
        required_reasons=validation.required_reasons,
        option_reasons=validation.option_reasons,
    )
    checks = _draft_checks(validation) + list(label_report.checks)
    manual_review = tuple(
        sorted(set(validation.all_reasons + tuple(label_report.manual_review_items)))
    )
    overall = strongest_status(checks)
    report = AcceptanceReport(
        linked_issue=None,
        overall_status=overall,
        checks=checks,
        manual_review_items=list(manual_review),
        evidence=[
            f"issue form: {Path(issue_form_path).as_posix()}",
            f"metadata contract: {metadata_contract(metadata)}",
            f"rendered fields: {len(schema.fields)}",
            f"proposed labels: {', '.join(proposed_labels) or 'none'}",
            f"form default labels: {', '.join(schema.default_labels) or 'none'}",
            *label_report.evidence,
        ],
        blockers=list(label_report.blockers),
        remaining_risks=list(
            dict.fromkeys(
                [
                    "Preview evidence does not authorize issue creation or any external write.",
                    "GitHub issue-form syntax may change and must remain behind the schema adapter.",
                    *label_report.remaining_risks,
                ]
            )
        ),
    )

    return IssueDraftResult(
        title=title,
        body=body,
        metadata_contract=metadata_contract(metadata),
        proposed_labels=proposed_labels,
        form_default_labels=schema.default_labels,
        form_default_assignees=schema.default_assignees,
        form_issue_type=schema.issue_type,
        form_projects=schema.projects,
        report=report,
        manual_review_reasons=manual_review,
    )


def draft_result_to_dict(result: IssueDraftResult) -> dict[str, object]:
    return {
        "title": result.title,
        "body": result.body,
        "metadata_contract": result.metadata_contract,
        "proposed_labels": list(result.proposed_labels),
        "form_metadata": {
            "default_labels": list(result.form_default_labels),
            "default_assignees": list(result.form_default_assignees),
            "issue_type": result.form_issue_type,
            "projects": list(result.form_projects),
        },
        "manual_review_reasons": list(result.manual_review_reasons),
        "mutation_performed": result.mutation_performed,
        "write_authorized": result.write_authorized,
        "report": report_to_dict(result.report),
    }


def render_draft_preview(result: IssueDraftResult) -> str:
    lines = [
        "Agent OS Issue Draft Preview",
        f"Title: {result.title}",
        f"Metadata contract: {result.metadata_contract}",
        f"Overall result: {result.report.overall_status.value}",
        f"Mutation performed: {_yes_no(result.mutation_performed)}",
        f"Write authorized: {_yes_no(result.write_authorized)}",
        "Proposed labels:",
        *_bullets(result.proposed_labels),
        "Form default labels (evidence only):",
        *_bullets(result.form_default_labels),
        "Manual review reasons:",
        *_bullets(result.manual_review_reasons),
        "Body:",
        result.body.rstrip("\n"),
        "Acceptance evidence:",
        render_report(result.report).rstrip("\n"),
    ]
    return "\n".join(lines) + "\n"


def _select_field_values(
    schema: IssueFormSchema, draft_input: IssueDraftInput
) -> tuple[dict[str, tuple[str, ...]], _DraftValidation]:
    input_fields = draft_input.field_mapping()
    schema_by_canonical = {field.canonical_id: field for field in schema.fields}
    candidates: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    input_reasons = list(draft_input.input_issues)

    for input_key, values in input_fields.items():
        canonical_id = canonical_field_id(input_key)
        if canonical_id not in schema_by_canonical:
            input_reasons.append(f"unknown input field: {input_key}")
            continue
        candidates.setdefault(canonical_id, []).append((input_key, values))

    selected: dict[str, tuple[str, ...]] = {}
    required_reasons: list[str] = []
    option_reasons: list[str] = []

    for field in schema.fields:
        field_candidates = candidates.get(field.canonical_id, [])
        if len(field_candidates) > 1:
            source_names = ", ".join(sorted(key for key, _ in field_candidates))
            input_reasons.append(
                f"multiple input fields map to {field.canonical_id}: {source_names}"
            )
        values = _preferred_values(field, field_candidates)
        selected[field.canonical_id] = values

        if field.required and not values:
            required_reasons.append(f"required field is missing: {field.field_id}")
        if field.control_type == "dropdown":
            if len(values) > 1:
                option_reasons.append(
                    f"dropdown field {field.field_id} must contain exactly one value"
                )
            for value in values:
                if field.options and value not in field.options:
                    option_reasons.append(
                        f"field {field.field_id} contains unsupported option: {value}"
                    )
        elif field.control_type == "checkboxes":
            selected_values = set(values)
            for value in values:
                if value not in field.options:
                    option_reasons.append(
                        f"field {field.field_id} contains unsupported checkbox option: {value}"
                    )
            for required_option in field.required_options:
                if required_option not in selected_values:
                    required_reasons.append(
                        f"required checkbox is not selected for {field.field_id}: {required_option}"
                    )
        elif len(values) > 1:
            input_reasons.append(
                f"field {field.field_id} contains multiple structured values"
            )

    validation = _DraftValidation(
        schema_reasons=tuple(schema.unsupported_controls),
        input_reasons=tuple(sorted(set(input_reasons))),
        required_reasons=tuple(sorted(set(required_reasons))),
        option_reasons=tuple(sorted(set(option_reasons))),
    )
    return selected, validation


def _preferred_values(
    field: IssueFormField,
    candidates: list[tuple[str, tuple[str, ...]]],
) -> tuple[str, ...]:
    if not candidates:
        return ()
    ordered = sorted(
        candidates,
        key=lambda item: (
            item[0] != field.field_id,
            item[0] != field.canonical_id,
            item[0],
        ),
    )
    return ordered[0][1]


def _render_title(prefix: str, title: str) -> tuple[str, str | None]:
    clean_title = title.strip()
    if not clean_title:
        return prefix.rstrip(), "title is required"
    if prefix and clean_title.startswith(prefix):
        return clean_title, None
    return f"{prefix}{clean_title}", None


def _render_body(
    schema: IssueFormSchema, selected: dict[str, tuple[str, ...]]
) -> str:
    sections = []
    for field in schema.fields:
        values = selected.get(field.canonical_id, ())
        sections.append(f"### {field.label}\n\n{_render_field(field, values)}")
    return "\n\n".join(sections) + "\n"


def _render_field(field: IssueFormField, values: tuple[str, ...]) -> str:
    if field.control_type == "checkboxes":
        if not field.options:
            return "_No response_"
        selected = set(values)
        return "\n".join(
            f"- [{'x' if option in selected else ' '}] {option}"
            for option in field.options
        )
    if not values:
        return "_No response_"
    if len(values) == 1:
        return values[0]
    return "\n".join(f"- {value}" for value in values)


def _draft_checks(validation: _DraftValidation) -> list[CheckResult]:
    return [
        _reasons_check(
            "issue form schema",
            validation.schema_reasons,
            "issue form controls are supported",
            "issue form schema requires review",
        ),
        _reasons_check(
            "structured input",
            validation.input_reasons,
            "structured input is normalized",
            "structured input requires review",
        ),
        _reasons_check(
            "required fields",
            validation.required_reasons,
            "all required fields are supplied",
            "required issue-form evidence is missing",
        ),
        _reasons_check(
            "form options",
            validation.option_reasons,
            "all supplied values match issue-form options",
            "one or more supplied values are unsupported",
        ),
        CheckResult(
            "draft authorization boundary",
            Status.PASS,
            "preview is local evidence only and authorizes no external write",
            ["mutation_performed=false", "write_authorized=false"],
        ),
    ]


def _reasons_check(
    name: str,
    reasons: tuple[str, ...],
    pass_message: str,
    review_message: str,
) -> CheckResult:
    if reasons:
        return CheckResult(name, Status.MANUAL_REVIEW, review_message, list(reasons))
    return CheckResult(name, Status.PASS, pass_message)


def _normalize_input_values(
    field_name: str, value: object, issues: list[str]
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        normalized = _normalize_text(value)
        return (normalized,) if normalized else ()
    if isinstance(value, list):
        values: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str):
                issues.append(
                    f"field {field_name} list item {index} must be a string"
                )
                continue
            normalized = _normalize_text(item)
            if normalized:
                values.append(normalized)
        return tuple(values)
    issues.append(f"field {field_name} must be a string, string list, or null")
    return ()


def _normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _bullets(values: tuple[str, ...]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {value}" for value in values]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
