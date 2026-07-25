from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
_SUPPORTED_FIELD_TYPES = {"input", "textarea", "dropdown", "checkboxes"}

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


@dataclass(frozen=True, slots=True)
class IssueFormOption:
    label: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class IssueFormField:
    source_id: str
    canonical_id: str
    label: str
    field_type: str
    required: bool
    options: tuple[IssueFormOption, ...] = ()


@dataclass(frozen=True, slots=True)
class IssueFormSchema:
    name: str
    description: str
    title_prefix: str
    default_labels: tuple[str, ...]
    fields: tuple[IssueFormField, ...]
    unsupported_items: tuple[str, ...] = ()


def load_issue_form_schema(path: str | Path) -> IssueFormSchema:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("issue form must be a YAML mapping")

    body = data.get("body")
    if not isinstance(body, list):
        raise ValueError("issue form must define a body list")

    fields: list[IssueFormField] = []
    unsupported: list[str] = []
    source_ids: set[str] = set()
    canonical_ids: set[str] = set()

    for index, item in enumerate(body):
        if not isinstance(item, dict):
            unsupported.append(f"body[{index}] is not a mapping")
            continue
        field_type = str(item.get("type") or "")
        if field_type == "markdown":
            continue
        field_id = item.get("id")
        attributes = item.get("attributes") or {}
        label = attributes.get("label") if isinstance(attributes, dict) else None
        if not field_id or not label:
            unsupported.append(f"body[{index}] lacks id or label")
            continue
        source_id = str(field_id)
        canonical_id = _FIELD_ID_ALIASES.get(source_id, source_id)
        if source_id in source_ids:
            raise ValueError(f"issue form contains duplicate field id: {source_id}")
        if canonical_id in canonical_ids:
            raise ValueError(f"issue form contains duplicate canonical field id: {canonical_id}")
        source_ids.add(source_id)
        canonical_ids.add(canonical_id)

        if field_type not in _SUPPORTED_FIELD_TYPES:
            unsupported.append(f"{source_id} uses unsupported type {field_type or 'missing'}")

        validations = item.get("validations") or {}
        required = bool(validations.get("required")) if isinstance(validations, dict) else False
        options = _load_options(attributes.get("options") if isinstance(attributes, dict) else None)
        fields.append(
            IssueFormField(
                source_id=source_id,
                canonical_id=canonical_id,
                label=str(label),
                field_type=field_type,
                required=required,
                options=options,
            )
        )

    if not fields:
        raise ValueError("issue form must define body fields with id and label")

    default_labels = data.get("labels") or []
    if not isinstance(default_labels, list):
        raise ValueError("issue form labels must be a list")

    return IssueFormSchema(
        name=str(data.get("name") or ""),
        description=str(data.get("description") or ""),
        title_prefix=str(data.get("title") or ""),
        default_labels=tuple(str(label) for label in default_labels),
        fields=tuple(fields),
        unsupported_items=tuple(unsupported),
    )


def load_issue_form_fields(path: str | Path) -> dict[str, str]:
    return {field.canonical_id: field.label for field in load_issue_form_schema(path).fields}


def parse_issue_form_body(issue_body: str, fields: dict[str, str]) -> dict[str, list[str]]:
    label_to_id = {
        _normalize(label): _FIELD_ID_ALIASES.get(field_id, field_id)
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


def _load_options(raw_options: Any) -> tuple[IssueFormOption, ...]:
    if raw_options is None:
        return ()
    if not isinstance(raw_options, list):
        raise ValueError("issue form options must be a list")
    options: list[IssueFormOption] = []
    seen: set[str] = set()
    for raw in raw_options:
        if isinstance(raw, dict):
            label = raw.get("label")
            required = bool(raw.get("required"))
        else:
            label = raw
            required = False
        if label is None:
            raise ValueError("issue form option must define a label")
        text = str(label)
        if text in seen:
            raise ValueError(f"issue form contains duplicate option: {text}")
        seen.add(text)
        options.append(IssueFormOption(label=text, required=required))
    return tuple(options)


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
