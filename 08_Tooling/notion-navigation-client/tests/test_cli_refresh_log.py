import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from notion_navigation_client.cli import main, parse_args
from notion_navigation_client.records import NAVIGATION_WARNING

SAMPLE_TABS = json.loads((Path(__file__).parent.parent / "samples" / "sample_tabs.json").read_text())


def fake_service(rows):
    service = MagicMock()
    service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = (
        {"values": rows} if rows else {}
    )
    return service


def run(argv, rows):
    """Run the CLI against a mocked Sheets service; return (exit code, service)."""
    service = fake_service(rows)
    with patch("notion_navigation_client.cli.get_credentials") as get_credentials, patch(
        "notion_navigation_client.cli.build_sheets_service", return_value=service
    ) as build_service:
        exit_code = main(argv)
    return exit_code, service, get_credentials, build_service


def test_refresh_log_requires_sheet_id(capsys):
    exit_code, _, get_credentials, _ = run(["refresh-log", "--sheet-id", ""], SAMPLE_TABS["Refresh Log"])
    assert exit_code == 1
    assert "--sheet-id" in capsys.readouterr().err
    get_credentials.assert_not_called()


@pytest.mark.parametrize("limit", ["0", "-3", "201", "1000"])
def test_refresh_log_rejects_out_of_range_limit_before_any_credentials(limit, capsys):
    exit_code, _, get_credentials, build_service = run(
        ["refresh-log", "--sheet-id", "sheet-id", "--limit", limit], SAMPLE_TABS["Refresh Log"]
    )
    assert exit_code == 1
    assert "--limit must be an integer between 1 and 200" in capsys.readouterr().err
    get_credentials.assert_not_called()
    build_service.assert_not_called()


def test_refresh_log_prints_bounded_evidence_as_json(capsys):
    exit_code, service, _, _ = run(["refresh-log", "--sheet-id", "sheet-id"], SAMPLE_TABS["Refresh Log"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["navigation_warning"] == NAVIGATION_WARNING
    assert result["tab"] == "Refresh Log"
    assert [entry["source_row"] for entry in result["entries"]] == [3, 4, 5]
    assert result["entries"][0]["timestamp"] == {
        "raw": "2026-07-04 16:04 UTC",
        "status": "explicit-utc",
        "utc": "2026-07-04T16:04:00Z",
    }
    assert result["latest_observed_refresh"]["by_source_row"]["source_row"] == 5
    assert result["latest_observed_refresh"]["by_timestamp"] is None
    service.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
        spreadsheetId="sheet-id", range="Refresh Log"
    )


def test_refresh_log_limit_option_bounds_the_window(capsys):
    exit_code, _, _, _ = run(["refresh-log", "--sheet-id", "sheet-id", "--limit", "1"], SAMPLE_TABS["Refresh Log"])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["limit"] == 1
    assert result["returned_rows"] == 1
    assert result["total_populated_rows"] == 3
    assert result["truncated"] is True
    assert result["entries"][0]["source_row"] == 5


def test_refresh_log_default_limit_matches_the_documented_default(capsys):
    assert parse_args(["refresh-log", "--sheet-id", "x"]).limit == 20
    run(["refresh-log", "--sheet-id", "sheet-id"], SAMPLE_TABS["Refresh Log"])
    assert json.loads(capsys.readouterr().out)["limit"] == 20


def test_empty_refresh_log_is_a_successful_read_with_an_empty_envelope(capsys):
    exit_code, _, _, _ = run(["refresh-log", "--sheet-id", "sheet-id"], [])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["entries"] == []
    assert result["navigation_warning"] == NAVIGATION_WARNING
    assert result["latest_observed_refresh"]["by_timestamp_unavailable_reason"] == "no-entries"


def test_refresh_log_cli_path_only_reads(capsys):
    """Every Sheets client call made on the refresh-log path is a values().get().execute() read."""
    _, service, _, _ = run(["refresh-log", "--sheet-id", "sheet-id"], SAMPLE_TABS["Refresh Log"])

    names = {call[0] for call in service.mock_calls}
    assert names == {
        "spreadsheets",
        "spreadsheets().values",
        "spreadsheets().values().get",
        "spreadsheets().values().get().execute",
    }


def test_lookup_subcommand_is_unchanged_by_refresh_log_support():
    with patch("notion_navigation_client.cli.NavigationIndex") as index_cls, patch(
        "notion_navigation_client.cli.build_sheets_service"
    ), patch("notion_navigation_client.cli.get_credentials"):
        index_cls.return_value.get_dashboard.return_value = {"Dashboard Name": "Curriculum Source Control"}
        assert main(["lookup", "dashboard", "Curriculum Source Control", "--sheet-id", "sheet-id"]) == 0
        index_cls.return_value.get_dashboard.assert_called_once_with("Curriculum Source Control")
        index_cls.return_value.get_refresh_log.assert_not_called()


def test_lookup_kinds_do_not_include_the_refresh_log():
    # Refresh Log evidence is a bounded window, not a keyed record lookup.
    with pytest.raises(SystemExit):
        parse_args(["lookup", "refresh-log", "key"])
