import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from notion_navigation_client.cli import MAX_AGE_HOURS_LIMIT, main, parse_args
from notion_navigation_client.records import NAVIGATION_WARNING

SAMPLE_TABS = json.loads((Path(__file__).parent.parent / "samples" / "sample_tabs.json").read_text())


class FakeRequest:
    def __init__(self, tab_name, executed):
        self._tab_name = tab_name
        self._executed = executed

    def execute(self):
        self._executed.append(self._tab_name)
        return {"values": SAMPLE_TABS[self._tab_name]} if self._tab_name in SAMPLE_TABS else {}


def fake_service():
    """A Sheets service whose values().get(range=<tab>) answers from the sample tabs.

    Returns (service, requested, executed): the ranges asked for, and the reads executed.
    """
    service = MagicMock()
    requested = []
    executed = []

    def get(spreadsheetId, range):  # noqa: A002 - mirrors the Sheets API keyword
        requested.append(range)
        return FakeRequest(range, executed)

    service.spreadsheets.return_value.values.return_value.get.side_effect = get
    return service, requested, executed


def run(argv):
    service, requested, executed = fake_service()
    with patch("notion_navigation_client.cli.get_credentials") as get_credentials, patch(
        "notion_navigation_client.cli.build_sheets_service", return_value=service
    ) as build_service:
        exit_code = main(argv)
    return exit_code, service, (requested, executed), get_credentials, build_service


def test_preflight_requires_a_sheet_id(capsys):
    exit_code, _, _, get_credentials, _ = run(["preflight", "dashboard", "X", "--sheet-id", ""])
    assert exit_code == 1
    assert "--sheet-id" in capsys.readouterr().err
    get_credentials.assert_not_called()


def test_preflight_refuses_a_field_without_a_database_before_any_credentials(capsys):
    exit_code, _, _, get_credentials, build_service = run(["preflight", "field", "Lesson Tag", "--sheet-id", "sheet-id"])
    assert exit_code == 1
    assert "--database is required for kind=field" in capsys.readouterr().err
    get_credentials.assert_not_called()
    build_service.assert_not_called()


@pytest.mark.parametrize("hours", ["0", "-1", "nan", "inf", str(MAX_AGE_HOURS_LIMIT + 1), "1e308"])
def test_preflight_refuses_a_nonsensical_freshness_policy(hours, capsys):
    exit_code, _, _, get_credentials, _ = run(
        ["preflight", "dashboard", "X", "--sheet-id", "sheet-id", "--max-age-hours", hours]
    )
    assert exit_code == 1
    assert "--max-age-hours must be greater than 0" in capsys.readouterr().err
    get_credentials.assert_not_called()


def test_preflight_rejects_an_unknown_kind():
    with pytest.raises(SystemExit):
        parse_args(["preflight", "schema", "X"])


def test_preflight_prints_the_advisory_result_as_json(capsys):
    exit_code, _, (requested, _), _, _ = run(
        ["preflight", "dashboard", "Curriculum Source Control", "--sheet-id", "sheet-id"]
    )
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["outcome"] == "existing-match"
    assert result["identity"]["matches"][0]["name"] == "Curriculum Source Control"
    assert result["navigation_warning"] == NAVIGATION_WARNING
    assert result["live_verification_required"] is True
    assert result["authorizes_mutation"] is False
    assert "Dashboard Registry" in requested


@pytest.mark.parametrize(
    "argv, outcome",
    [
        (["dashboard", "Curriculum Source Control"], "existing-match"),
        (["field", "Readiness", "--database", "DM Units"], "duplicate-risk-review"),
        (["dashboard", "Brand New Dashboard"], "stale-or-unverified"),
    ],
)
def test_the_exit_status_never_carries_the_verdict(argv, outcome, capsys):
    exit_code, _, _, _, _ = run(["preflight", *argv, "--sheet-id", "sheet-id"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == outcome


def test_preflight_passes_the_information_type_through_to_routing(capsys):
    run(
        [
            "preflight",
            "dashboard",
            "Brand New Dashboard",
            "--information-type",
            "Curriculum readiness",
            "--sheet-id",
            "sheet-id",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert [route["source"] for route in result["routing"]["routes"]] == ["source-of-truth-matrix"]


def test_preflight_without_a_policy_passes_no_clock_and_no_maximum_age():
    with patch("notion_navigation_client.cli.precreate_preflight", return_value={}) as preflight:
        run(["preflight", "dashboard", "X", "--sheet-id", "sheet-id"])
    assert preflight.call_args.kwargs == {}


def test_preflight_builds_the_freshness_policy_from_the_flag():
    before = datetime.now(timezone.utc)
    with patch("notion_navigation_client.cli.precreate_preflight", return_value={}) as preflight:
        run(["preflight", "dashboard", "X", "--sheet-id", "sheet-id", "--max-age-hours", "36"])
    after = datetime.now(timezone.utc)
    kwargs = preflight.call_args.kwargs
    assert kwargs["max_age"] == timedelta(hours=36)
    assert kwargs["now"].tzinfo is not None
    assert before <= kwargs["now"] <= after
    request = preflight.call_args.args[1]
    assert (request.kind, request.name, request.database, request.information_type) == ("dashboard", "X", None, None)


def test_preflight_cli_path_only_reads_known_tabs():
    _, service, (requested, executed), _, _ = run(
        ["preflight", "field", "Readiness", "--database", "DM Units", "--max-age-hours", "24", "--sheet-id", "sheet-id"]
    )
    # Only spreadsheets().values().get(...) was ever called on the service, and every read executed.
    assert {call[0] for call in service.mock_calls} == {
        "spreadsheets",
        "spreadsheets().values",
        "spreadsheets().values().get",
    }
    assert requested == executed
    assert set(requested) <= {
        "Property Dictionary",
        "Duplicate / Drift Watchlist",
        "Database Registry",
        "Refresh Log",
    }
    assert len(requested) == len(set(requested))  # one read per tab per session


def test_lookup_still_works_beside_preflight(capsys):
    exit_code, _, _, _, _ = run(["lookup", "dashboard", "Curriculum Source Control", "--sheet-id", "sheet-id"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["Dashboard Name"] == "Curriculum Source Control"
    assert run(["lookup", "field", "DM Units", "--sheet-id", "sheet-id"])[0] == 1
