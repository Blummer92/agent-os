"""Aggregate reconciliation entries into a dry-run plan and simulate rerun."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import ExistingAssetRecord, ReconciliationEntry, ReconciliationResult, SourceAssetRecord
from .reconcile import build_plan


@dataclass(frozen=True)
class ReconciliationPlan:
    entries: tuple[ReconciliationEntry, ...]
    total_source_records: int
    dry_run: bool = True

    def count(self, result: ReconciliationResult) -> int:
        return sum(1 for entry in self.entries if entry.result is result)

    @property
    def update_existing(self) -> int:
        return self.count(ReconciliationResult.UPDATE_EXISTING)

    @property
    def create_missing(self) -> int:
        return self.count(ReconciliationResult.CREATE_MISSING)

    @property
    def duplicate_id(self) -> int:
        return self.count(ReconciliationResult.DUPLICATE_ID)

    @property
    def malformed_identity(self) -> int:
        return self.count(ReconciliationResult.MALFORMED_IDENTITY)

    @property
    def contradictory_record(self) -> int:
        return self.count(ReconciliationResult.CONTRADICTORY_RECORD)

    @property
    def excluded(self) -> int:
        return self.count(ReconciliationResult.EXCLUDED)

    @property
    def zero_write_confirmed(self) -> bool:
        return self.dry_run


def build_reconciliation_plan(
    source_records: Sequence[SourceAssetRecord],
    existing_records: Sequence[ExistingAssetRecord],
) -> ReconciliationPlan:
    entries = tuple(build_plan(source_records, existing_records))
    return ReconciliationPlan(entries=entries, total_source_records=len(source_records))


def simulate_apply(
    plan: ReconciliationPlan,
    source_records: Sequence[SourceAssetRecord],
    existing_records: Sequence[ExistingAssetRecord],
) -> tuple[ExistingAssetRecord, ...]:
    """Return a new, in-memory existing-records collection with this plan's
    CREATE_MISSING entries materialized as simulated pages.

    Performs no external writes. ``existing_records`` is not mutated; the
    caller may pass the returned tuple into a second ``build_reconciliation_plan``
    call to verify idempotent rerun behavior.
    """
    source_by_row = {record.source_row: record for record in source_records}
    simulated = list(existing_records)

    for entry in plan.entries:
        if entry.result is not ReconciliationResult.CREATE_MISSING:
            continue
        source = source_by_row[entry.source_row]
        simulated.append(
            ExistingAssetRecord(
                page_id=f"simulated:{entry.identity_key}",
                drive_file_id=source.drive_file_id,
                drive_url=source.drive_url,
                asset_title=source.file_name,
                approved_use=source.approved_use,
            )
        )

    return tuple(simulated)
