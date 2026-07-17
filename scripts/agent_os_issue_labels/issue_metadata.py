from __future__ import annotations

import re
from pathlib import Path

import yaml

_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")


def load_issue_form_fields(path: str | Path) -> dict[str, str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    fields: dict[str, str] = {}
    for item in data.get("body", []):
        field_id = item.get("id")
        label = (item.get("attributes") or {}).get("label")
        if field_id and label:
            fields[str(field_id)] = str(label)
    if not fields:
        raise ValueError("issue form must define body fields with id and label")
    return fields


def parse_issue_form_body(issue_body: str, fields: dict[str, str]) -> dict[str, list[str]]:
    label_to_id = {_normalize(label): field_id for field_id, label in fields.items()}
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
