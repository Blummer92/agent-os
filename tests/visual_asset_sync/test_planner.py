"""Focused tests for plan aggregation, reporting, and idempotent rerun."""

from __future__ import annotations

import json

import pytest

from visual_asset_sync.models import (
    ExistingAssetRecord,
    ReconciliationResult,
    SourceAssetRecord,
)
from visual_asset_sync.plan import build_reconciliation_plan, simulate_apply
from visual_asset_sync.report import plan_to_dict, plan_to_json, plan_to_summary

VALID_ID = "abc123def456ghi789jkl012m"
OTHER_ID = "zyx987wvu654tsr321qpo098n"
THIRD_ID = "third12345678901234567890"


def source(row: str, **kwargs) -> SourceAssetRecord:
    return SourceAssetRecord(source_row=row, **kwargs)


def existing(page_id: str, **kwargs) -> ExistingAssetRecord:
    return ExistingAssetRecord(page_id=page_id, **kwargs)


def test_plan_totals_and_zero_write_confirmation() -> None:
    records = [
        source("1", drive_file_id=VALID_ID),
        source("2", drive_file_id=OTHER_ID),
        source("3"),
        source("4", excluded=True),
    ]
    plan = build_reconciliation_plan(
        records, [existing("page-1", drive_file_id=VALID_ID)]
    )
    assert plan.total_source_records == 4
    assert plan.update_existing == 1
    assert plan.create_missing == 1
    assert plan.malformed_identity == 1
    assert plan.excluded == 1
    assert plan.dry_run is True
    assert plan.zero_write_confirmed is True


def test_repeated_runs_are_deterministic() -> None:
    records = [
        source("1", drive_file_id=VALID_ID),
        source("2", drive_file_id=OTHER_ID),
    ]
    existing_records = [existing("page-1", drive_file_id=VALID_ID)]
    assert plan_to_dict(build_reconciliation_plan(records, existing_records)) == plan_to_dict(
        build_reconciliation_plan(records, existing_records)
    )


def test_idempotent_rerun_does_not_propose_duplicate_creates() -> None:
    records = [
        source("1", drive_file_id=VALID_ID),
        source("2", drive_file_id=OTHER_ID),
    ]
    existing_records = [existing("page-1", drive_file_id=VALID_ID)]
    first_plan = build_reconciliation_plan(records, existing_records)
    simulated = simulate_apply(first_plan, records, existing_records)
    second_plan = build_reconciliation_plan(records, simulated)
    assert first_plan.create_missing == 1
    assert second_plan.create_missing == 0
    assert second_plan.update_existing == 2


def test_simulate_apply_does_not_mutate_inputs() -> None:
    records = [source("1", drive_file_id=VALID_ID)]
    existing_records = [existing("page-old", drive_file_id=OTHER_ID)]
    plan = build_reconciliation_plan(records, existing_records)
    entries_before = plan.entries
    source_before = tuple(records)
    existing_before = tuple(existing_records)
    simulated = simulate_apply(plan, records, existing_records)
    assert plan.entries == entries_before
    assert tuple(records) == source_before
    assert tuple(existing_records) == existing_before
    assert isinstance(simulated, tuple)
    assert len(simulated) == 2


def test_excluded_records_remain_represented_in_plan_output() -> None:
    plan = build_reconciliation_plan([source("1", excluded=True)], [])
    assert len(plan.entries) == 1
    assert plan.entries[0].result is ReconciliationResult.EXCLUDED
    assert plan.excluded == 1


def test_plan_to_json_is_valid_and_matches_summary_counts() -> None:
    records = [
        source("1", drive_file_id=VALID_ID),
        source("2", drive_file_id=OTHER_ID),
    ]
    plan = build_reconciliation_plan(
        records, [existing("page-1", drive_file_id=VALID_ID)]
    )
    payload = json.loads(plan_to_json(plan))
    assert payload["dry_run"] is True
    assert payload["zero_write_confirmed"] is True
    assert payload["total_source_records"] == 2
    assert payload["summary"]["update_existing"] == 1
    assert payload["summary"]["create_missing"] == 1
    assert len(payload["entries"]) == 2


def test_plan_to_summary_is_human_readable_text() -> None:
    plan = build_reconciliation_plan([source("1", drive_file_id=VALID_ID)], [])
    summary = plan_to_summary(plan)
    assert "Visual Asset Reconciliation Plan" in summary
    assert "zero external writes" in summary
    assert "CREATE_MISSING:       1" in summary


def test_dry_run_performs_zero_external_writes() -> None:
    plan = build_reconciliation_plan([source("1", drive_file_id=VALID_ID)], [])
    assert plan.dry_run is True
    assert plan.zero_write_confirmed is True


def test_duplicate_source_rows_with_distinct_creates_are_applied_positionally() -> None:
    records = [
        source("same-row", drive_file_id=VALID_ID, file_name="first.png"),
        source("same-row", drive_file_id=OTHER_ID, file_name="second.png"),
    ]
    plan = build_reconciliation_plan(records, [])
    simulated = simulate_apply(plan, records, [])
    assert [record.drive_file_id for record in simulated] == [VALID_ID, OTHER_ID]
    assert [record.asset_title for record in simulated] == ["first.png", "second.png"]


def test_duplicate_rows_mixed_with_update_and_exclusion_remain_aligned() -> None:
    records = [
        source("same-row", drive_file_id=VALID_ID),
        source("same-row", drive_file_id=OTHER_ID),
        source("same-row", excluded=True),
    ]
    existing_records = [existing("page-1", drive_file_id=VALID_ID)]
    plan = build_reconciliation_plan(records, existing_records)
    simulated = simulate_apply(plan, records, existing_records)
    assert [entry.result for entry in plan.entries] == [
        ReconciliationResult.UPDATE_EXISTING,
        ReconciliationResult.CREATE_MISSING,
        ReconciliationResult.EXCLUDED,
    ]
    assert len(simulated) == 2
    assert simulated[-1].drive_file_id == OTHER_ID


def test_plan_source_count_mismatch_fails_closed() -> None:
    records = [source("1", drive_file_id=VALID_ID)]
    plan = build_reconciliation_plan(records, [])
    with pytest.raises(ValueError, match="plan and source record counts differ"):
        simulate_apply(plan, [], [])


def test_reordered_source_input_fails_closed() -> None:
    records = [
        source("1", drive_file_id=VALID_ID),
        source("2", drive_file_id=OTHER_ID),
    ]
    plan = build_reconciliation_plan(records, [])
    with pytest.raises(ValueError, match="plan does not match"):
        simulate_apply(plan, list(reversed(records)), [])


def test_mismatched_source_identity_fails_closed() -> None:
    original = [source("1", drive_file_id=VALID_ID)]
    plan = build_reconciliation_plan(original, [])
    changed = [source("1", drive_file_id=OTHER_ID)]
    with pytest.raises(ValueError, match="plan does not match"):
        simulate_apply(plan, changed, [])


def test_mismatched_source_classification_fails_closed() -> None:
    original = [source("1", drive_file_id=VALID_ID)]
    plan = build_reconciliation_plan(original, [])
    changed = [source("1", drive_file_id=VALID_ID, excluded=True)]
    with pytest.raises(ValueError, match="plan does not match"):
        simulate_apply(plan, changed, [])


def test_url_fallback_create_remains_idempotent() -> None:
    records = [
        source(
            "1",
            drive_url=f"https://drive.google.com/file/d/{THIRD_ID}/view",
        )
    ]
    first_plan = build_reconciliation_plan(records, [])
    simulated = simulate_apply(first_plan, records, [])
    second_plan = build_reconciliation_plan(records, simulated)
    assert first_plan.create_missing == 1
    assert second_plan.update_existing == 1


def test_existing_contradiction_is_a_valid_noop_during_simulation() -> None:
    records = [source("1", drive_file_id=VALID_ID)]
    existing_records = [
        existing(
            "page-conflict",
            drive_file_id=VALID_ID,
            drive_url=f"https://drive.google.com/open?id={OTHER_ID}",
        )
    ]
    plan = build_reconciliation_plan(records, existing_records)
    assert plan.entries[0].result is ReconciliationResult.CONTRADICTORY_RECORD
    assert simulate_apply(plan, records, existing_records) == tuple(existing_records)
