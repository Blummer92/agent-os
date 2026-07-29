"""Focused tests for identity resolution and per-record classification."""

from visual_asset_sync.models import ExistingAssetRecord, ReconciliationResult, SourceAssetRecord
from visual_asset_sync.reconcile import build_plan, resolve_identity


def source(row: str, **kwargs) -> SourceAssetRecord:
    return SourceAssetRecord(source_row=row, **kwargs)


def existing(page_id: str, **kwargs) -> ExistingAssetRecord:
    return ExistingAssetRecord(page_id=page_id, **kwargs)


def test_exact_id_match_produces_update_existing() -> None:
    records = [source("1", drive_file_id="abc123def456ghi789jkl012m")]
    existing_records = [existing("page-1", drive_file_id="abc123def456ghi789jkl012m")]

    entries = build_plan(records, existing_records)

    assert entries[0].result is ReconciliationResult.UPDATE_EXISTING
    assert entries[0].matched_page_ids == ("page-1",)


def test_url_fallback_matches_when_id_absent() -> None:
    records = [
        source(
            "1",
            drive_url="https://drive.google.com/file/d/abc123def456ghi789jkl012m/view",
        )
    ]
    existing_records = [existing("page-1", drive_file_id="abc123def456ghi789jkl012m")]

    entries = build_plan(records, existing_records)

    assert entries[0].result is ReconciliationResult.UPDATE_EXISTING
    assert entries[0].identity_key == "abc123def456ghi789jkl012m"


def test_filename_collision_with_different_ids_does_not_match() -> None:
    records = [source("1", drive_file_id="idA123456789012345678901", file_name="icon.png")]
    existing_records = [existing("page-1", drive_file_id="idB123456789012345678901", asset_title="icon.png")]

    entries = build_plan(records, existing_records)

    assert entries[0].result is ReconciliationResult.CREATE_MISSING


def test_missing_record_produces_create_missing() -> None:
    records = [source("1", drive_file_id="idC123456789012345678901")]

    entries = build_plan(records, [])

    assert entries[0].result is ReconciliationResult.CREATE_MISSING
    assert entries[0].matched_page_ids == ()


def test_duplicate_existing_ids_produce_duplicate_id() -> None:
    records = [source("1", drive_file_id="dupID12345678901234567890")]
    existing_records = [
        existing("page-1", drive_file_id="dupID12345678901234567890"),
        existing("page-2", drive_file_id="dupID12345678901234567890"),
    ]

    entries = build_plan(records, existing_records)

    assert entries[0].result is ReconciliationResult.DUPLICATE_ID
    assert set(entries[0].matched_page_ids) == {"page-1", "page-2"}


def test_duplicate_source_ids_produce_duplicate_id() -> None:
    records = [
        source("1", drive_file_id="dupID12345678901234567890"),
        source("2", drive_file_id="dupID12345678901234567890"),
    ]

    entries = build_plan(records, [])

    assert entries[0].result is ReconciliationResult.DUPLICATE_ID
    assert entries[1].result is ReconciliationResult.DUPLICATE_ID


def test_missing_identity_produces_malformed_identity() -> None:
    records = [source("1")]

    entries = build_plan(records, [])

    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY


def test_malformed_drive_url_without_id_produces_malformed_identity() -> None:
    identity_key, forced_result = resolve_identity(source("1", drive_url="not-a-drive-url"))

    assert identity_key is None
    assert forced_result is ReconciliationResult.MALFORMED_IDENTITY


def test_malformed_url_with_id_present_falls_back_to_id() -> None:
    identity_key, forced_result = resolve_identity(
        source("1", drive_file_id="idD123456789012345678901", drive_url="not-a-drive-url")
    )

    assert forced_result is None
    assert identity_key == "idD123456789012345678901"


def test_id_and_url_contradiction_produces_contradictory_record() -> None:
    records = [
        source(
            "1",
            drive_file_id="idEEEE123456789012345678901",
            drive_url="https://drive.google.com/file/d/idFFFF123456789012345678901/view",
        )
    ]

    entries = build_plan(records, [])

    assert entries[0].result is ReconciliationResult.CONTRADICTORY_RECORD


def test_id_and_url_agreement_is_not_contradictory() -> None:
    records = [
        source(
            "1",
            drive_file_id="idGGGG123456789012345678901",
            drive_url="https://drive.google.com/file/d/idGGGG123456789012345678901/view",
        )
    ]

    entries = build_plan(records, [])

    assert entries[0].result is ReconciliationResult.CREATE_MISSING


def test_excluded_record_is_represented_not_dropped() -> None:
    records = [source("1", drive_file_id="idH123456789012345678901", excluded=True)]

    entries = build_plan(records, [])

    assert len(entries) == 1
    assert entries[0].result is ReconciliationResult.EXCLUDED
    assert entries[0].source_row == "1"


def test_mixed_batch_classifies_each_record_independently() -> None:
    records = [
        source("1", drive_file_id="matchID1234567890123456789"),
        source("2", drive_file_id="createID123456789012345678"),
        source("3"),
        source(
            "4",
            drive_file_id="contraA12345678901234567890",
            drive_url="https://drive.google.com/file/d/contraB12345678901234567890/view",
        ),
        source("5", excluded=True),
    ]
    existing_records = [existing("page-1", drive_file_id="matchID1234567890123456789")]

    entries = build_plan(records, existing_records)
    results = [entry.result for entry in entries]

    assert results == [
        ReconciliationResult.UPDATE_EXISTING,
        ReconciliationResult.CREATE_MISSING,
        ReconciliationResult.MALFORMED_IDENTITY,
        ReconciliationResult.CONTRADICTORY_RECORD,
        ReconciliationResult.EXCLUDED,
    ]


def test_preserves_unrelated_notion_fields_on_update() -> None:
    records = [source("1", drive_file_id="idI123456789012345678901")]
    existing_records = [
        existing(
            "page-1",
            drive_file_id="idI123456789012345678901",
            extra_fields={"Classroom Ready": True, "Slideshow Order": 4},
        )
    ]

    entries = build_plan(records, existing_records)

    assert entries[0].preserved_fields == {"Classroom Ready": True, "Slideshow Order": 4}


def test_deterministic_output_ordering_matches_input_order() -> None:
    records = [source(str(row)) for row in range(5)]

    entries = build_plan(records, [])

    assert [entry.source_row for entry in entries] == ["0", "1", "2", "3", "4"]
