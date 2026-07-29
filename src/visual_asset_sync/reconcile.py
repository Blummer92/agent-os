"""Deterministic identity resolution and per-record classification.

Pure functions only. No network calls, no external writes, no mutation of
caller-supplied collections.
"""

from __future__ import annotations

from typing import Sequence

from .models import ExistingAssetRecord, ReconciliationEntry, ReconciliationResult, SourceAssetRecord
from .normalize import extract_drive_id_from_url


def resolve_identity(
    record: SourceAssetRecord,
) -> tuple[str | None, ReconciliationResult | None]:
    """Return (identity_key, forced_result).

    forced_result is None when identity resolution succeeded and normal
    matching should proceed; otherwise it is the terminal classification for
    this record (MALFORMED_IDENTITY or CONTRADICTORY_RECORD).
    """
    has_id = bool(record.drive_file_id)
    has_url = bool(record.drive_url)

    if not has_id and not has_url:
        return None, ReconciliationResult.MALFORMED_IDENTITY

    url_id = extract_drive_id_from_url(record.drive_url) if has_url else None

    if has_url and url_id is None and not has_id:
        # A URL was supplied but no File ID could be extracted, and there is
        # no File ID to fall back on.
        return None, ReconciliationResult.MALFORMED_IDENTITY

    if has_id and url_id is not None and url_id != record.drive_file_id:
        return None, ReconciliationResult.CONTRADICTORY_RECORD

    if has_id:
        return record.drive_file_id, None

    return url_id, None


def build_plan(
    source_records: Sequence[SourceAssetRecord],
    existing_records: Sequence[ExistingAssetRecord],
) -> list[ReconciliationEntry]:
    """Classify every source record. Order mirrors ``source_records``."""
    existing_by_id: dict[str, list[ExistingAssetRecord]] = {}
    for existing in existing_records:
        key = existing.drive_file_id or extract_drive_id_from_url(existing.drive_url)
        if key:
            existing_by_id.setdefault(key, []).append(existing)

    resolved: list[tuple[SourceAssetRecord, str | None, ReconciliationResult | None]] = []
    source_identity_counts: dict[str, int] = {}
    for record in source_records:
        if record.excluded:
            resolved.append((record, None, ReconciliationResult.EXCLUDED))
            continue
        identity_key, forced_result = resolve_identity(record)
        resolved.append((record, identity_key, forced_result))
        if forced_result is None and identity_key is not None:
            source_identity_counts[identity_key] = source_identity_counts.get(identity_key, 0) + 1

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
        is_source_duplicate = source_identity_counts.get(identity_key, 0) > 1

        if len(matches) > 1 or is_source_duplicate:
            entries.append(
                ReconciliationEntry(
                    source_row=record.source_row,
                    result=ReconciliationResult.DUPLICATE_ID,
                    identity_key=identity_key,
                    matched_page_ids=tuple(match.page_id for match in matches),
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
        ReconciliationResult.UPDATE_EXISTING: "Exact Drive File ID matched one existing record.",
        ReconciliationResult.CREATE_MISSING: "No existing record matches this identity.",
        ReconciliationResult.DUPLICATE_ID: "Identity matches more than one record.",
        ReconciliationResult.MALFORMED_IDENTITY: "No usable Drive File ID or Drive URL identity was found.",
        ReconciliationResult.CONTRADICTORY_RECORD: "Drive File ID and Drive URL identity disagree.",
        ReconciliationResult.EXCLUDED: "Record is marked excluded from synchronization.",
    }[result]
