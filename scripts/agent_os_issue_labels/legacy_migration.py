from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .issue_metadata import load_issue_form_fields, metadata_contract, parse_issue_form_body
from .label_map import expected_labels, load_label_map

_REQUIRED_TIERED_FIELDS = (
    "tier",
    "owner",
    "status",
    "source-of-truth",
    "external-write",
)
_OPTIONAL_TIERED_FIELDS = ("type",)
_ALLOWED_EVIDENCE_FIELDS = frozenset((*_REQUIRED_TIERED_FIELDS, *_OPTIONAL_TIERED_FIELDS))
_FIELD_HEADINGS = (
    ("tier", "Issue tier"),
    ("owner", "Primary owner"),
    ("status", "Readiness candidate"),
    ("type", "Work type"),
    ("source-of-truth", "Source of truth"),
    ("external-write", "External write boundary"),
)


@dataclass(frozen=True, slots=True)
class LegacyIssueMigrationResult:
    body: str
    disposition: str
    metadata_contract: str
    reason_codes: tuple[str, ...]
    canonical_metadata: tuple[tuple[str, tuple[str, ...]], ...]
    mutation_performed: bool = False


def build_legacy_issue_migration(
    issue_body: str,
    evidence: Mapping[str, str | Sequence[str]],
    *,
    issue_form_path: str | Path,
    label_map_path: str | Path,
) -> LegacyIssueMigrationResult:
    """Build a fail-closed canonical metadata migration without mutating GitHub."""
    fields = load_issue_form_fields(issue_form_path)
    existing = parse_issue_form_body(issue_body, fields)
    existing_contract = metadata_contract(existing)

    if existing_contract == "tiered":
        return LegacyIssueMigrationResult(
            issue_body,
            "already-canonical",
            "tiered",
            (),
            _freeze_metadata(existing),
        )

    if existing:
        return LegacyIssueMigrationResult(
            issue_body,
            "manual-review",
            existing_contract,
            ("existing-canonical-metadata-incomplete",),
            _freeze_metadata(existing),
        )

    normalized, reasons = _normalize_evidence(evidence)
    missing = tuple(field for field in _REQUIRED_TIERED_FIELDS if field not in normalized)
    reasons.extend(f"missing-canonical-evidence:{field}" for field in missing)
    if reasons:
        return LegacyIssueMigrationResult(
            issue_body,
            "manual-review",
            "incomplete",
            tuple(reasons),
            _freeze_metadata(normalized),
        )

    _, unknown = expected_labels(normalized, load_label_map(label_map_path))
    if unknown:
        return LegacyIssueMigrationResult(
            issue_body,
            "manual-review",
            "incomplete",
            tuple(f"unmapped-canonical-evidence:{item}" for item in sorted(unknown)),
            _freeze_metadata(normalized),
        )

    migrated_body = _append_canonical_block(issue_body, normalized)
    parsed = parse_issue_form_body(migrated_body, fields)
    contract = metadata_contract(parsed)
    if contract != "tiered":
        return LegacyIssueMigrationResult(
            issue_body,
            "manual-review",
            contract,
            ("rendered-canonical-metadata-invalid",),
            _freeze_metadata(parsed),
        )

    return LegacyIssueMigrationResult(
        migrated_body,
        "migrated",
        "tiered",
        (),
        _freeze_metadata(parsed),
    )


def _normalize_evidence(
    evidence: Mapping[str, str | Sequence[str]],
) -> tuple[dict[str, list[str]], list[str]]:
    normalized: dict[str, list[str]] = {}
    reasons: list[str] = []
    for raw_field, raw_value in evidence.items():
        field = str(raw_field).strip()
        if field not in _ALLOWED_EVIDENCE_FIELDS:
            reasons.append(f"unsupported-canonical-evidence-field:{field}")
            continue
        if isinstance(raw_value, str):
            raw_values = (raw_value,)
        elif isinstance(raw_value, Sequence):
            raw_values = tuple(str(value) for value in raw_value)
        else:
            reasons.append(f"invalid-canonical-evidence-type:{field}")
            continue
        values: list[str] = []
        for value in raw_values:
            text = str(value).strip()
            if not text:
                reasons.append(f"blank-canonical-evidence:{field}")
                continue
            if "\n" in text or "\r" in text:
                reasons.append(f"multiline-canonical-evidence:{field}")
                continue
            values.append(text)
        if not values:
            continue
        if field != "type" and len(values) != 1:
            reasons.append(f"ambiguous-canonical-evidence:{field}")
            continue
        normalized[field] = values
    return normalized, reasons


def _append_canonical_block(issue_body: str, metadata: dict[str, list[str]]) -> str:
    sections = ["## Canonical metadata"]
    for field, heading in _FIELD_HEADINGS:
        values = metadata.get(field)
        if not values:
            continue
        sections.extend((f"### {heading}", "\n".join(values)))
    block = "\n\n".join(sections)
    prefix = issue_body.rstrip()
    return f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"


def _freeze_metadata(
    metadata: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (field, tuple(metadata[field]))
        for field, _ in _FIELD_HEADINGS
        if field in metadata
    )
