"""Deterministic identity resolution and per-record classification.

Pure functions only. No network calls, no external writes, no mutation of
caller-supplied collections.
"""

from __future__ import annotations

from typing import Sequence

from .models import ExistingAssetRecord, ReconciliationEntry, ReconciliationResult, SourceAssetRecord
from .normalize import (
    extract_drive_id_candidates,
    extract_drive_id_from_url,
    is_valid_drive_file_id,
)


def resolve_identity(
    record: SourceAssetRecord,
) -> tuple[str | None, ReconciliationResult | None]:
    """Return (identity_key, forced_result).

    forced_result is None when identity resolution succeeded and normal
    matching should proceed; otherwise it is the terminal classification for
    this record (MALFORMED_IDENTITY or CONTRADICTORY_RECORD).

    A valid explicit ``drive_file_id`` is primary. URL fallback applies only
    when no explicit ID is present, and only when the URL carries exactly one
    distinct valid candidate ID. A malformed explicit ID is MALFORMED_IDENTITY
    rather than CONTRADICTORY_RECORD: contradiction requires a valid explicit
    ID to disagree with valid URL-derived evidence.
    """
    url_candidates = extract_drive_id_candidates(record.drive_url)

    if record.drive_file_id:
        if not is_valid_drive_file_id(record.drive_file_id):
            return None, ReconciliationResult.MALFORMED_IDENTITY
        if any(candidate != record.drive_file_id for candidate in url_candidates):
            return None, ReconciliationResult.CONTRADICTORY_RECORD
        return record.drive_file_id, None

    if len(url_candidates) == 1:
        return url_candidates[0], None

    # No identity at all, an unsupported or unparseable URL, or an ambiguous
    # URL carrying more than one distinct candidate ID.
    return None, ReconciliationResult.MALFORMED_IDENTITY


def existing_identity_key(record: ExistingAssetRecord) -> str | None:
    """Identity key for an existing record, or None when it has no valid one.

    Mirrors source-side precedence: a valid explicit ``drive_file_id`` wins,
    otherwise an unambiguous URL-derived ID is used. Records with no valid
    identity are simply not indexed, so they can never be matched.
    """
    if record.drive_file_id:
        if is_valid_drive_file_id(record.drive_file_id):
            return record.drive_file_id
        return None
    return extract_drive_id_from_url(record.drive_url)


def build_plan(
    source_records: Sequence[SourceAssetRecord],
    existing_records: Sequence[ExistingAssetRecord],
) -> list[ReconciliationEntry]:
    """Classify every source record. Order mirrors ``source_records``."""
    existing_by_id: dict[str, list[ExistingAssetRecord]] = {}
    for existing in existing_records:
        key = existing_identity_key(existing)
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
        ReconciliationResult.MALFORMED_IDENTITY: "No single usable Drive File ID or Drive URL identity was found.",
        ReconciliationResult.CONTRADICTORY_RECORD: "Drive File ID and Drive URL identity disagree.",
        ReconciliationResult.EXCLUDED: "Record is marked excluded from synchronization.",
    }[result]
