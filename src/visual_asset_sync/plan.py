"""Aggregate reconciliation entries into a dry-run plan and simulate rerun."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .models import (
    ExistingAssetRecord,
    ReconciliationEntry,
    ReconciliationResult,
    SourceAssetRecord,
)
from .reconcile import build_plan, resolve_identity


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


def _validate_plan_source_pair(
    entry: ReconciliationEntry, source: SourceAssetRecord
) -> None:
    if entry.source_row != source.source_row:
        raise ValueError("plan does not match the supplied source records")

    if source.excluded:
        expected_identity = None
        expected_forced = ReconciliationResult.EXCLUDED
    else:
        expected_identity, expected_forced = resolve_identity(source)

    if entry.identity_key != expected_identity:
        raise ValueError("plan does not match the supplied source records")
    if expected_forced is not None and entry.result is not expected_forced:
        raise ValueError("plan does not match the supplied source records")
    if expected_forced is None and entry.result in {
        ReconciliationResult.MALFORMED_IDENTITY,
        ReconciliationResult.EXCLUDED,
    }:
        raise ValueError("plan does not match the supplied source records")


def simulate_apply(
    plan: ReconciliationPlan,
    source_records: Sequence[SourceAssetRecord],
    existing_records: Sequence[ExistingAssetRecord],
) -> tuple[ExistingAssetRecord, ...]:
    """Materialize CREATE_MISSING entries in memory without external writes."""
    if (
        plan.total_source_records != len(source_records)
        or len(plan.entries) != len(source_records)
    ):
        raise ValueError("plan and source record counts differ")

    simulated = list(existing_records)
    for entry, source in zip(plan.entries, source_records):
        _validate_plan_source_pair(entry, source)
        if entry.result is not ReconciliationResult.CREATE_MISSING:
            continue
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
