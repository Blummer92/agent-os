from unittest.mock import MagicMock, patch

from notion_navigation_client.cli import main


def test_main_requires_sheet_id():
    exit_code = main(["lookup", "dashboard", "Curriculum Source Control", "--sheet-id", ""])
    assert exit_code == 1


def test_main_requires_field_for_field_kind():
    exit_code = main(["lookup", "field", "DM Units", "--sheet-id", "sheet-id"])
    assert exit_code == 1


@patch("notion_navigation_client.cli.NavigationIndex")
@patch("notion_navigation_client.cli.build_sheets_service")
@patch("notion_navigation_client.cli.get_credentials")
def test_main_prints_lookup_result(mock_get_credentials, mock_build_service, mock_index_cls, capsys):
    mock_index = MagicMock()
    mock_index.get_dashboard.return_value = {"Dashboard Name": "Curriculum Source Control"}
    mock_index_cls.return_value = mock_index

    exit_code = main(["lookup", "dashboard", "Curriculum Source Control", "--sheet-id", "sheet-id"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Curriculum Source Control" in out
    mock_index.get_dashboard.assert_called_once_with("Curriculum Source Control")


@patch("notion_navigation_client.cli.NavigationIndex")
@patch("notion_navigation_client.cli.build_sheets_service")
@patch("notion_navigation_client.cli.get_credentials")
def test_main_returns_1_when_lookup_finds_nothing(mock_get_credentials, mock_build_service, mock_index_cls):
    mock_index = MagicMock()
    mock_index.get_dashboard.return_value = None
    mock_index_cls.return_value = mock_index

    exit_code = main(["lookup", "dashboard", "Nonexistent", "--sheet-id", "sheet-id"])

    assert exit_code == 1
