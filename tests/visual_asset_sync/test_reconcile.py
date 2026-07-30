"""Focused tests for identity resolution and per-record classification."""

import pytest

from visual_asset_sync.models import ExistingAssetRecord, ReconciliationResult, SourceAssetRecord
from visual_asset_sync.normalize import (
    extract_drive_id_candidates,
    extract_drive_id_from_url,
    is_valid_drive_file_id,
)
from visual_asset_sync.reconcile import build_plan, resolve_identity

VALID_ID = "abc123def456ghi789jkl012m"
OTHER_ID = "zyx987wvu654tsr321qpo098n"


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


# --- Host validation: only supported Google hosts establish Drive identity ---


@pytest.mark.parametrize(
    "url",
    [
        f"https://drive.google.com/file/d/{VALID_ID}/view",
        f"https://drive.google.com/open?id={VALID_ID}",
        f"https://docs.google.com/document/d/{VALID_ID}/edit",
        f"http://DRIVE.GOOGLE.COM/file/d/{VALID_ID}/view",
        f"https://drive.google.com:443/file/d/{VALID_ID}/view",
    ],
)
def test_supported_google_urls_yield_the_drive_id(url: str) -> None:
    assert extract_drive_id_from_url(url) == VALID_ID


@pytest.mark.parametrize(
    "url",
    [
        f"https://example.com/file/d/{VALID_ID}/view",
        f"https://malicious.example/?id={VALID_ID}",
        f"https://drive.google.com.evil.example/file/d/{VALID_ID}/view",
        f"https://notdrive.google.com/file/d/{VALID_ID}/view",
        f"https://evil.example/?redirect=https://drive.google.com/file/d/{VALID_ID}/view",
        f"ftp://drive.google.com/file/d/{VALID_ID}/view",
        "not-a-drive-url",
    ],
)
def test_unsupported_hosts_and_schemes_yield_no_drive_id(url: str) -> None:
    assert extract_drive_id_candidates(url) == ()
    assert extract_drive_id_from_url(url) is None


def test_non_google_path_match_produces_malformed_identity() -> None:
    records = [source("1", drive_url=f"https://example.com/file/d/{VALID_ID}/view")]

    entries = build_plan(records, [existing("page-1", drive_file_id=VALID_ID)])

    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY
    assert entries[0].identity_key is None


def test_non_google_id_query_produces_malformed_identity() -> None:
    records = [source("1", drive_url=f"https://malicious.example/?id={VALID_ID}")]

    entries = build_plan(records, [existing("page-1", drive_file_id=VALID_ID)])

    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY
    assert entries[0].identity_key is None


def test_existing_record_url_on_non_google_host_is_not_indexed() -> None:
    records = [source("1", drive_file_id=VALID_ID)]
    existing_records = [
        existing("page-1", drive_url=f"https://example.com/file/d/{VALID_ID}/view")
    ]

    entries = build_plan(records, existing_records)

    assert entries[0].result is ReconciliationResult.CREATE_MISSING


# --- Ambiguous URL identity is never resolved to the first candidate ---


def test_url_with_two_candidate_ids_is_ambiguous() -> None:
    url = f"https://drive.google.com/file/d/{VALID_ID}/view?id={OTHER_ID}"

    assert extract_drive_id_candidates(url) == (VALID_ID, OTHER_ID)
    assert extract_drive_id_from_url(url) is None


def test_ambiguous_url_only_record_produces_malformed_identity() -> None:
    records = [
        source("1", drive_url=f"https://drive.google.com/file/d/{VALID_ID}/view?id={OTHER_ID}")
    ]

    entries = build_plan(records, [existing("page-1", drive_file_id=VALID_ID)])

    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY
    assert entries[0].identity_key is None


def test_repeated_identical_id_in_url_is_not_ambiguous() -> None:
    url = f"https://drive.google.com/file/d/{VALID_ID}/view?id={VALID_ID}"

    assert extract_drive_id_candidates(url) == (VALID_ID,)
    assert extract_drive_id_from_url(url) == VALID_ID


# --- Explicit ID precedence, contradiction, and format validation ---


def test_explicit_id_matching_url_id_resolves_to_the_explicit_id() -> None:
    identity_key, forced_result = resolve_identity(
        source(
            "1",
            drive_file_id=VALID_ID,
            drive_url=f"https://drive.google.com/open?id={VALID_ID}",
        )
    )

    assert forced_result is None
    assert identity_key == VALID_ID


def test_explicit_id_conflicting_with_url_id_produces_contradictory_record() -> None:
    entries = build_plan(
        [
            source(
                "1",
                drive_file_id=VALID_ID,
                drive_url=f"https://drive.google.com/open?id={OTHER_ID}",
            )
        ],
        [],
    )

    assert entries[0].result is ReconciliationResult.CONTRADICTORY_RECORD


def test_explicit_id_conflicting_with_ambiguous_url_evidence_is_contradictory() -> None:
    """One matching candidate does not excuse a second, conflicting candidate."""
    entries = build_plan(
        [
            source(
                "1",
                drive_file_id=VALID_ID,
                drive_url=f"https://drive.google.com/file/d/{VALID_ID}/view?id={OTHER_ID}",
            )
        ],
        [],
    )

    assert entries[0].result is ReconciliationResult.CONTRADICTORY_RECORD


@pytest.mark.parametrize(
    "candidate",
    [
        "abc",
        "too-short-id",
        "has spaces in it and is long enough",
        "invalid/slash/characters/in/the/id/value",
        "id!!!with!!!punctuation!!!not!!!allowed",
        "x" * 129,
    ],
)
def test_malformed_explicit_ids_are_rejected(candidate: str) -> None:
    assert is_valid_drive_file_id(candidate) is False

    entries = build_plan([source("1", drive_file_id=candidate)], [])

    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY
    assert entries[0].identity_key is None


def test_malformed_explicit_id_is_not_matched_against_existing_records() -> None:
    records = [source("1", drive_file_id="abc")]
    existing_records = [existing("page-1", drive_file_id="abc")]

    entries = build_plan(records, existing_records)

    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY
    assert entries[0].matched_page_ids == ()


def test_bounded_length_rule_accepts_known_drive_id_shapes() -> None:
    for length in (20, 25, 28, 33, 44, 128):
        assert is_valid_drive_file_id("a" * length) is True
    for length in (0, 1, 19, 129):
        assert is_valid_drive_file_id("a" * length) is False
