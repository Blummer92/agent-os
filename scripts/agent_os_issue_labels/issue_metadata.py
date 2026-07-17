from __future__ import annotations

import re
from pathlib import Path

import yaml

_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")

# Canonical field IDs preserve the existing label-map contract while allowing
# both the legacy and tiered issue forms to be parsed by one implementation.
_FIELD_ID_ALIASES = {
    "readiness": "status",
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


def load_issue_form_fields(path: str | Path) -> dict[str, str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    fields: dict[str, str] = {}
    for item in data.get("body", []):
        field_id = item.get("id")
        label = (item.get("attributes") or {}).get("label")
        if field_id and label:
            canonical_id = _FIELD_ID_ALIASES.get(str(field_id), str(field_id))
            fields[canonical_id] = str(label)
    if not fields:
        raise ValueError("issue form must define body fields with id and label")
    return fields


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
