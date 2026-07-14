import json
from pathlib import Path

from notion_navigation_client.index import NavigationIndex

SAMPLE_TABS = json.loads((Path(__file__).parent.parent / "samples" / "sample_tabs.json").read_text())


def fake_fetch_tab(calls, tab_name):
    calls.append(tab_name)
    return SAMPLE_TABS[tab_name]


def make_index():
    calls: list[str] = []
    index = NavigationIndex(lambda tab_name: fake_fetch_tab(calls, tab_name))
    return index, calls


def test_get_dashboard_returns_record_with_warning():
    index, _ = make_index()
    result = index.get_dashboard("Curriculum Source Control")
    assert result["Owner / Source of Truth?"] == "Yes - curriculum/source authority"
    assert "Navigation aid only" in result["navigation_warning"]


def test_get_dashboard_unknown_name_returns_none():
    index, _ = make_index()
    assert index.get_dashboard("Nonexistent Dashboard") is None


def test_get_database_passes_through_human_review_flag():
    index, _ = make_index()
    result = index.get_database("DM Units")
    assert result["Readiness-Relevant?"] == "Yes"
    assert result["Human Review Needed?"] == "No"


def test_get_field_matches_live_property_name_header():
    index, _ = make_index()
    result = index.get_field("DM Units", "Generation Gate")
    assert result["Human Review Needed?"] == "Yes"
    assert result["Property Name"] == "Generation Gate"
    assert result["Canonical Meaning"].startswith("Generation permission/gate")


def test_get_field_matches_legacy_field_name_header():
    tabs = {
        "Property Dictionary": [
            ["Database Name", "Field Name", "Canonical Meaning", "Human Review Needed?"],
            ["DM Units", "Generation Gate", "Legacy field-name fixture", "Yes"],
        ]
    }
    index = NavigationIndex(lambda tab_name: tabs[tab_name])
    result = index.get_field("DM Units", "Generation Gate")
    assert result["Field Name"] == "Generation Gate"
    assert result["Canonical Meaning"] == "Legacy field-name fixture"
    assert result["Human Review Needed?"] == "Yes"


def test_get_field_wrong_database_returns_none():
    index, _ = make_index()
    assert index.get_field("DM Source Library", "Generation Gate") is None


def test_get_source_of_truth_lookup():
    index, _ = make_index()
    result = index.get_source_of_truth("Curriculum readiness")
    assert result["Source-of-Truth Database"] == "DM Units / DM Curriculum Elements"


def test_get_workflow_lookup():
    index, _ = make_index()
    result = index.get_workflow("Unit planning")
    assert result["Human Review Needed?"] == "Yes"


def test_get_prompt_lookup():
    index, _ = make_index()
    result = index.get_prompt("Curriculum readiness check")
    assert result["Agent Type"] == "Curriculum Agent"
    assert result["Human Review Required?"] == "Yes if owner unclear"


def test_check_duplicate_risk_exact_match():
    index, _ = make_index()
    matches = index.check_duplicate_risk("Readiness")
    assert len(matches) == 1
    assert matches[0]["Risk Type"] == "Conflicting status meaning"
    assert matches[0]["Human Review Needed?"] == "Yes"


def test_check_duplicate_risk_substring_match_in_similar_to():
    index, _ = make_index()
    matches = index.check_duplicate_risk("Materials Production Readiness")
    assert len(matches) == 1
    assert matches[0]["Suspect Field, Database, or Dashboard"] == "Readiness"


def test_check_duplicate_risk_no_match_returns_empty_list():
    index, _ = make_index()
    assert index.check_duplicate_risk("Nothing Like This") == []


def test_direct_header_dashboard_lookup_still_works():
    tabs = {
        "Dashboard Registry": [
            ["Dashboard Name", "Owner"],
            ["Curriculum Source Control", "Source Control"],
        ]
    }
    index = NavigationIndex(lambda tab_name: tabs[tab_name])
    result = index.get_dashboard("Curriculum Source Control")
    assert result["Owner"] == "Source Control"
    assert "Navigation aid only" in result["navigation_warning"]


def test_each_tab_is_fetched_at_most_once_per_session():
    index, calls = make_index()
    index.get_dashboard("Curriculum Source Control")
    index.get_dashboard("Unit Alignment & Readiness Dashboard")
    index.get_dashboard("Curriculum Source Control")
    assert calls == ["Dashboard Registry"]


def test_different_tabs_are_cached_independently():
    index, calls = make_index()
    index.get_dashboard("Curriculum Source Control")
    index.get_database("DM Units")
    index.get_dashboard("Curriculum Source Control")
    assert calls == ["Dashboard Registry", "Database Registry"]
