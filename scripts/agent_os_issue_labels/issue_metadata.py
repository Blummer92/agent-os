from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
_SUPPORTED_CONTROL_TYPES = {"checkboxes", "dropdown", "input", "textarea"}

# Canonical field IDs preserve the existing label-map contract while allowing
# both the legacy and tiered issue forms to be parsed by one implementation.
_FIELD_ID_ALIASES = {
    "readiness": "status",
    "documentation-impact": "documentation_impact",
    "required-docs": "required_docs",
    "documentation-expected-change": "documentation_expected_change",
    "documentation-exemption-reason": "documentation_exemption_reason",
}

_HEADING_ALIASES = {
    "phase": "phase",
    "epic": "epic",
    "owner agent": "owner",
    "primary owner": "owner",
    "status": "status",
    "readiness candidate": "status",
    "type": "type",
    "source-of-truth surface": "source-of-truth",
    "source of truth": "source-of-truth",
    "external write surface": "external-write",
    "external write boundary": "external-write",
    "issue tier": "tier",
}

_LEGACY_REQUIRED_FIELDS = frozenset(
    {
        "phase",
        "epic",
        "owner",
        "status",
        "type",
        "source-of-truth",
        "external-write",
    }
)
_TIERED_REQUIRED_FIELDS = frozenset(
    {
        "tier",
        "owner",
        "status",
        "source-of-truth",
        "external-write",
    }
)


@dataclass(frozen=True)
class IssueFormField:
    field_id: str
    canonical_id: str
    control_type: str
    label: str
    required: bool
    options: tuple[str, ...] = ()
    required_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class IssueFormSchema:
    name: str
    description: str
    title_prefix: str
    default_labels: tuple[str, ...]
    default_assignees: tuple[str, ...]
    issue_type: str | None
    projects: tuple[str, ...]
    fields: tuple[IssueFormField, ...]
    unsupported_controls: tuple[str, ...] = ()


def canonical_field_id(value: str) -> str:
    return _FIELD_ID_ALIASES.get(value, value)


def load_issue_form_schema(path: str | Path) -> IssueFormSchema:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("issue form must be a YAML mapping")

    body = data.get("body", [])
    if not isinstance(body, list):
        raise ValueError("issue form body must be a list")

    fields: list[IssueFormField] = []
    unsupported: list[str] = []
    seen_canonical_ids: set[str] = set()

    for index, raw_item in enumerate(body):
        if not isinstance(raw_item, dict):
            unsupported.append(f"body[{index}] is not a mapping")
            continue

        control_type = str(raw_item.get("type") or "")
        if control_type == "markdown":
            continue

        field_id = raw_item.get("id")
        attributes = raw_item.get("attributes") or {}
        validations = raw_item.get("validations") or {}
        if not isinstance(attributes, dict) or not isinstance(validations, dict):
            unsupported.append(f"body[{index}] has malformed attributes or validations")
            continue

        label = attributes.get("label")
        if not field_id or not label:
            unsupported.append(f"body[{index}] input control must define id and label")
            continue
        if control_type not in _SUPPORTED_CONTROL_TYPES:
            unsupported.append(
                f"body[{index}] field {field_id!s} uses unsupported control {control_type!r}"
            )
            continue

        raw_id = str(field_id)
        canonical_id = canonical_field_id(raw_id)
        if canonical_id in seen_canonical_ids:
            unsupported.append(f"duplicate canonical field id: {canonical_id}")
            continue
        seen_canonical_ids.add(canonical_id)

        options, required_options = _load_options(control_type, attributes)
        fields.append(
            IssueFormField(
                field_id=raw_id,
                canonical_id=canonical_id,
                control_type=control_type,
                label=str(label),
                required=validations.get("required") is True,
                options=options,
                required_options=required_options,
            )
        )

    if not fields:
        raise ValueError("issue form must define supported body fields with id and label")

    return IssueFormSchema(
        name=str(data.get("name") or ""),
        description=str(data.get("description") or ""),
        title_prefix=str(data.get("title") or ""),
        default_labels=_string_tuple(data.get("labels")),
        default_assignees=_string_tuple(data.get("assignees")),
        issue_type=_optional_string(data.get("type")),
        projects=_string_tuple(data.get("projects")),
        fields=tuple(fields),
        unsupported_controls=tuple(unsupported),
    )


def load_issue_form_fields(path: str | Path) -> dict[str, str]:
    schema = load_issue_form_schema(path)
    return {field.canonical_id: field.label for field in schema.fields}


def parse_issue_form_body(issue_body: str, fields: dict[str, str]) -> dict[str, list[str]]:
    label_to_id = {
        _normalize(label): canonical_field_id(field_id)
        for field_id, label in fields.items()
    }
    label_to_id.update(_HEADING_ALIASES)

    sections = _markdown_sections(issue_body)
    parsed: dict[str, list[str]] = {}
    for heading, content in sections.items():
        field_id = label_to_id.get(_normalize(heading))
        if not field_id:
            continue
        values = _parse_values(content)
        if values:
            parsed[field_id] = values
    return parsed


def metadata_contract(metadata: dict[str, list[str]]) -> str:
    fields = set(metadata)
    if _TIERED_REQUIRED_FIELDS <= fields:
        return "tiered"
    if _LEGACY_REQUIRED_FIELDS <= fields:
        return "legacy"
    return "incomplete"


def _load_options(
    control_type: str, attributes: dict[str, Any]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    raw_options = attributes.get("options") or []
    if not isinstance(raw_options, list):
        return (), ()

    options: list[str] = []
    required_options: list[str] = []
    for raw_option in raw_options:
        if control_type == "checkboxes":
            if not isinstance(raw_option, dict) or not raw_option.get("label"):
                continue
            label = str(raw_option["label"])
            options.append(label)
            if raw_option.get("required") is True:
                required_options.append(label)
        else:
            options.append(str(raw_option))
    return tuple(options), tuple(required_options)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _markdown_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = match.group(1).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _parse_values(content: str) -> list[str]:
    values: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line == "_No response_":
            continue
        if line.startswith("-"):
            line = line[1:].strip()
        if line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].strip()
        if line:
            values.append(line)
    return values


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())
