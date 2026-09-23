from unittest.mock import MagicMock

from notion_navigation_client.sheets_client import fetch_tab_values


def test_fetch_tab_values_calls_get_with_tab_as_range():
    service = MagicMock()
    service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [["Dashboard Name", "Owner"], ["Curriculum Source Control", "Governance Agent"]]
    }

    rows = fetch_tab_values(service, "sheet-id", "Dashboard Registry")

    assert rows == [["Dashboard Name", "Owner"], ["Curriculum Source Control", "Governance Agent"]]
    service.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
        spreadsheetId="sheet-id", range="Dashboard Registry"
    )


def test_fetch_tab_values_returns_empty_list_when_tab_has_no_values():
    service = MagicMock()
    service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {}

    assert fetch_tab_values(service, "sheet-id", "Empty Tab") == []
