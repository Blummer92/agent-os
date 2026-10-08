from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")
# Any ATX heading level: used to delimit the bare-metadata lead block so
# content under deeper non-metadata headings (e.g. `#### `) is never misread
# as lead-block metadata.
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+")
_SUPPORTED_CONTROL_TYPES = {"checkboxes", "dropdown", "input", "textarea"}

# Matches a `key: value` metadata line. The key must start with a letter so
# timestamps, URLs, and ratios (e.g. `12:30`, `https://…`) never parse as keys.
_VALUE_KEY_RE = re.compile(r"^([A-Za-z][\w\s.\-]*?)\s*:\s*(.+?)\s*$")

# A metadata value is at most three whitespace-separated tokens. This admits
# every multi-word value in the current label map ("Notion handoff",
# "Google Drive handoff", "ChatGPT planning only") while ordinary prose —
# which is longer — is ignored. Anything accepted here is still validated
# against the label map downstream; unknown values fail closed there.
_MAX_VALUE_TOKENS = 3

# Fields whose label-map values are bare tokens rather than `field:value`
# pairs. Mirrors .github/labeler/agent-os-issue-label-map.yml: source-of-truth
# values ("GitHub", "Notion handoff") and external-write values
# ("no-external-write") carry no key prefix, while tier/owner/status/type
# values do. A `key: value` line for one of these fields stores the bare value.
_BARE_VALUE_FIELDS = frozenset({"source-of-truth", "external-write"})

# Canonical field IDs preserve the existing label-map contract while allowing
# both the legacy and tiered issue forms to be parsed by one implementation.
_FIELD_ID_ALIASES = {
    "readiness": "status",
    "work-type": "type",
    "documentation-impact": "documentation_impact",
    "required-docs": "required_docs",
    "documentation-expected-change": "documentation_expected_change",
    "documentation-exemption-reason": "documentation_exemption_reason",
    "original-parent": "original_parent_issue_number",
    "root-cause-owner": "root_cause_issue_number",
}

_HEADING_ALIASES = {
    "phase": "phase",
    "epic": "epic",
    "owner agent": "owner",
    "primary owner": "owner",
    "status": "status",
    "readiness candidate": "status",
    "type": "type",
    "work type": "type",
    "source-of-truth surface": "source-of-truth",
    "source of truth": "source-of-truth",
    "external write surface": "external-write",
    "external write boundary": "external-write",
    "issue tier": "tier",
    "original parent": "original_parent_issue_number",
    "current root-cause owner": "root_cause_issue_number",
}

_REQUIRED_FIELDS = {
    "legacy": frozenset(
        {
            "phase",
            "epic",
            "owner",
            "status",
            "type",
            "source-of-truth",
            "external-write",
        }
    ),
    "tiered": frozenset(
        {
            "tier",
            "owner",
            "status",
            "source-of-truth",
            "external-write",
        }
    ),
}


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
        # Route malformed shapes to unsupported rather than stringifying them; str()
        # would invent a usable id or label out of a non-string value.
        if not isinstance(field_id, str) or not isinstance(label, str):
            unsupported.append(f"body[{index}] input control id and label must be strings")
            continue
        if control_type not in _SUPPORTED_CONTROL_TYPES:
            unsupported.append(
                f"body[{index}] field {field_id!s} uses unsupported control {control_type!r}"
            )
            continue

        raw_id = field_id
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
                label=label,
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
    """Parse an issue body into per-field value lists (full fidelity).

    Section content keeps its historical behavior: every non-empty content
    line is a value, so free-text fields (objective, scope, documentation,
    prior-scope-review) round-trip for draft validation and duplicate-review
    evidence. Additionally, bare `key: value` metadata lines appearing before
    the first heading of any level are recognized, since real issue bodies
    often carry canonical metadata above the first `## ` heading.
    """
    label_to_id = {
        _normalize(label): canonical_field_id(field_id)
        for field_id, label in fields.items()
    }
    label_to_id.update(_HEADING_ALIASES)
    key_map = _build_bare_key_map(fields)

    parsed: dict[str, list[str]] = {}
    lead, rest = _split_lead_block(issue_body)
    for raw_line in lead.splitlines():
        item = _extract_bare_value(raw_line, key_map)
        if item is not None:
            _append_value(parsed, item[0], item[1])
    for heading, content in _markdown_sections(rest):
        field_id = label_to_id.get(_normalize(heading))
        if not field_id:
            continue
        for raw_line in content.splitlines():
            value = _extract_full_value(raw_line)
            if value is not None:
                _append_value(parsed, field_id, value)
    return parsed


def parse_label_metadata(issue_body: str, fields: dict[str, str]) -> dict[str, list[str]]:
    """Parse only metadata-shaped values from an issue body.

    Same recognized shapes as `parse_issue_form_body` (bare `key: value`
    lead block plus `## `/`### ` sections), but a section line is accepted
    only when it is metadata-shaped: a `key: value` line whose key resolves to
    the section's field, or a compact bare token (at most three words, which
    admits every multi-word value in the current label map). Ordinary prose,
    examples, and explanatory Markdown are ignored and can never become
    metadata values. Unknown keys are ignored.

    This is the extraction used for label derivation (`managed_labels_for_create`
    and the connected-creation facade). Downstream fail-closed behavior is
    unchanged: missing, conflicting, or genuinely unmapped metadata still
    raises or routes to manual review there.
    """
    label_to_id = {
        _normalize(label): canonical_field_id(field_id)
        for field_id, label in fields.items()
    }
    label_to_id.update(_HEADING_ALIASES)
    key_map = _build_bare_key_map(fields)

    parsed: dict[str, list[str]] = {}
    lead, rest = _split_lead_block(issue_body)
    for raw_line in lead.splitlines():
        item = _extract_bare_value(raw_line, key_map)
        if item is not None:
            _append_value(parsed, item[0], item[1])
    for heading, content in _markdown_sections(rest):
        field_id = label_to_id.get(_normalize(heading))
        if not field_id:
            continue
        for raw_line in content.splitlines():
            value = _extract_strict_section_value(raw_line, field_id, key_map)
            if value is not None:
                _append_value(parsed, field_id, value)
    return parsed


def _append_value(parsed: dict[str, list[str]], field_id: str, value: str) -> None:
    canonical_values = parsed.setdefault(field_id, [])
    if value not in canonical_values:
        canonical_values.append(value)


def _build_bare_key_map(fields: dict[str, str]) -> dict[str, str]:
    """Map normalized metadata keys to canonical field ids.

    Covers canonical ids (`tier`), form labels (`Issue tier`), field-id
    aliases (`readiness`), and heading aliases (`primary owner`, `external
    write boundary`) so bare `key: value` lines resolve the same way section
    headings do.
    """
    key_map: dict[str, str] = {}
    for field_id, label in fields.items():
        canonical = canonical_field_id(field_id)
        key_map.setdefault(_normalize_key(field_id), canonical)
        key_map.setdefault(_normalize_key(label), canonical)
    for alias, target in _FIELD_ID_ALIASES.items():
        key_map.setdefault(_normalize_key(alias), target)
    for alias, target in _HEADING_ALIASES.items():
        key_map.setdefault(_normalize_key(alias), target)
    return key_map


def _split_lead_block(text: str) -> tuple[str, str]:
    """Split body into (lines before the first heading, the remainder).

    The split triggers on a heading of any level (`#` through `######`), so
    content under deeper non-metadata headings (e.g. `#### `) is not
    misread as lead-block metadata; it is simply not a metadata section.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _ANY_HEADING_RE.match(line):
            return "\n".join(lines[:index]), "\n".join(lines[index:])
    return "\n".join(lines), ""


def _strip_markers(raw_line: str) -> str | None:
    """Strip list/checkbox markers; return None for non-content lines."""
    line = raw_line.strip()
    if not line or line == "_No response_":
        return None
    if line.startswith("-"):
        line = line[1:].strip()
    if line.startswith("[") and "]" in line:
        line = line.split("]", 1)[1].strip()
    return line or None


def _extract_full_value(raw_line: str) -> str | None:
    """Historical per-line extraction: every content line is a value."""
    return _strip_markers(raw_line)


def _extract_bare_value(
    raw_line: str, key_map: dict[str, str]
) -> tuple[str, str] | None:
    """Parse one bare `key: value` lead-block line.

    Returns (field_id, stored value) or None. Lines without a key, with an
    unrecognized key, or with prose-length values are ignored: without a
    section for context, an unkeyed line is ambiguous and fails closed.
    """
    match = _VALUE_KEY_RE.match(raw_line.strip())
    if not match:
        return None
    field_id = key_map.get(_normalize_key(match.group(1)))
    if field_id is None:
        return None
    rest = match.group(2).strip()
    if not _is_compact_value(rest):
        return None
    return field_id, _store_value(field_id, rest)


def _extract_strict_section_value(
    raw_line: str, field_id: str, key_map: dict[str, str]
) -> str | None:
    """Extract one metadata-shaped value from a section line.

    A `key: value` line is accepted only when its key resolves to this
    section's field (preventing cross-field misattribution) and its value is
    compact. A keyless line is accepted only when compact. Ordinary prose is
    ignored; it can never become a metadata value. This is the strictness
    used for label derivation; full-fidelity parsing stays in
    `parse_issue_form_body`.
    """
    line = _strip_markers(raw_line)
    if line is None:
        return None
    match = _VALUE_KEY_RE.match(line)
    if match:
        if key_map.get(_normalize_key(match.group(1))) != field_id:
            return None
        rest = match.group(2).strip()
        if not _is_compact_value(rest):
            return None
        return _store_value(field_id, rest)
    return line if _is_compact_value(line) else None


def _store_value(field_id: str, rest: str) -> str:
    """Store a metadata value in label-map value shape.

    Fields whose label-map values are bare tokens (`source-of-truth`,
    `external-write`) store the value without a key prefix; all other fields
    store the canonical `field:value` form.
    """
    if field_id in _BARE_VALUE_FIELDS:
        return rest
    return f"{field_id}:{rest}"


def _is_compact_value(text: str) -> bool:
    tokens = text.split()
    return 1 <= len(tokens) <= _MAX_VALUE_TOKENS


def metadata_contract(metadata: dict[str, list[str]]) -> str:
    fields = set(metadata)
    if _REQUIRED_FIELDS["tiered"] <= fields:
        return "tiered"
    if _REQUIRED_FIELDS["legacy"] <= fields:
        return "legacy"
    return "incomplete"


def missing_metadata_fields(metadata: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    present = set(metadata)
    return {
        name: tuple(sorted(required - present))
        for name, required in _REQUIRED_FIELDS.items()
    }


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
        # Validate members rather than stringify them: str(item) would turn a
        # malformed entry such as None or {} into invented text.
        if not all(isinstance(item, str) for item in value):
            raise TypeError("expected a list of strings")
        return tuple(value)
    if not isinstance(value, str):
        raise TypeError("expected a string or list of strings")
    return (value,)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _markdown_sections(text: str) -> tuple[tuple[str, str], ...]:
    sections: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = []
            sections.append((match.group(1).strip(), current))
            continue
        if current is not None:
            current.append(line)
    return tuple((heading, "\n".join(lines).strip()) for heading, lines in sections)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _normalize_key(value: str) -> str:
    """Normalize a metadata key for map lookup.

    Unlike `_normalize` (which preserves the heading-alias spelling with
    spaces), this collapses every separator run — spaces, hyphens,
    underscores — to a single hyphen, so `Source of truth`, `source-of-truth`,
    and `source_of_truth` all resolve identically.
    """
    return re.sub(r"[\s_\-]+", "-", value.strip().lower())
