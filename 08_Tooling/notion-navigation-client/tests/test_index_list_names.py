import json
from pathlib import Path

import pytest

from notion_navigation_client.index import NavigationIndex
from notion_navigation_client.records import NAVIGATION_WARNING

SAMPLE_TABS = json.loads((Path(__file__).parent.parent / "samples" / "sample_tabs.json").read_text())


def make_index(tabs=None):
    calls: list[str] = []
    tabs = SAMPLE_TABS if tabs is None else tabs

    def fetch(tab_name):
        calls.append(tab_name)
        return tabs[tab_name]

    return NavigationIndex(fetch), calls


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("dashboard", ["Curriculum Source Control", "Unit Alignment & Readiness Dashboard"]),
        ("database", ["Canonical Digital Media Unit Registry", "DM Units", "DM Curriculum Elements"]),
        ("workflow", ["Unit planning"]),
        ("prompt", ["Curriculum readiness check"]),
    ],
)
def test_list_names_returns_stored_names_in_sheet_order(kind, expected):
    index, _ = make_index()
    assert index.list_names(kind) == expected


def test_list_names_for_fields_is_scoped_to_one_database():
    index, _ = make_index()
    assert index.list_names("field", database="DM Units") == ["Readiness", "Generation Gate"]
    assert index.list_names("field", database="No Such Database") == []


def test_list_names_matches_the_keyed_getters_name_for_name():
    index, _ = make_index()
    for name in index.list_names("dashboard"):
        assert index.get_dashboard(name)["Dashboard Name"] == name
    for name in index.list_names("database"):
        assert index.get_database(name)["Database Name"] == name
    for name in index.list_names("field", database="DM Units"):
        assert index.get_field("DM Units", name) is not None


def test_list_names_preserves_repeated_names_that_the_keyed_getters_collapse():
    tabs = {
        "Dashboard Registry": [
            [NAVIGATION_WARNING],
            ["Dashboard Name", "Owner"],
            ["Unit Hub", "Owner A"],
            ["Unit Hub", "Owner B"],
            ["", "Blank name is skipped"],
        ]
    }
    index, _ = make_index(tabs)
    assert index.list_names("dashboard") == ["Unit Hub", "Unit Hub"]
    assert index.get_dashboard("Unit Hub")["Owner"] == "Owner B"


def test_list_names_supports_both_property_name_headers():
    tabs = {
        "Property Dictionary": [
            ["Database Name", "Field Name"],
            ["DM Units", "Legacy Field"],
            ["DM Units", ""],
        ]
    }
    index, _ = make_index(tabs)
    assert index.list_names("field", database="DM Units") == ["Legacy Field"]


def test_list_names_requires_a_database_for_fields_and_rejects_unknown_kinds():
    index, calls = make_index()
    with pytest.raises(ValueError, match="database is required"):
        index.list_names("field")
    with pytest.raises(ValueError, match="database is required"):
        index.list_names("field", database="")
    with pytest.raises(ValueError, match="unsupported kind"):
        index.list_names("watchlist")
    with pytest.raises(ValueError, match="unsupported kind"):
        index.list_names("")
    assert calls == []


def test_list_names_shares_the_per_session_tab_cache():
    index, calls = make_index()
    index.list_names("dashboard")
    index.get_dashboard("Curriculum Source Control")
    index.list_names("dashboard")
    index.list_names("field", database="DM Units")
    index.get_field("DM Units", "Generation Gate")
    assert calls == ["Dashboard Registry", "Property Dictionary"]


def test_list_names_returns_a_new_list_each_time():
    index, _ = make_index()
    first = index.list_names("dashboard")
    first.append("tampered")
    assert index.list_names("dashboard") == ["Curriculum Source Control", "Unit Alignment & Readiness Dashboard"]



def test_list_names_enumerates_information_types_and_watchlist_suspects():
    index, _ = make_index()
    assert index.list_names("source-of-truth")[:1] == ["Curriculum readiness"]
    assert index.list_names("duplicate-risk") == ["Readiness", "Generation Gate"]
