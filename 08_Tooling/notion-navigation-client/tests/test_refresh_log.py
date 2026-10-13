import ast
import copy
import json
from pathlib import Path

import pytest

from notion_navigation_client import refresh_log
from notion_navigation_client.index import NavigationIndex
from notion_navigation_client.records import NAVIGATION_WARNING
from notion_navigation_client.refresh_log import (
    COMPLETENESS_NOTICE,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    build_refresh_log_evidence,
    classify_timestamp,
    validate_limit,
)

PACKAGE_DIR = Path(__file__).parent.parent / "src" / "notion_navigation_client"
SAMPLE_TABS = json.loads((Path(__file__).parent.parent / "samples" / "sample_tabs.json").read_text())

LIVE_HEADER = [
    "Refresh Date",
    "Script Version",
    "Refreshed By",
    "Data Sources Scanned",
    "Dashboards Scanned",
    "Properties Scanned",
    "Relations Found",
    "Errors",
    "Unresolved Questions",
    "Notes",
]


def log_row(refresh_date, notes="note", errors="", unresolved=""):
    return [refresh_date, "v0.1.2", "Operator A", "1", "2", "3", "4", errors, unresolved, notes]


def tab(*data_rows, banner=True):
    rows = [[NAVIGATION_WARNING]] if banner else []
    return rows + [list(LIVE_HEADER)] + [list(row) for row in data_rows]


# --- timestamp classification ------------------------------------------------


@pytest.mark.parametrize(
    "raw, status, utc",
    [
        ("2026-07-04 16:04 UTC", "explicit-utc", "2026-07-04T16:04:00Z"),
        ("2026-07-04 16:04:09 utc", "explicit-utc", "2026-07-04T16:04:09Z"),
        ("2026-08-09T16:37:20Z", "explicit-utc", "2026-08-09T16:37:20Z"),
        ("2026-08-09T16:37:20.339Z", "explicit-utc", "2026-08-09T16:37:20.339000Z"),
        ("2026-08-09 16:10:03+02:00", "explicit-offset", "2026-08-09T14:10:03Z"),
        ("2026-08-09 16:10:03 -0500", "explicit-offset", "2026-08-09T21:10:03Z"),
        ("2026-08-09 23:30+00:00", "explicit-offset", "2026-08-09T23:30:00Z"),
        ("2026-08-09 23:30-12:00", "explicit-offset", "2026-08-10T11:30:00Z"),
        ("2026-08-09 23:30+14:00", "explicit-offset", "2026-08-09T09:30:00Z"),
    ],
)
def test_explicit_zone_evidence_resolves_to_utc(raw, status, utc):
    result = classify_timestamp(raw)
    assert result == {"raw": raw, "status": status, "utc": utc}


@pytest.mark.parametrize(
    "raw",
    [
        "2026-08-09 16:10:03.654",
        "2026-08-09 16:10",
        "2026-08-09T16:10:03",
    ],
)
def test_timestamp_without_zone_evidence_is_ambiguous_and_never_guessed(raw):
    result = classify_timestamp(raw)
    assert result == {"raw": raw, "status": "ambiguous-timezone", "utc": None}


@pytest.mark.parametrize(
    "raw",
    [
        "2026-08-09",  # a day, not an instant
        "2026-08-09 UTC",
        "8/9/2026 16:10",  # locale-dependent order
        "09/08/2026 16:10:03",
        "Aug 9, 2026 4:10 PM",
        "2026-08-09 16:10 PST",  # abbreviations are not unambiguous zones
        "2026-08-09 16:10 CST",
        "2026-13-09 16:10 UTC",  # impossible calendar values
        "2026-02-30 16:10 UTC",
        "2026-08-09 24:00 UTC",
        "2026-08-09 16:10+15:00",  # no real zone is this far from UTC
        "2026-08-09 16:10+02:75",
        "yesterday",
    ],
)
def test_unrecognized_formats_stay_raw_and_unresolved(raw):
    result = classify_timestamp(raw)
    assert result == {"raw": raw, "status": "unrecognized-format", "utc": None}


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_timestamp_is_missing(raw):
    result = classify_timestamp(raw)
    assert result["status"] == "missing"
    assert result["utc"] is None
    assert result["raw"] == ("" if raw is None else raw)


def test_raw_timestamp_is_preserved_byte_for_byte_including_whitespace():
    raw = "  2026-07-04 16:04 UTC \t"
    result = classify_timestamp(raw)
    assert result["raw"] == raw
    assert result["status"] == "explicit-utc"


# --- layout parsing from the live warning-row + header-row shape ------------


def test_fixture_parses_live_warning_row_plus_header_row_layout():
    index = NavigationIndex(lambda tab_name: SAMPLE_TABS[tab_name])
    result = index.get_refresh_log()

    assert [entry["source_row"] for entry in result["entries"]] == [3, 4, 5]
    assert list(result["entries"][0]["record"]) == LIVE_HEADER
    assert [entry["record"]["Refresh Date"] for entry in result["entries"]] == [
        "2026-07-04 16:04 UTC",
        "2026-08-09 16:10:03.654",
        "2026-08-09 16:37:20.339",
    ]
    assert result["total_populated_rows"] == 3
    assert result["truncated"] is False
    assert result["timestamp_column_present"] is True


def test_direct_header_layout_without_banner_numbers_rows_from_two():
    rows = tab(log_row("2026-07-04 16:04 UTC"), log_row("2026-07-05 09:00 UTC"), banner=False)
    result = build_refresh_log_evidence(rows)
    assert [entry["source_row"] for entry in result["entries"]] == [2, 3]


def test_blank_interior_rows_are_skipped_but_keep_sheet_row_numbers():
    rows = tab(log_row("2026-07-04 16:04 UTC"), [], ["", "  "], log_row("2026-07-05 09:00 UTC"))
    result = build_refresh_log_evidence(rows)
    assert [entry["source_row"] for entry in result["entries"]] == [3, 6]
    assert result["total_populated_rows"] == 2


def test_short_rows_are_padded_like_every_other_tab():
    rows = tab(["2026-07-04 16:04 UTC", "v0.1.0"])
    entry = build_refresh_log_evidence(rows)["entries"][0]
    assert entry["record"]["Notes"] == ""
    assert entry["record"]["Script Version"] == "v0.1.0"


# --- bounded history ----------------------------------------------------------


def test_default_limit_is_applied():
    rows = tab(*[log_row(f"2026-07-{day:02d} 10:00 UTC") for day in range(1, 29)])
    result = build_refresh_log_evidence(rows)
    assert result["limit"] == DEFAULT_LIMIT == 20
    assert result["returned_rows"] == 20
    assert result["total_populated_rows"] == 28
    assert result["truncated"] is True


def test_limit_returns_the_last_rows_in_ascending_source_order():
    rows = tab(*[log_row(f"2026-07-{day:02d} 10:00 UTC", notes=f"n{day}") for day in range(1, 11)])
    result = build_refresh_log_evidence(rows, limit=3)
    assert [entry["record"]["Notes"] for entry in result["entries"]] == ["n8", "n9", "n10"]
    assert [entry["source_row"] for entry in result["entries"]] == [10, 11, 12]
    assert result["returned_rows"] == 3
    assert result["truncated"] is True
    assert result["window"] == "last-populated-source-rows"


def test_limit_larger_than_the_log_returns_everything_untruncated():
    result = build_refresh_log_evidence(tab(log_row("2026-07-04 16:04 UTC")), limit=50)
    assert result["returned_rows"] == 1
    assert result["truncated"] is False


def test_bound_applies_to_returned_entries_not_to_summary_evidence():
    # The oldest row is the only one with an unresolved timestamp; it is outside
    # a limit=1 window but must still count in the summary and block by_timestamp.
    rows = tab(
        log_row("2026-07-01 10:00"),
        log_row("2026-07-02 10:00 UTC"),
        log_row("2026-07-03 10:00 UTC"),
    )
    result = build_refresh_log_evidence(rows, limit=1)
    assert [entry["source_row"] for entry in result["entries"]] == [5]
    assert result["timestamp_status_counts"]["ambiguous-timezone"] == 1
    assert result["timestamp_status_counts"]["explicit-utc"] == 2
    latest = result["latest_observed_refresh"]
    assert latest["by_source_row"]["source_row"] == 5
    assert latest["by_timestamp"] is None
    assert latest["by_timestamp_unavailable_reason"] == "timestamps-not-all-explicit"


def test_large_log_stays_bounded_at_the_maximum():
    rows = tab(*[log_row(f"2026-01-01 00:{i % 60:02d} UTC", notes=str(i)) for i in range(1500)])
    result = build_refresh_log_evidence(rows, limit=MAX_LIMIT)
    assert result["returned_rows"] == MAX_LIMIT == 200
    assert result["total_populated_rows"] == 1500
    assert result["entries"][-1]["record"]["Notes"] == "1499"


@pytest.mark.parametrize("limit", [0, -1, MAX_LIMIT + 1, True, False, 2.0, "5", None])
def test_invalid_limit_is_rejected(limit):
    with pytest.raises(ValueError, match="limit must be an integer between 1 and 200"):
        build_refresh_log_evidence(tab(log_row("2026-07-04 16:04 UTC")), limit=limit)
    with pytest.raises(ValueError):
        validate_limit(limit)


@pytest.mark.parametrize("limit", [1, DEFAULT_LIMIT, MAX_LIMIT])
def test_valid_limits_are_accepted(limit):
    assert validate_limit(limit) == limit


# --- latest-refresh projection -------------------------------------------------


def test_latest_by_source_row_is_always_the_last_populated_row():
    index = NavigationIndex(lambda tab_name: SAMPLE_TABS[tab_name])
    latest = index.get_refresh_log()["latest_observed_refresh"]
    assert latest["by_source_row"]["source_row"] == 5
    assert latest["by_source_row"]["timestamp"]["raw"] == "2026-08-09 16:37:20.339"


def test_mixed_timestamp_evidence_withholds_timestamp_based_latest():
    # The shape of the current live tab: one explicit-UTC row, later rows with no zone.
    index = NavigationIndex(lambda tab_name: SAMPLE_TABS[tab_name])
    result = index.get_refresh_log()
    latest = result["latest_observed_refresh"]
    assert latest["by_timestamp"] is None
    assert latest["by_timestamp_unavailable_reason"] == "timestamps-not-all-explicit"
    assert latest["agree"] is None
    assert result["source_order_matches_timestamp_order"] is None
    assert result["timestamp_status_counts"] == {
        "explicit-utc": 1,
        "explicit-offset": 0,
        "ambiguous-timezone": 2,
        "unrecognized-format": 0,
        "missing": 0,
    }


def test_all_explicit_append_ordered_log_resolves_latest_by_timestamp():
    rows = tab(
        log_row("2026-07-04 16:04 UTC"),
        log_row("2026-07-05 09:00 UTC"),
        log_row("2026-07-06T10:30:00Z"),
    )
    result = build_refresh_log_evidence(rows)
    latest = result["latest_observed_refresh"]
    assert latest["by_timestamp"]["source_row"] == 5
    assert latest["by_timestamp"]["timestamp"]["utc"] == "2026-07-06T10:30:00Z"
    assert latest["by_timestamp_unavailable_reason"] is None
    assert latest["agree"] is True
    assert result["source_order_matches_timestamp_order"] is True


def test_newest_first_sheet_is_not_mistaken_for_append_order():
    rows = tab(
        log_row("2026-07-06 10:30 UTC", notes="newest"),
        log_row("2026-07-05 09:00 UTC", notes="middle"),
        log_row("2026-07-04 16:04 UTC", notes="oldest"),
    )
    result = build_refresh_log_evidence(rows)
    latest = result["latest_observed_refresh"]
    assert latest["by_source_row"]["record"]["Notes"] == "oldest"
    assert latest["by_timestamp"]["record"]["Notes"] == "newest"
    assert latest["agree"] is False
    assert result["source_order_matches_timestamp_order"] is False
    # Entries are still returned in sheet order, not re-sorted.
    assert [entry["record"]["Notes"] for entry in result["entries"]] == ["newest", "middle", "oldest"]


def test_instants_are_compared_in_utc_not_by_raw_text():
    rows = tab(
        log_row("2026-08-10 01:00 UTC", notes="01:00Z"),
        log_row("2026-08-09 23:00-05:00", notes="04:00Z next day"),
    )
    result = build_refresh_log_evidence(rows)
    latest = result["latest_observed_refresh"]
    assert latest["by_timestamp"]["record"]["Notes"] == "04:00Z next day"
    assert latest["by_timestamp"]["timestamp"]["utc"] == "2026-08-10T04:00:00Z"
    assert result["source_order_matches_timestamp_order"] is True


def test_equal_instants_resolve_to_the_later_source_row():
    rows = tab(
        log_row("2026-08-10 04:00 UTC", notes="first"),
        log_row("2026-08-09 23:00-05:00", notes="second"),
    )
    latest = build_refresh_log_evidence(rows)["latest_observed_refresh"]
    assert latest["by_timestamp"]["record"]["Notes"] == "second"
    assert latest["agree"] is True


def test_single_explicit_row_is_trivially_ordered():
    result = build_refresh_log_evidence(tab(log_row("2026-07-04 16:04 UTC")))
    assert result["source_order_matches_timestamp_order"] is True
    assert result["latest_observed_refresh"]["agree"] is True


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [[NAVIGATION_WARNING]],
        tab(),
        tab([], ["", ""]),
    ],
)
def test_empty_log_returns_an_envelope_with_no_latest(rows):
    result = build_refresh_log_evidence(rows)
    assert result["entries"] == []
    assert result["total_populated_rows"] == 0
    assert result["returned_rows"] == 0
    assert result["truncated"] is False
    latest = result["latest_observed_refresh"]
    assert latest["by_source_row"] is None
    assert latest["by_timestamp"] is None
    assert latest["by_timestamp_unavailable_reason"] == "no-entries"
    assert latest["agree"] is None
    assert result["source_order_matches_timestamp_order"] is None
    assert result["navigation_warning"] == NAVIGATION_WARNING


def test_missing_timestamp_column_is_reported_not_papered_over():
    header = [name for name in LIVE_HEADER if name != "Refresh Date"]
    rows = [[NAVIGATION_WARNING], header, ["v0.1.2", "Operator A", "1", "2", "3", "4", "", "", "n"]]
    result = build_refresh_log_evidence(rows)
    assert result["timestamp_column_present"] is False
    assert result["timestamp_status_counts"]["missing"] == 1
    latest = result["latest_observed_refresh"]
    assert latest["by_source_row"]["source_row"] == 3
    assert latest["by_timestamp"] is None
    assert latest["by_timestamp_unavailable_reason"] == "timestamp-column-missing"


def test_unrecognized_and_missing_timestamps_also_withhold_timestamp_based_latest():
    for bad in ("8/9/2026 16:10", ""):
        rows = tab(log_row("2026-07-04 16:04 UTC"), log_row(bad))
        latest = build_refresh_log_evidence(rows)["latest_observed_refresh"]
        assert latest["by_timestamp"] is None
        assert latest["by_timestamp_unavailable_reason"] == "timestamps-not-all-explicit"
        assert latest["by_source_row"]["timestamp"]["raw"] == bad


# --- raw preservation, determinism, isolation ---------------------------------


def test_raw_cells_are_preserved_untouched_in_the_record():
    notes = "Mixed  spacing,\tunicode é — and a trailing space "
    rows = tab(log_row("2026-08-09 16:10:03.654", notes=notes, errors="E1; E2", unresolved="Open question?"))
    entry = build_refresh_log_evidence(rows)["entries"][0]
    assert entry["record"]["Notes"] == notes
    assert entry["record"]["Errors"] == "E1; E2"
    assert entry["record"]["Unresolved Questions"] == "Open question?"
    assert entry["record"]["Refresh Date"] == "2026-08-09 16:10:03.654"
    assert entry["timestamp"]["raw"] == "2026-08-09 16:10:03.654"
    assert entry["timestamp"]["status"] == "ambiguous-timezone"
    assert entry["timestamp"]["utc"] is None


def test_ordering_is_sheet_order_and_repeated_reads_are_identical():
    rows = tab(
        log_row("2026-07-09 10:00 UTC", notes="a"),
        log_row("2026-07-01 10:00 UTC", notes="b"),
        log_row("2026-07-05 10:00 UTC", notes="c"),
    )
    first = build_refresh_log_evidence(rows)
    second = build_refresh_log_evidence(rows)
    assert first == second
    assert [entry["record"]["Notes"] for entry in first["entries"]] == ["a", "b", "c"]
    assert first["ordering"] == "source-row"


def test_input_rows_are_not_modified():
    rows = tab(log_row("2026-07-04 16:04 UTC"), [], log_row("2026-08-09 16:10"))
    before = copy.deepcopy(rows)
    build_refresh_log_evidence(rows, limit=1)
    assert rows == before


def test_mutating_a_result_does_not_leak_into_later_reads():
    index = NavigationIndex(lambda tab_name: SAMPLE_TABS[tab_name])
    first = index.get_refresh_log()
    expected = copy.deepcopy(first)
    first["entries"][0]["record"]["Notes"] = "tampered"
    first["entries"][-1]["timestamp"]["raw"] = "tampered"
    first["latest_observed_refresh"]["by_source_row"]["record"]["Notes"] = "tampered"
    first["entries"].clear()
    assert index.get_refresh_log() == expected


def test_entries_do_not_alias_the_latest_projection():
    result = build_refresh_log_evidence(tab(log_row("2026-07-04 16:04 UTC")))
    result["entries"][0]["record"]["Notes"] = "tampered"
    assert result["latest_observed_refresh"]["by_source_row"]["record"]["Notes"] == "note"


# --- navigation warning and non-authority boundary -----------------------------


def test_every_result_level_carries_the_navigation_warning():
    index = NavigationIndex(lambda tab_name: SAMPLE_TABS[tab_name])
    result = index.get_refresh_log()
    assert result["navigation_warning"] == NAVIGATION_WARNING
    assert result["entries"]
    for entry in result["entries"]:
        assert entry["navigation_warning"] == NAVIGATION_WARNING
    latest = result["latest_observed_refresh"]["by_source_row"]
    assert latest["navigation_warning"] == NAVIGATION_WARNING


def test_result_states_it_is_not_a_complete_work_history():
    result = build_refresh_log_evidence(tab(log_row("2026-07-04 16:04 UTC")))
    assert result["completeness_notice"] == COMPLETENESS_NOTICE
    assert "not a complete history" in COMPLETENESS_NOTICE
    assert "live Notion or GitHub verification" in COMPLETENESS_NOTICE
    assert result["tab"] == "Refresh Log"


def test_a_record_cannot_collide_with_evidence_fields():
    header = ["Refresh Date", "source_row", "timestamp", "navigation_warning"]
    rows = [[NAVIGATION_WARNING], header, ["2026-07-04 16:04 UTC", "sheet-says-9", "sheet-ts", "sheet-warning"]]
    entry = build_refresh_log_evidence(rows)["entries"][0]
    assert entry["source_row"] == 3
    assert entry["timestamp"]["status"] == "explicit-utc"
    assert entry["navigation_warning"] == NAVIGATION_WARNING
    assert entry["record"]["source_row"] == "sheet-says-9"
    assert entry["record"]["navigation_warning"] == "sheet-warning"


def test_result_is_json_serializable():
    index = NavigationIndex(lambda tab_name: SAMPLE_TABS[tab_name])
    assert json.loads(json.dumps(index.get_refresh_log()))["total_populated_rows"] == 3


# --- caching: one fetch, no second store -----------------------------------------


def test_refresh_log_is_fetched_once_per_session_across_reads():
    calls = []

    def fetch(tab_name):
        calls.append(tab_name)
        return SAMPLE_TABS[tab_name]

    index = NavigationIndex(fetch)
    index.get_refresh_log()
    index.get_refresh_log(limit=1)
    index.get_refresh_log(limit=2)
    assert calls == ["Refresh Log"]


def test_refresh_log_and_keyed_lookups_cache_independently():
    calls = []

    def fetch(tab_name):
        calls.append(tab_name)
        return SAMPLE_TABS[tab_name]

    index = NavigationIndex(fetch)
    index.get_dashboard("Curriculum Source Control")
    index.get_refresh_log()
    index.get_dashboard("Curriculum Source Control")
    index.get_refresh_log()
    assert calls == ["Dashboard Registry", "Refresh Log"]


def test_invalid_limit_does_not_fetch_before_failing_validation_is_still_cheap():
    # Validation happens on the pure function; the fetch is the only I/O and is
    # cached, so a rejected limit never causes a second read.
    calls = []

    def fetch(tab_name):
        calls.append(tab_name)
        return SAMPLE_TABS[tab_name]

    index = NavigationIndex(fetch)
    with pytest.raises(ValueError):
        index.get_refresh_log(limit=0)
    index.get_refresh_log()
    assert calls == ["Refresh Log"]


# --- read-only surface ---------------------------------------------------------


def test_refresh_log_module_is_pure_and_imports_no_io_or_network():
    tree = ast.parse((PACKAGE_DIR / "refresh_log.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
    assert imported <= {"__future__", "re", "datetime", ".records"}


SHEETS_WRITE_ATTRS = {
    "batchUpdate",
    "batchClear",
    "batchUpdateByDataFilter",
    "batchClearByDataFilter",
    "copyTo",
    "developerMetadata",
}
VALUES_WRITE_ATTRS = {"update", "append", "clear"}


def sheet_write_references(source):
    """Return Sheets write-API references in executable code (docstrings/prose ignored)."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            if node.attr in SHEETS_WRITE_ATTRS:
                hits.append(node.attr)
            chained_on_values = (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "values"
            )
            if node.attr in VALUES_WRITE_ATTRS and chained_on_values:
                hits.append(f"values().{node.attr}")
        elif isinstance(node, ast.Constant) and node.value in SHEETS_WRITE_ATTRS:
            hits.append(node.value)
    return hits


def test_write_detector_flags_known_sheet_write_chains():
    assert sheet_write_references("service.spreadsheets().values().update(a=1)") == ["values().update"]
    assert sheet_write_references("service.spreadsheets().values().append(a=1)") == ["values().append"]
    assert sheet_write_references("service.spreadsheets().batchUpdate(a=1)") == ["batchUpdate"]
    assert sheet_write_references("getattr(service, 'batchClear')") == ["batchClear"]
    # Reads, list appends and prose are not write references.
    assert sheet_write_references("service.spreadsheets().values().get(a=1)") == []
    assert sheet_write_references("matches.append(1)") == []
    assert sheet_write_references('"""no update/append/batchUpdate call here"""') == []


def test_no_sheet_write_api_or_write_scope_exists_anywhere_in_the_package():
    modules = sorted(PACKAGE_DIR.glob("*.py"))
    assert {path.name for path in modules} >= {"index.py", "refresh_log.py", "sheets_client.py", "cli.py"}
    for path in modules:
        assert sheet_write_references(path.read_text()) == [], path.name

    from notion_navigation_client import sheets_client

    assert sheets_client.SCOPES == ["https://www.googleapis.com/auth/spreadsheets.readonly"]


WRITE_VERBS = frozenset(
    {
        "write", "update", "append", "clear", "delete", "remove", "set", "create", "insert",
        "put", "post", "save", "send", "batch", "merge", "patch", "mutate", "edit",
    }
)


def write_verbs_in(name):
    return WRITE_VERBS & set(name.lower().split("_"))


def test_navigation_index_public_surface_has_no_write_verbs():
    # A deny-list of write verbs rather than an allow-list of prefixes, so adding another
    # read method (for example a name listing) never needs this test edited.
    public = [name for name in dir(NavigationIndex) if not name.startswith("_")]
    assert "get_refresh_log" in public
    assert [name for name in public if write_verbs_in(name)] == []
    assert [name for name in dir(refresh_log) if not name.startswith("_") and write_verbs_in(name)] == []
    assert write_verbs_in("update_record") == {"update"}  # the check can actually fail
