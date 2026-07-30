"""Focused tests for identity resolution, normalization, and classification."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from visual_asset_sync.models import (
    ExistingAssetRecord,
    ReconciliationResult,
    SourceAssetRecord,
)
from visual_asset_sync.normalize import (
    MAX_SOURCE_ROW_LENGTH,
    extract_drive_id_candidates,
    extract_drive_id_from_url,
    is_valid_drive_file_id,
    normalize_existing_record,
    normalize_source_record,
)
from visual_asset_sync.reconcile import build_plan, resolve_identity

VALID_ID = "abc123def456ghi789jkl012m"
OTHER_ID = "zyx987wvu654tsr321qpo098n"
THIRD_ID = "third12345678901234567890"


def source(row: str, **kwargs) -> SourceAssetRecord:
    return SourceAssetRecord(source_row=row, **kwargs)


def existing(page_id: str, **kwargs) -> ExistingAssetRecord:
    return ExistingAssetRecord(page_id=page_id, **kwargs)


def test_exact_id_match_produces_update_existing() -> None:
    entries = build_plan(
        [source("1", drive_file_id=VALID_ID)],
        [existing("page-1", drive_file_id=VALID_ID)],
    )
    assert entries[0].result is ReconciliationResult.UPDATE_EXISTING
    assert entries[0].matched_page_ids == ("page-1",)


def test_url_fallback_matches_when_id_absent() -> None:
    entries = build_plan(
        [source("1", drive_url=f"https://drive.google.com/file/d/{VALID_ID}/view")],
        [existing("page-1", drive_file_id=VALID_ID)],
    )
    assert entries[0].result is ReconciliationResult.UPDATE_EXISTING
    assert entries[0].identity_key == VALID_ID


def test_filename_collision_with_different_ids_does_not_match() -> None:
    entries = build_plan(
        [source("1", drive_file_id=VALID_ID, file_name="icon.png")],
        [existing("page-1", drive_file_id=OTHER_ID, asset_title="icon.png")],
    )
    assert entries[0].result is ReconciliationResult.CREATE_MISSING


def test_filename_alone_never_establishes_identity() -> None:
    entries = build_plan(
        [source("1", file_name="icon.png")],
        [existing("page-1", asset_title="icon.png")],
    )
    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY


def test_missing_record_produces_create_missing() -> None:
    entries = build_plan([source("1", drive_file_id=VALID_ID)], [])
    assert entries[0].result is ReconciliationResult.CREATE_MISSING
    assert entries[0].matched_page_ids == ()


def test_duplicate_existing_ids_produce_duplicate_id_deterministically() -> None:
    entries = build_plan(
        [source("1", drive_file_id=VALID_ID)],
        [
            existing("page-z", drive_file_id=VALID_ID),
            existing("page-a", drive_file_id=VALID_ID),
        ],
    )
    assert entries[0].result is ReconciliationResult.DUPLICATE_ID
    assert entries[0].matched_page_ids == ("page-a", "page-z")


def test_duplicate_source_ids_produce_duplicate_id() -> None:
    entries = build_plan(
        [
            source("1", drive_file_id=VALID_ID),
            source("2", drive_file_id=VALID_ID),
        ],
        [],
    )
    assert [entry.result for entry in entries] == [
        ReconciliationResult.DUPLICATE_ID,
        ReconciliationResult.DUPLICATE_ID,
    ]


def test_missing_identity_produces_malformed_identity() -> None:
    entries = build_plan([source("1")], [])
    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY


def test_malformed_drive_url_without_id_produces_malformed_identity() -> None:
    key, result = resolve_identity(source("1", drive_url="not-a-drive-url"))
    assert key is None
    assert result is ReconciliationResult.MALFORMED_IDENTITY


def test_malformed_url_with_valid_explicit_id_uses_explicit_id() -> None:
    key, result = resolve_identity(
        source("1", drive_file_id=VALID_ID, drive_url="not-a-drive-url")
    )
    assert result is None
    assert key == VALID_ID


def test_id_and_url_contradiction_produces_contradictory_record() -> None:
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


def test_id_and_url_agreement_is_not_contradictory() -> None:
    entries = build_plan(
        [
            source(
                "1",
                drive_file_id=VALID_ID,
                drive_url=f"https://drive.google.com/open?id={VALID_ID}",
            )
        ],
        [],
    )
    assert entries[0].result is ReconciliationResult.CREATE_MISSING


def test_excluded_record_is_represented_not_dropped() -> None:
    entries = build_plan(
        [source("1", drive_file_id=VALID_ID, excluded=True)], []
    )
    assert len(entries) == 1
    assert entries[0].result is ReconciliationResult.EXCLUDED


def test_mixed_batch_classifies_each_record_independently() -> None:
    records = [
        source("1", drive_file_id=VALID_ID),
        source("2", drive_file_id=OTHER_ID),
        source("3"),
        source(
            "4",
            drive_file_id=VALID_ID,
            drive_url=f"https://drive.google.com/open?id={THIRD_ID}",
        ),
        source("5", excluded=True),
    ]
    existing_records = [existing("page-1", drive_file_id=VALID_ID)]
    assert [entry.result for entry in build_plan(records, existing_records)] == [
        ReconciliationResult.UPDATE_EXISTING,
        ReconciliationResult.CREATE_MISSING,
        ReconciliationResult.MALFORMED_IDENTITY,
        ReconciliationResult.CONTRADICTORY_RECORD,
        ReconciliationResult.EXCLUDED,
    ]


def test_preserves_unrelated_notion_fields_on_update() -> None:
    marker = object()
    entries = build_plan(
        [source("1", drive_file_id=VALID_ID)],
        [
            existing(
                "page-1",
                drive_file_id=VALID_ID,
                extra_fields={"Classroom Ready": True, "opaque": marker},
            )
        ],
    )
    assert entries[0].preserved_fields["Classroom Ready"] is True
    assert entries[0].preserved_fields["opaque"] is marker


def test_deterministic_output_ordering_matches_input_order() -> None:
    records = [source(str(row)) for row in range(5)]
    assert [entry.source_row for entry in build_plan(records, [])] == [
        "0",
        "1",
        "2",
        "3",
        "4",
    ]


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
        f"arbitrary text /d/{VALID_ID} embedded here",
        "not-a-drive-url",
    ],
)
def test_unsupported_hosts_schemes_and_text_yield_no_drive_id(url: str) -> None:
    assert extract_drive_id_candidates(url) == ()
    assert extract_drive_id_from_url(url) is None


def test_url_with_two_candidate_ids_is_ambiguous() -> None:
    url = f"https://drive.google.com/file/d/{VALID_ID}/view?id={OTHER_ID}"
    assert extract_drive_id_candidates(url) == (VALID_ID, OTHER_ID)
    assert extract_drive_id_from_url(url) is None


def test_ambiguous_url_only_record_produces_malformed_identity() -> None:
    entries = build_plan(
        [
            source(
                "1",
                drive_url=(
                    f"https://drive.google.com/file/d/{VALID_ID}/view?id={OTHER_ID}"
                ),
            )
        ],
        [],
    )
    assert entries[0].result is ReconciliationResult.MALFORMED_IDENTITY


def test_repeated_identical_id_in_url_is_not_ambiguous() -> None:
    url = f"https://drive.google.com/file/d/{VALID_ID}/view?id={VALID_ID}"
    assert extract_drive_id_candidates(url) == (VALID_ID,)
    assert extract_drive_id_from_url(url) == VALID_ID


def test_explicit_id_conflicting_with_any_ambiguous_url_candidate_is_contradictory() -> None:
    entries = build_plan(
        [
            source(
                "1",
                drive_file_id=VALID_ID,
                drive_url=(
                    f"https://drive.google.com/file/d/{VALID_ID}/view?id={OTHER_ID}"
                ),
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


def test_bounded_length_rule_accepts_known_drive_id_shapes() -> None:
    for length in (20, 25, 28, 33, 44, 128):
        assert is_valid_drive_file_id("a" * length) is True
    for length in (0, 1, 19, 129):
        assert is_valid_drive_file_id("a" * length) is False


class Explosive:
    def __str__(self) -> str:
        raise AssertionError("__str__ executed")

    def __repr__(self) -> str:
        raise AssertionError("__repr__ executed")

    def __bool__(self) -> bool:
        raise AssertionError("__bool__ executed")

    def __iter__(self):
        raise AssertionError("__iter__ executed")


class ExplosiveDict(dict):
    def get(self, *args, **kwargs):
        raise AssertionError("custom get executed")

    def items(self):
        raise AssertionError("custom items executed")


class ExplosiveMapping(Mapping):
    def __getitem__(self, key):
        raise AssertionError("custom mapping executed")

    def __iter__(self):
        raise AssertionError("custom mapping executed")

    def __len__(self):
        raise AssertionError("custom mapping executed")


class TextSubclass(str):
    pass


@pytest.mark.parametrize("raw", [ExplosiveDict(), ExplosiveMapping()])
def test_custom_mapping_inputs_are_rejected_before_mapping_behavior(raw) -> None:
    with pytest.raises(TypeError, match="exact dictionary"):
        normalize_source_record(raw)


@pytest.mark.parametrize("value", [Explosive(), TextSubclass("value"), 1, True])
def test_non_exact_text_values_are_rejected_without_coercion(value) -> None:
    with pytest.raises(TypeError, match="file_name must be an exact string or null"):
        normalize_source_record({"source_row": "1", "file_name": value})


@pytest.mark.parametrize("value", [0, 1, "false", "true", Explosive()])
def test_excluded_requires_an_exact_boolean(value) -> None:
    with pytest.raises(TypeError, match="excluded must be an exact boolean"):
        normalize_source_record({"source_row": "1", "excluded": value})


def test_source_row_requires_a_bounded_nonempty_exact_string() -> None:
    for value in (None, 1, TextSubclass("1"), Explosive()):
        with pytest.raises(TypeError, match="source_row must be an exact string"):
            normalize_source_record({"source_row": value})
    with pytest.raises(ValueError, match="source_row must not be empty"):
        normalize_source_record({"source_row": "   "})
    with pytest.raises(ValueError, match="source_row exceeds the length limit"):
        normalize_source_record({"source_row": "x" * (MAX_SOURCE_ROW_LENGTH + 1)})


def test_rejected_raw_value_is_not_echoed() -> None:
    raw_secret = TextSubclass("do-not-echo-this-value")
    with pytest.raises(TypeError) as exc_info:
        normalize_source_record({"source_row": "1", "file_name": raw_secret})
    assert "do-not-echo-this-value" not in str(exc_info.value)


def test_normal_source_dictionary_normalizes_without_coercion() -> None:
    record = normalize_source_record(
        {
            "source_row": " 12 ",
            "drive_file_id": f" {VALID_ID} ",
            "file_name": " icon.png ",
            "excluded": False,
        }
    )
    assert record.source_row == "12"
    assert record.drive_file_id == VALID_ID
    assert record.file_name == "icon.png"
    assert record.excluded is False


def test_existing_extra_fields_preserve_opaque_values_without_coercion() -> None:
    opaque = Explosive()
    record = normalize_existing_record(
        {"page_id": "page-1", "drive_file_id": VALID_ID, "opaque": opaque}
    )
    assert record.extra_fields["opaque"] is opaque


def test_existing_explicit_id_conflicting_with_url_blocks_explicit_side() -> None:
    entries = build_plan(
        [source("1", drive_file_id=VALID_ID)],
        [
            existing(
                "page-conflict",
                drive_file_id=VALID_ID,
                drive_url=f"https://drive.google.com/open?id={OTHER_ID}",
            )
        ],
    )
    assert entries[0].result is ReconciliationResult.CONTRADICTORY_RECORD
    assert entries[0].matched_page_ids == ("page-conflict",)


def test_existing_explicit_id_conflicting_with_url_blocks_url_side() -> None:
    entries = build_plan(
        [source("1", drive_file_id=OTHER_ID)],
        [
            existing(
                "page-conflict",
                drive_file_id=VALID_ID,
                drive_url=f"https://drive.google.com/open?id={OTHER_ID}",
            )
        ],
    )
    assert entries[0].result is ReconciliationResult.CONTRADICTORY_RECORD
    assert entries[0].matched_page_ids == ("page-conflict",)


def test_contradictory_existing_record_overrides_valid_match_and_sorts_pages() -> None:
    entries = build_plan(
        [source("1", drive_file_id=VALID_ID)],
        [
            existing("page-z", drive_file_id=VALID_ID),
            existing(
                "page-a",
                drive_file_id=VALID_ID,
                drive_url=f"https://drive.google.com/open?id={OTHER_ID}",
            ),
        ],
    )
    assert entries[0].result is ReconciliationResult.CONTRADICTORY_RECORD
    assert entries[0].matched_page_ids == ("page-a", "page-z")


def test_ambiguous_existing_url_blocks_each_candidate_identity() -> None:
    existing_records = [
        existing(
            "page-conflict",
            drive_url=(
                f"https://drive.google.com/file/d/{VALID_ID}/view?id={OTHER_ID}"
            ),
        )
    ]
    for candidate in (VALID_ID, OTHER_ID):
        entry = build_plan([source("1", drive_file_id=candidate)], existing_records)[0]
        assert entry.result is ReconciliationResult.CONTRADICTORY_RECORD
        assert entry.matched_page_ids == ("page-conflict",)


def test_malformed_existing_identity_does_not_create_false_match() -> None:
    entry = build_plan(
        [source("1", drive_file_id=VALID_ID)],
        [existing("page-bad", drive_file_id="abc")],
    )[0]
    assert entry.result is ReconciliationResult.CREATE_MISSING
    assert entry.matched_page_ids == ()
