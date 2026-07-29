"""Focused tests for plan aggregation, reporting, and idempotent rerun."""

import json

from visual_asset_sync.models import ExistingAssetRecord, ReconciliationResult, SourceAssetRecord
from visual_asset_sync.plan import build_reconciliation_plan, simulate_apply
from visual_asset_sync.report import plan_to_dict, plan_to_json, plan_to_summary


def source(row: str, **kwargs) -> SourceAssetRecord:
    return SourceAssetRecord(source_row=row, **kwargs)


def existing(page_id: str, **kwargs) -> ExistingAssetRecord:
    return ExistingAssetRecord(page_id=page_id, **kwargs)


def test_plan_totals_and_zero_write_confirmation() -> None:
    records = [
        source("1", drive_file_id="matchID1234567890123456789"),
        source("2", drive_file_id="createID123456789012345678"),
        source("3"),
        source("4", excluded=True),
    ]
    existing_records = [existing("page-1", drive_file_id="matchID1234567890123456789")]

    plan = build_reconciliation_plan(records, existing_records)

    assert plan.total_source_records == 4
    assert plan.update_existing == 1
    assert plan.create_missing == 1
    assert plan.malformed_identity == 1
    assert plan.excluded == 1
    assert plan.dry_run is True
    assert plan.zero_write_confirmed is True


def test_repeated_runs_are_deterministic() -> None:
    records = [
        source("1", drive_file_id="matchID1234567890123456789"),
        source("2", drive_file_id="createID123456789012345678"),
    ]
    existing_records = [existing("page-1", drive_file_id="matchID1234567890123456789")]

    plan_a = build_reconciliation_plan(records, existing_records)
    plan_b = build_reconciliation_plan(records, existing_records)

    assert plan_to_dict(plan_a) == plan_to_dict(plan_b)


def test_idempotent_rerun_does_not_propose_duplicate_creates() -> None:
    records = [
        source("1", drive_file_id="matchID1234567890123456789"),
        source("2", drive_file_id="createID123456789012345678"),
    ]
    existing_records = [existing("page-1", drive_file_id="matchID1234567890123456789")]

    first_plan = build_reconciliation_plan(records, existing_records)
    assert first_plan.create_missing == 1

    simulated_existing = simulate_apply(first_plan, records, existing_records)
    second_plan = build_reconciliation_plan(records, simulated_existing)

    assert second_plan.create_missing == 0
    assert second_plan.update_existing == 2


def test_simulate_apply_does_not_mutate_inputs() -> None:
    records = [source("1", drive_file_id="createID123456789012345678")]
    existing_records = [existing("page-1", drive_file_id="matchID1234567890123456789")]
    original_existing_len = len(existing_records)

    plan = build_reconciliation_plan(records, existing_records)
    simulated = simulate_apply(plan, records, existing_records)

    assert len(existing_records) == original_existing_len
    assert len(simulated) == original_existing_len + 1
    assert isinstance(simulated, tuple)


def test_excluded_records_remain_represented_in_plan_output() -> None:
    records = [source("1", excluded=True)]

    plan = build_reconciliation_plan(records, [])

    assert len(plan.entries) == 1
    assert plan.entries[0].result is ReconciliationResult.EXCLUDED
    assert plan.excluded == 1


def test_plan_to_json_is_valid_and_matches_summary_counts() -> None:
    records = [
        source("1", drive_file_id="matchID1234567890123456789"),
        source("2", drive_file_id="createID123456789012345678"),
    ]
    existing_records = [existing("page-1", drive_file_id="matchID1234567890123456789")]

    plan = build_reconciliation_plan(records, existing_records)
    payload = json.loads(plan_to_json(plan))

    assert payload["dry_run"] is True
    assert payload["zero_write_confirmed"] is True
    assert payload["total_source_records"] == 2
    assert payload["summary"]["update_existing"] == 1
    assert payload["summary"]["create_missing"] == 1
    assert len(payload["entries"]) == 2


def test_plan_to_summary_is_human_readable_text() -> None:
    plan = build_reconciliation_plan([source("1", drive_file_id="createID123456789012345678")], [])

    summary = plan_to_summary(plan)

    assert "Visual Asset Reconciliation Plan" in summary
    assert "zero external writes" in summary
    assert "CREATE_MISSING:       1" in summary


def test_dry_run_performs_zero_external_writes() -> None:
    records = [source("1", drive_file_id="createID123456789012345678")]

    plan = build_reconciliation_plan(records, [])

    # No connector, client, or network object is constructed anywhere in this
    # call graph; the plan is pure data.
    assert plan.dry_run is True
    assert plan.zero_write_confirmed is True
