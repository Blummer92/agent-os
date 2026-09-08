from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .issue_metadata import (
    load_issue_form_fields,
    metadata_contract,
    missing_metadata_fields,
    parse_issue_form_body,
)

_TIERED_REQUIRED = ("tier", "owner", "status", "source-of-truth", "external-write")
_RENDER_ORDER = ("tier", "owner", "status", "type", "source-of-truth", "external-write")


@dataclass(frozen=True, slots=True)
class LegacyIssueMigrationResult:
    body: str
    status: str
    metadata_contract: str
    missing_fields: tuple[str, ...]
    reason_codes: tuple[str, ...]
    mutation_performed: bool = False
    write_authorized: bool = False


def migrate_legacy_issue_body(
    issue_body: str,
    evidence: Mapping[str, str | Sequence[str]],
    *,
    issue_form_path: str | Path,
) -> LegacyIssueMigrationResult:
    """Render canonical tiered metadata from explicit caller-supplied evidence.

    This helper never infers values from prose, labels, titles, issue age, or
    current readiness state. It performs no GitHub write. The caller must supply
    the evidence values explicitly, and the existing parser/reconciler remains
    the only readiness projection path.
    """

    fields = load_issue_form_fields(issue_form_path)
    existing = parse_issue_form_body(issue_body, fields)
    if metadata_contract(existing) == "tiered":
        return LegacyIssueMigrationResult(
            body=issue_body,
            status="already-tiered",
            metadata_contract="tiered",
            missing_fields=(),
            reason_codes=(),
        )

    normalized, reasons = _normalize_evidence(evidence)
    missing = tuple(field for field in _TIERED_REQUIRED if field not in normalized)
    if missing or reasons:
        reason_codes = tuple((*reasons, *(f"missing-canonical-evidence:{field}" for field in missing)))
        return LegacyIssueMigrationResult(
            body=issue_body,
            status="manual-review",
            metadata_contract=metadata_contract(existing),
            missing_fields=missing,
            reason_codes=reason_codes,
        )

    headings = {field_id: label for field_id, label in fields.items()}
    rendered: list[str] = ["## Canonical metadata migration", ""]
    for field_id in _RENDER_ORDER:
        value = normalized.get(field_id)
        if value is None:
            continue
        heading = headings.get(field_id)
        if not heading:
            return LegacyIssueMigrationResult(
                body=issue_body,
                status="manual-review",
                metadata_contract=metadata_contract(existing),
                missing_fields=(),
                reason_codes=(f"canonical-heading-unavailable:{field_id}",),
            )
        rendered.extend((f"### {heading}", "", value, ""))

    base = issue_body.rstrip()
    migrated = f"{base}\n\n" + "\n".join(rendered).rstrip() + "\n"
    parsed = parse_issue_form_body(migrated, fields)
    contract = metadata_contract(parsed)
    if contract != "tiered":
        missing_after = missing_metadata_fields(parsed)["tiered"]
        return LegacyIssueMigrationResult(
            body=issue_body,
            status="manual-review",
            metadata_contract=contract,
            missing_fields=missing_after,
            reason_codes=("rendered-metadata-failed-tiered-contract",),
        )

    return LegacyIssueMigrationResult(
        body=migrated,
        status="ready-for-canonical-reconciliation",
        metadata_contract=contract,
        missing_fields=(),
        reason_codes=(),
    )


def _normalize_evidence(
    evidence: Mapping[str, str | Sequence[str]],
) -> tuple[dict[str, str], tuple[str, ...]]:
    normalized: dict[str, str] = {}
    reasons: list[str] = []
    aliases = {"readiness": "status", "work-type": "type"}

    for raw_key, raw_value in evidence.items():
        key = aliases.get(raw_key, raw_key)
        values = _values(raw_value)
        if not values:
            continue
        unique = tuple(dict.fromkeys(values))
        if len(unique) != 1:
            reasons.append(f"ambiguous-canonical-evidence:{key}")
            continue
        if key in normalized and normalized[key] != unique[0]:
            reasons.append(f"conflicting-canonical-evidence:{key}")
            continue
        normalized[key] = unique[0]

    return normalized, tuple(reasons)


def _values(value: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        items = (value,)
    else:
        items = tuple(str(item) for item in value)
    return tuple(item.strip() for item in items if item and item.strip())
