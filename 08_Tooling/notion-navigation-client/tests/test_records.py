from notion_navigation_client.records import (
    NAVIGATION_WARNING,
    index_by,
    is_navigation_warning_row,
    rows_to_records,
    split_header_and_data,
    with_warning,
)


def test_rows_to_records_zips_header_and_rows():
    header = ["Name", "Owner"]
    rows = [["Curriculum Source Control", "Governance Agent"]]
    assert rows_to_records(header, rows) == [{"Name": "Curriculum Source Control", "Owner": "Governance Agent"}]


def test_rows_to_records_pads_short_rows():
    header = ["Name", "Owner", "Notes"]
    rows = [["DM Units"]]
    assert rows_to_records(header, rows) == [{"Name": "DM Units", "Owner": "", "Notes": ""}]


def test_is_navigation_warning_row_matches_standard_banner():
    assert is_navigation_warning_row([NAVIGATION_WARNING]) is True


def test_is_navigation_warning_row_rejects_header_row():
    assert is_navigation_warning_row(["Dashboard Name", "Owner"]) is False


def test_split_header_and_data_skips_banner_row():
    rows = [[NAVIGATION_WARNING], ["Name", "Owner"], ["DM Units", "Source Control"]]
    header, data = split_header_and_data(rows)
    assert header == ["Name", "Owner"]
    assert data == [["DM Units", "Source Control"]]


def test_split_header_and_data_accepts_direct_header_rows():
    rows = [["Name", "Owner"], ["DM Units", "Source Control"]]
    header, data = split_header_and_data(rows)
    assert header == ["Name", "Owner"]
    assert data == [["DM Units", "Source Control"]]


def test_index_by_keys_on_field():
    records = [{"Dashboard Name": "A", "Owner": "X"}, {"Dashboard Name": "B", "Owner": "Y"}]
    index = index_by(records, "Dashboard Name")
    assert index["A"]["Owner"] == "X"
    assert index["B"]["Owner"] == "Y"


def test_index_by_skips_records_missing_key():
    records = [{"Dashboard Name": "", "Owner": "X"}, {"Dashboard Name": "B", "Owner": "Y"}]
    index = index_by(records, "Dashboard Name")
    assert list(index) == ["B"]


def test_with_warning_attaches_warning_without_mutating_original():
    record = {"Dashboard Name": "A"}
    result = with_warning(record)
    assert result["navigation_warning"] == NAVIGATION_WARNING
    assert "navigation_warning" not in record


def test_with_warning_passes_through_none():
    assert with_warning(None) is None
