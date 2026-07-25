from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.agent_os_issue_acceptance.models import CheckResult, Status, strongest_status

from .checker import evaluate_issue_labels
from .issue_metadata import IssueFormField, IssueFormSchema, load_issue_form_schema
from .label_map import expected_labels, load_label_map

DRAFT_SCHEMA = "agent-os-issue-draft/v1"


class IssueDraftInputError(ValueError):
    """Raised when structured draft input is malformed before evaluation."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise IssueDraftInputError(f"duplicate mapping key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class IssueDraftInput:
    title: str
    fields: tuple[tuple[str, tuple[str, ...]], ...]

    def field_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.fields)


@dataclass(frozen=True, slots=True)
class IssueDraftResult:
    schema: str
    title: str
    body: str
    proposed_labels: tuple[str, ...]
    overall_status: Status
    checks: tuple[CheckResult, ...]
    manual_review_items: tuple[str, ...]
    mutation_performed: bool = False
    write_authorized: bool = False


def load_issue_draft_input(text: str) -> IssueDraftInput:
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except IssueDraftInputError:
        raise
    except yaml.YAMLError as exc:
        raise IssueDraftInputError(
            f"structured input is not valid YAML or JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise IssueDraftInputError("structured input must be a mapping")
    unknown_top = sorted(str(key) for key in set(data) - {"title", "fields"})
    if unknown_top:
        raise IssueDraftInputError(f"unknown top-level keys: {', '.join(unknown_top)}")

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise IssueDraftInputError("title must be a non-empty string")
    raw_fields = data.get("fields")
    if not isinstance(raw_fields, dict):
        raise IssueDraftInputError("fields must be a mapping")

    normalized: list[tuple[str, tuple[str, ...]]] = []
    for key, raw_value in raw_fields.items():
        if not isinstance(key, str) or not key:
            raise IssueDraftInputError("field names must be non-empty strings")
        normalized.append((key, _normalize_input_value(raw_value, key)))
    return IssueDraftInput(title=title.strip(), fields=tuple(normalized))


def load_issue_draft_input_file(path: str | Path) -> IssueDraftInput:
    return load_issue_draft_input(Path(path).read_text(encoding="utf-8"))


def build_issue_draft(
    draft_input: IssueDraftInput,
    *,
    issue_form_path: str | Path,
    label_map_path: str | Path,
) -> IssueDraftResult:
    schema = load_issue_form_schema(issue_form_path)
    supplied = draft_input.field_map()
    known_ids = {field.source_id for field in schema.fields}
    manual_review: list[str] = [
        f"issue form compatibility requires review: {item}"
        for item in schema.unsupported_items
    ]
    manual_review.extend(
        f"unknown input field requires review: {field_id}"
        for field_id in sorted(set(supplied) - known_ids)
    )

    sections: list[str] = []
    normalized_for_checks: dict[str, tuple[str, ...]] = {}
    for field in schema.fields:
        values = supplied.get(field.source_id, ())
        rendered, normalized, findings = _render_field(field, values)
        manual_review.extend(findings)
        normalized_for_checks[field.source_id] = normalized
        sections.extend([f"### {field.label}", "", rendered, ""])

    title = draft_input.title
    if schema.title_prefix and not title.startswith(schema.title_prefix):
        title = f"{schema.title_prefix}{title}"
    body = "\n".join(sections).rstrip() + "\n"

    label_map = load_label_map(label_map_path)
    parsed_metadata = _metadata_for_label_map(schema, normalized_for_checks)
    labels, unknown_label_values = expected_labels(parsed_metadata, label_map)
    manual_review.extend(
        f"unmapped value requires review: {value}" for value in unknown_label_values
    )
    proposed_labels = tuple(sorted(labels))

    label_report = evaluate_issue_labels(
        issue_body=body,
        existing_labels=list(proposed_labels),
        issue_form_path=issue_form_path,
        label_map_path=label_map_path,
    )
    manual_review.extend(label_report.manual_review_items)
    manual_review = sorted(set(manual_review))

    draft_check = CheckResult(
        name="issue draft input",
        status=Status.MANUAL_REVIEW if manual_review else Status.PASS,
        message=(
            "draft requires human review before any submission"
            if manual_review
            else "draft satisfies the current issue-form shape"
        ),
        evidence=manual_review,
    )
    checks = tuple([draft_check, *label_report.checks])
    overall = strongest_status(list(checks))

    return IssueDraftResult(
        schema=DRAFT_SCHEMA,
        title=title,
        body=body,
        proposed_labels=proposed_labels,
        overall_status=overall,
        checks=checks,
        manual_review_items=tuple(manual_review),
    )


def issue_draft_to_dict(result: IssueDraftResult) -> dict[str, object]:
    return {
        "schema": result.schema,
        "title": result.title,
        "body": result.body,
        "proposed_labels": list(result.proposed_labels),
        "overall_status": result.overall_status.value,
        "checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "evidence": list(check.evidence),
            }
            for check in result.checks
        ],
        "manual_review_items": list(result.manual_review_items),
        "mutation_performed": result.mutation_performed,
        "write_authorized": result.write_authorized,
    }


def render_issue_draft_json(result: IssueDraftResult) -> str:
    return (
        json.dumps(
            issue_draft_to_dict(result),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def render_issue_draft_text(result: IssueDraftResult) -> str:
    lines = [
        "Agent OS Issue Draft Preview",
        f"Schema: {result.schema}",
        f"Overall result: {result.overall_status.value}",
        f"Mutation performed: {'yes' if result.mutation_performed else 'no'}",
        f"Write authorized: {'yes' if result.write_authorized else 'no'}",
        f"Title: {result.title}",
        "Proposed labels:",
        *_bullets(result.proposed_labels),
        "Manual review items:",
        *_bullets(result.manual_review_items),
        "Body:",
        "--- begin issue body ---",
        result.body.rstrip("\n"),
        "--- end issue body ---",
    ]
    return "\n".join(lines) + "\n"


def render_issue_draft_error(message: str, *, output_format: str) -> str:
    payload = {
        "schema": DRAFT_SCHEMA,
        "overall_status": Status.FAIL.value,
        "error": message,
        "mutation_performed": False,
        "write_authorized": False,
    }
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return "\n".join(
        [
            "Agent OS Issue Draft Preview",
            f"Schema: {DRAFT_SCHEMA}",
            f"Overall result: {Status.FAIL.value}",
            "Mutation performed: no",
            "Write authorized: no",
            f"Error: {message}",
            "",
        ]
    )


def _normalize_input_value(raw_value: Any, field_id: str) -> tuple[str, ...]:
    if raw_value is None:
        return ()
    if isinstance(raw_value, (str, int, float, bool)):
        return (_normalized_text(str(raw_value)),)
    if isinstance(raw_value, list):
        values: list[str] = []
        for value in raw_value:
            if isinstance(value, (dict, list)):
                raise IssueDraftInputError(f"field {field_id} contains a nested value")
            if value is not None:
                values.append(_normalized_text(str(value)))
        return tuple(values)
    raise IssueDraftInputError(f"field {field_id} must be a scalar, list, or null")


def _render_field(
    field: IssueFormField,
    values: tuple[str, ...],
) -> tuple[str, tuple[str, ...], list[str]]:
    findings: list[str] = []
    nonblank = tuple(value for value in values if value.strip())

    if field.required and not nonblank:
        findings.append(f"required field is missing: {field.source_id}")

    if field.field_type in {"input", "textarea"}:
        if len(nonblank) > 1:
            findings.append(f"field must contain one scalar value: {field.source_id}")
        normalized = ("\n".join(nonblank),) if nonblank else ()
        return (normalized[0] if normalized else "_No response_", normalized, findings)

    if field.field_type == "dropdown":
        if len(nonblank) > 1:
            findings.append(f"dropdown must contain exactly one value: {field.source_id}")
        allowed = {option.label for option in field.options}
        for value in nonblank:
            if value not in allowed:
                findings.append(f"unknown option for {field.source_id}: {value}")
        normalized = nonblank[:1]
        return (normalized[0] if normalized else "_No response_", normalized, findings)

    if field.field_type == "checkboxes":
        allowed_order = [option.label for option in field.options]
        selected = set(nonblank)
        for value in nonblank:
            if value not in allowed_order:
                findings.append(f"unknown checkbox option for {field.source_id}: {value}")
        for option in field.options:
            if option.required and option.label not in selected:
                findings.append(
                    f"required checkbox option is missing for {field.source_id}: {option.label}"
                )
        normalized = tuple(option for option in allowed_order if option in selected)
        rendered = "\n".join(f"- [x] {option}" for option in normalized)
        return (rendered or "_No response_", normalized, findings)

    findings.append(f"unsupported field type for {field.source_id}: {field.field_type}")
    rendered = "\n".join(nonblank) or "_No response_"
    return rendered, nonblank, findings


def _metadata_for_label_map(
    schema: IssueFormSchema,
    normalized: dict[str, tuple[str, ...]],
) -> dict[str, list[str]]:
    metadata: dict[str, list[str]] = {}
    for field in schema.fields:
        values = list(normalized.get(field.source_id, ()))
        if values:
            metadata[field.canonical_id] = values
    return metadata


def _normalized_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _bullets(values: tuple[str, ...]) -> list[str]:
    return [f"- {value}" for value in values] if values else ["- none"]
