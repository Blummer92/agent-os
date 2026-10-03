"""Deterministic identity resolution and per-record classification."""

from __future__ import annotations

from typing import Any, Sequence

from .models import (
    ExistingAssetRecord,
    ReconciliationEntry,
    ReconciliationResult,
    SourceAssetRecord,
)
from .normalize import extract_drive_id_candidates, is_valid_drive_file_id

_EXISTING_CONTRADICTION_REASON = "Existing record identity evidence is contradictory."


def resolve_identity(
    record: SourceAssetRecord,
) -> tuple[str | None, ReconciliationResult | None]:
    """Return the source identity and any terminal source classification."""
    url_candidates = extract_drive_id_candidates(record.drive_url)

    if record.drive_file_id:
        if not is_valid_drive_file_id(record.drive_file_id):
            return None, ReconciliationResult.MALFORMED_IDENTITY
        if any(candidate != record.drive_file_id for candidate in url_candidates):
            return None, ReconciliationResult.CONTRADICTORY_RECORD
        return record.drive_file_id, None

    if len(url_candidates) == 1:
        return url_candidates[0], None

    return None, ReconciliationResult.MALFORMED_IDENTITY


def existing_identity_evidence(
    record: ExistingAssetRecord,
) -> tuple[str | None, tuple[str, ...]]:
    """Return (valid identity, contradictory candidate identities)."""
    url_candidates = extract_drive_id_candidates(record.drive_url)

    if record.drive_file_id:
        if not is_valid_drive_file_id(record.drive_file_id):
            return None, ()
        conflicts = tuple(
            sorted(
                {record.drive_file_id, *url_candidates}
                if any(
                    candidate != record.drive_file_id
                    for candidate in url_candidates
                )
                else ()
            )
        )
        if conflicts:
            return None, conflicts
        return record.drive_file_id, ()

    if len(url_candidates) == 1:
        return url_candidates[0], ()
    if len(url_candidates) > 1:
        return None, tuple(sorted(url_candidates))
    return None, ()


def existing_identity_key(record: ExistingAssetRecord) -> str | None:
    """Return only a non-contradictory existing-record identity."""
    identity_key, contradictions = existing_identity_evidence(record)
    if contradictions:
        return None
    return identity_key


def build_plan(
    source_records: Sequence[SourceAssetRecord],
    existing_records: Sequence[ExistingAssetRecord],
) -> list[ReconciliationEntry]:
    """Classify every source record. Output order mirrors source_records."""
    existing_by_id: dict[str, list[ExistingAssetRecord]] = {}
    contradictory_by_id: dict[str, set[str]] = {}
    for existing in existing_records:
        key, contradictory_keys = existing_identity_evidence(existing)
        if key:
            existing_by_id.setdefault(key, []).append(existing)
        for contradictory_key in contradictory_keys:
            contradictory_by_id.setdefault(contradictory_key, set()).add(
                existing.page_id
            )

    resolved: list[
        tuple[SourceAssetRecord, str | None, ReconciliationResult | None]
    ] = []
    source_identity_counts: dict[str, int] = {}
    for record in source_records:
        if record.excluded:
            resolved.append((record, None, ReconciliationResult.EXCLUDED))
            continue
        identity_key, forced_result = resolve_identity(record)
        resolved.append((record, identity_key, forced_result))
        if forced_result is None and identity_key is not None:
            source_identity_counts[identity_key] = (
                source_identity_counts.get(identity_key, 0) + 1
            )

    entries: list[ReconciliationEntry] = []
    for record, identity_key, forced_result in resolved:
        if forced_result is not None:
            entries.append(
                ReconciliationEntry(
                    source_row=record.source_row,
                    result=forced_result,
                    identity_key=identity_key,
                    reason=_reason_for(forced_result),
                )
            )
            continue

        matches = existing_by_id.get(identity_key, [])
        contradictory_pages = contradictory_by_id.get(identity_key, set())
        if contradictory_pages:
            relevant_pages = sorted(
                contradictory_pages | {match.page_id for match in matches}
            )
            entries.append(
                ReconciliationEntry(
                    source_row=record.source_row,
                    result=ReconciliationResult.CONTRADICTORY_RECORD,
                    identity_key=identity_key,
                    matched_page_ids=tuple(relevant_pages),
                    reason=_EXISTING_CONTRADICTION_REASON,
                )
            )
            continue

        is_source_duplicate = source_identity_counts.get(identity_key, 0) > 1
        if len(matches) > 1 or is_source_duplicate:
            entries.append(
                ReconciliationEntry(
                    source_row=record.source_row,
                    result=ReconciliationResult.DUPLICATE_ID,
                    identity_key=identity_key,
                    matched_page_ids=tuple(
                        sorted(match.page_id for match in matches)
                    ),
                    reason=_reason_for(ReconciliationResult.DUPLICATE_ID),
                )
            )
            continue

        if len(matches) == 1:
            match = matches[0]
            entries.append(
                ReconciliationEntry(
                    source_row=record.source_row,
                    result=ReconciliationResult.UPDATE_EXISTING,
                    identity_key=identity_key,
                    matched_page_ids=(match.page_id,),
                    reason=_reason_for(ReconciliationResult.UPDATE_EXISTING),
                    preserved_fields=dict(match.extra_fields),
                )
            )
            continue

        entries.append(
            ReconciliationEntry(
                source_row=record.source_row,
                result=ReconciliationResult.CREATE_MISSING,
                identity_key=identity_key,
                reason=_reason_for(ReconciliationResult.CREATE_MISSING),
            )
        )

    return entries


def _reason_for(result: ReconciliationResult) -> str:
    return {
        ReconciliationResult.UPDATE_EXISTING: (
            "Exact Drive File ID matched one existing record."
        ),
        ReconciliationResult.CREATE_MISSING: (
            "No existing record matches this identity."
        ),
        ReconciliationResult.DUPLICATE_ID: (
            "Identity matches more than one record."
        ),
        ReconciliationResult.MALFORMED_IDENTITY: (
            "No single usable Drive File ID or Drive URL identity was found."
        ),
        ReconciliationResult.CONTRADICTORY_RECORD: (
            "Drive File ID and Drive URL identity disagree."
        ),
        ReconciliationResult.EXCLUDED: (
            "Record is marked excluded from synchronization."
        ),
    }[result]


def _normalize_title(title: str | None) -> str | None:
    if not isinstance(title, str):
        return None
    normalized = " ".join(title.split()).casefold()
    return normalized or None


def find_duplicate_titles(
    existing_records: Sequence[ExistingAssetRecord],
) -> list[dict[str, Any]]:
    """Report existing records that share a normalized title (read-only, #3256).

    Duplicate titles do not block reconciliation -- identity is by Drive file
    ID -- but they are an explicit reconciliation signal: two records with the
    same title may describe the same logical asset and deserve human review
    before either is treated as canonical. This function performs no writes;
    it only reports.
    """
    by_title: dict[str, list[ExistingAssetRecord]] = {}
    for record in existing_records:
        title = _normalize_title(record.asset_title)
        if title is None:
            continue
        by_title.setdefault(title, []).append(record)
    report: list[dict[str, Any]] = []
    for title in sorted(by_title):
        records = by_title[title]
        if len(records) < 2:
            continue
        report.append(
            {
                "normalized_title": title,
                "record_count": len(records),
                "page_ids": tuple(sorted(record.page_id for record in records)),
                "drive_file_ids": tuple(
                    sorted({record.drive_file_id for record in records if record.drive_file_id})
                ),
                "disposition": "duplicate-title-needs-review",
            }
        )
    return report
