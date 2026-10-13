import ast
import copy
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from notion_navigation_client import precreate
from notion_navigation_client.index import NavigationIndex
from notion_navigation_client.precreate import (
    NEXT_STEP,
    OUTCOMES,
    PREFLIGHT_KINDS,
    PreCreateRequest,
    normalize_name,
    precreate_preflight,
)
from notion_navigation_client.records import NAVIGATION_WARNING

PACKAGE_DIR = Path(__file__).parent.parent / "src" / "notion_navigation_client"
SAMPLE_TABS = json.loads((Path(__file__).parent.parent / "samples" / "sample_tabs.json").read_text())

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
MAX_AGE = timedelta(hours=24)
POLICY = {"now": NOW, "max_age": MAX_AGE}


def sample_index(tabs=None):
    tabs = SAMPLE_TABS if tabs is None else tabs
    return NavigationIndex(lambda tab_name: tabs[tab_name])


def tab(header, *rows):
    return [[NAVIGATION_WARNING], list(header), *[list(row) for row in rows]]


class LookupOnly:
    """The NavigationLookup surface and nothing else (no Refresh Log), recording every call."""

    def __init__(self, index):
        self._index = index
        self.calls = []

    def list_names(self, kind, database=None):
        self.calls.append(("list_names", kind, database))
        return self._index.list_names(kind, database=database)

    def get_dashboard(self, name):
        self.calls.append(("get_dashboard", name))
        return self._index.get_dashboard(name)

    def get_database(self, name):
        self.calls.append(("get_database", name))
        return self._index.get_database(name)

    def get_field(self, database, field):
        self.calls.append(("get_field", database, field))
        return self._index.get_field(database, field)

    def get_workflow(self, workflow_name):
        self.calls.append(("get_workflow", workflow_name))
        return self._index.get_workflow(workflow_name)

    def get_prompt(self, prompt_name):
        self.calls.append(("get_prompt", prompt_name))
        return self._index.get_prompt(prompt_name)

    def get_source_of_truth(self, information_type):
        self.calls.append(("get_source_of_truth", information_type))
        return self._index.get_source_of_truth(information_type)

    def check_duplicate_risk(self, name):
        self.calls.append(("check_duplicate_risk", name))
        return self._index.check_duplicate_risk(name)


class WithLog(LookupOnly):
    """LookupOnly plus a Refresh Log source: evidence to return, or an exception to raise."""

    def __init__(self, index, log):
        super().__init__(index)
        self._log = log

    def get_refresh_log(self, limit=20):
        self.calls.append(("get_refresh_log", limit))
        if isinstance(self._log, Exception):
            raise self._log
        return self._log


def entry(source_row, raw, status, utc):
    return {
        "source_row": source_row,
        "timestamp": {"raw": raw, "status": status, "utc": utc},
        "record": {"Refresh Date": raw},
        "navigation_warning": NAVIGATION_WARNING,
    }


def explicit_log(utc="2026-10-13T06:00:00Z", raw="2026-10-13 06:00 UTC", total=3):
    latest = entry(5, raw, "explicit-utc", utc)
    return {
        "total_populated_rows": total,
        "latest_observed_refresh": {
            "by_source_row": latest,
            "by_timestamp": latest,
            "by_timestamp_unavailable_reason": None,
            "agree": True,
        },
    }


def unresolved_log():
    latest = entry(5, "2026-08-09 16:37:20.339", "ambiguous-timezone", None)
    return {
        "total_populated_rows": 3,
        "latest_observed_refresh": {
            "by_source_row": latest,
            "by_timestamp": None,
            "by_timestamp_unavailable_reason": "timestamps-not-all-explicit",
            "agree": None,
        },
    }


def empty_log():
    return {
        "total_populated_rows": 0,
        "latest_observed_refresh": {
            "by_source_row": None,
            "by_timestamp": None,
            "by_timestamp_unavailable_reason": "no-entries",
            "agree": None,
        },
    }


def current_index(tabs=None):
    return WithLog(sample_index(tabs), explicit_log())


def run(request, index=None, **policy):
    return precreate_preflight(index if index is not None else current_index(), request, **policy)


# --- identity: exact and normalized ---------------------------------------------


def test_exact_dashboard_match_is_existing_match_with_the_cached_record():
    result = run(PreCreateRequest("dashboard", "Curriculum Source Control"), **POLICY)
    assert result["outcome"] == "existing-match"
    assert result["identity"]["status"] == "exact-match"
    (match,) = result["identity"]["matches"]
    assert match["basis"] == "exact"
    assert match["name"] == "Curriculum Source Control"
    assert match["occurrences"] == 1
    assert match["record"]["Owner / Source of Truth?"] == "Yes - curriculum/source authority"
    assert match["record"]["navigation_warning"] == NAVIGATION_WARNING
    assert result["reason_codes"][:2] == ["identity.exact-match", "duplicate-risk.no-hit"]


@pytest.mark.parametrize(
    "kind, name",
    [
        ("database", "Canonical Digital Media Unit Registry"),
        ("workflow", "Unit planning"),
        ("prompt", "Curriculum readiness check"),
    ],
)
def test_exact_match_for_every_other_keyed_kind(kind, name):
    result = run(PreCreateRequest(kind, name), **POLICY)
    assert result["outcome"] == "existing-match"
    assert result["identity"]["matches"][0]["name"] == name


def test_a_name_inside_a_watchlist_family_description_routes_to_review_by_substring():
    # check_duplicate_risk matches substrings of "Similar To", so "DM Units" is part of the
    # "Generation Gate" family text. The preflight reports that conservatively.
    result = run(PreCreateRequest("database", "DM Units"), **POLICY)
    assert result["identity"]["status"] == "exact-match"
    assert result["outcome"] == "duplicate-risk-review"
    assert result["duplicate_risk"]["hits"][0]["record"]["Suspect Field, Database, or Dashboard"] == "Generation Gate"


FIELD_HEADER = ["Database Name", "Property Name", "Recommended Owner", "Similar / Duplicate Fields", "Human Review Needed?"]


def test_exact_field_match_is_scoped_to_its_database():
    tabs = {
        **SAMPLE_TABS,
        "Property Dictionary": tab(
            FIELD_HEADER,
            ["DM Units", "Lesson Tag", "Curriculum Agent", "", "No"],
            ["DM Source Library", "Other Tag", "Curriculum Agent", "", "No"],
        ),
    }
    hit = run(PreCreateRequest("field", "Lesson Tag", database="DM Units"), current_index(tabs), **POLICY)
    assert hit["outcome"] == "existing-match"
    assert hit["identity"]["matches"][0]["record"]["Recommended Owner"] == "Curriculum Agent"

    wrong_database = run(PreCreateRequest("field", "Lesson Tag", database="DM Source Library"), current_index(tabs), **POLICY)
    assert wrong_database["identity"]["status"] == "no-match"


def test_normalized_match_is_reported_as_normalized_with_the_stored_name():
    result = run(PreCreateRequest("dashboard", "  curriculum   SOURCE control "), **POLICY)
    assert result["outcome"] == "existing-match"
    assert result["identity"]["status"] == "normalized-match"
    (match,) = result["identity"]["matches"]
    assert match["basis"] == "normalized"
    assert match["name"] == "Curriculum Source Control"
    assert "identity.normalized-match" in result["reason_codes"]
    assert result["request"]["name"] == "  curriculum   SOURCE control "


@pytest.mark.parametrize(
    "variant",
    [
        "Ｃｕｒｒｉｃｕｌｕｍ Ｓｏｕｒｃｅ Ｃｏｎｔｒｏｌ",  # full-width forms fold under NFKC
        "Curriculum Source Control",  # no-break spaces collapse
        "CURRICULUM\tSOURCE\nCONTROL",
    ],
)
def test_supported_normalization_variants_match(variant):
    result = run(PreCreateRequest("dashboard", variant), **POLICY)
    assert result["identity"]["status"] == "normalized-match"


@pytest.mark.parametrize(
    "variant",
    [
        "Curriculum-Source-Control",  # punctuation is not normalized
        "Curriculum Source Controls",  # plurals are not normalized
        "Source Control Curriculum",  # word order is not normalized
        "Curr Source Control",  # abbreviations are not normalized
        "Curriculum Source Control Dashboard",  # no substring matching
        "Curriculum Source",  # a prefix of a stored name is not that name
        "Source Control",  # nor is a suffix
        "control",  # nor a fragment
    ],
)
def test_normalization_is_deliberately_limited_so_lookalikes_do_not_match(variant):
    result = run(PreCreateRequest("dashboard", variant), **POLICY)
    assert result["identity"]["status"] == "no-match"
    assert result["outcome"] == "no-cached-match"


def test_normalize_name_contract():
    assert normalize_name("  A  b\tC  ") == "a b c"
    assert normalize_name("Ｇｅｎｅｒａｔｉｏｎ Ｇａｔｅ") == "generation gate"
    assert normalize_name("Straße") == normalize_name("STRASSE") == "strasse"
    assert normalize_name("a-b") != normalize_name("a b")
    assert normalize_name(normalize_name("  Mixed   Case ")) == normalize_name("  Mixed   Case ")
    assert normalize_name("") == ""


DASHBOARD_HEADER = ["Dashboard Name", "Notion URL", "Notion ID", "Dashboard Type", "Owner / Source of Truth?", "Human Review Needed?"]


def dashboard_tabs(*rows):
    return {**SAMPLE_TABS, "Dashboard Registry": tab(DASHBOARD_HEADER, *rows)}


def test_exact_and_normalized_twin_in_the_cache_is_ambiguous():
    tabs = dashboard_tabs(
        ["Unit Hub", "", "", "Source of Truth", "Owner A", "No"],
        ["unit hub", "", "", "Source of Truth", "Owner B", "No"],
    )
    result = run(PreCreateRequest("dashboard", "Unit Hub"), current_index(tabs), **POLICY)
    assert result["outcome"] == "manual-review"
    assert result["identity"]["status"] == "ambiguous"
    assert {match["name"] for match in result["identity"]["matches"]} == {"Unit Hub", "unit hub"}
    assert result["reason_codes"][0] == "identity.ambiguous"
    assert result["human_review_required"] is True


def test_two_normalized_candidates_without_an_exact_match_are_ambiguous():
    tabs = dashboard_tabs(
        ["Unit Hub", "", "", "Source of Truth", "Owner A", "No"],
        ["UNIT HUB", "", "", "Source of Truth", "Owner B", "No"],
    )
    result = run(PreCreateRequest("dashboard", "unit hub"), current_index(tabs), **POLICY)
    assert result["outcome"] == "manual-review"
    assert result["identity"]["status"] == "ambiguous"
    assert [match["basis"] for match in result["identity"]["matches"]] == ["normalized", "normalized"]


def test_a_name_repeated_in_the_cache_is_ambiguous_not_silently_resolved():
    tabs = dashboard_tabs(
        ["Unit Hub", "", "", "Source of Truth", "Owner A", "No"],
        ["Unit Hub", "", "", "Source of Truth", "Owner B", "No"],
    )
    result = run(PreCreateRequest("dashboard", "Unit Hub"), current_index(tabs), **POLICY)
    assert result["outcome"] == "manual-review"
    assert result["identity"]["matches"][0]["occurrences"] == 2
    assert result["reason_codes"][:2] == ["identity.ambiguous", "identity.duplicate-cache-rows"]


def test_a_listed_name_with_no_readable_record_is_manual_review():
    class Inconsistent(LookupOnly):
        def get_dashboard(self, name):
            return None

    result = precreate_preflight(Inconsistent(sample_index()), PreCreateRequest("dashboard", "Curriculum Source Control"), **POLICY)
    assert result["outcome"] == "manual-review"
    assert result["identity"]["status"] == "unreadable"
    assert result["reason_codes"][0] == "identity.record-unreadable"


# --- duplicate-risk watchlist ------------------------------------------------------


def test_watchlist_hit_on_the_requested_name_routes_to_human_review():
    result = run(PreCreateRequest("field", "Readiness", database="DM Units"), **POLICY)
    assert result["outcome"] == "duplicate-risk-review"
    assert result["human_review_required"] is True
    assert result["duplicate_risk"]["hit_count"] == 1
    (hit,) = result["duplicate_risk"]["hits"]
    assert hit["matched_on"] == "Readiness"
    assert hit["record"]["Risk Type"] == "Conflicting status meaning"
    assert hit["record"]["navigation_warning"] == NAVIGATION_WARNING
    assert result["identity"]["status"] == "exact-match"  # the identity evidence is kept alongside


def test_watchlist_similar_to_hit_flags_a_new_name_with_no_identity_match():
    result = run(PreCreateRequest("field", "Materials Production Readiness", database="DM Units"), **POLICY)
    assert result["identity"]["status"] == "no-match"
    assert result["outcome"] == "duplicate-risk-review"
    assert result["duplicate_risk"]["hits"][0]["record"]["Suspect Field, Database, or Dashboard"] == "Readiness"


def test_watchlist_is_also_checked_for_the_matched_stored_name():
    result = run(PreCreateRequest("field", " readiness ", database="DM Units"), **POLICY)
    assert result["identity"]["status"] == "normalized-match"
    assert result["duplicate_risk"]["checked_names"] == [" readiness ", "Readiness"]
    assert result["outcome"] == "duplicate-risk-review"
    assert result["duplicate_risk"]["hits"][0]["matched_on"] == "Readiness"


def test_the_same_watchlist_row_is_reported_once_even_if_two_names_find_it():
    # " Readiness" hits the row through Similar To (substring) and the stored name "Readiness"
    # hits it through Suspect (exact): one row, reported once, under the first name that found it.
    result = run(PreCreateRequest("field", " Readiness", database="DM Units"), **POLICY)
    assert result["duplicate_risk"]["checked_names"] == [" Readiness", "Readiness"]
    rows = [hit["record"]["Suspect Field, Database, or Dashboard"] for hit in result["duplicate_risk"]["hits"]]
    assert rows == ["Readiness"]
    assert result["duplicate_risk"]["hit_count"] == 1
    assert result["duplicate_risk"]["hits"][0]["matched_on"] == " Readiness"


def test_every_watchlist_hit_counts_whatever_its_status():
    header = ["Suspect Field, Database, or Dashboard", "Similar To", "Risk Type", "Human Review Needed?", "Status"]
    tabs = {
        **SAMPLE_TABS,
        "Duplicate / Drift Watchlist": tab(header, ["Lesson Tag", "Lesson Label", "Duplicate field", "No", "Resolved"]),
    }
    result = run(PreCreateRequest("field", "Lesson Tag", database="DM Units"), current_index(tabs), **POLICY)
    assert result["outcome"] == "duplicate-risk-review"
    assert result["duplicate_risk"]["hits"][0]["record"]["Status"] == "Resolved"
    assert result["human_review_required"] is True


def test_no_watchlist_hit_is_reported_explicitly():
    result = run(PreCreateRequest("dashboard", "Curriculum Source Control"), **POLICY)
    assert result["duplicate_risk"] == {"checked_names": ["Curriculum Source Control"], "hit_count": 0, "hits": []}
    assert "duplicate-risk.no-hit" in result["reason_codes"]


# --- no cached match, staleness, and currentness -------------------------------------


def test_no_match_in_a_cache_shown_current_is_no_cached_match_and_still_not_safe_to_create():
    result = run(PreCreateRequest("dashboard", "Brand New Dashboard"), **POLICY)
    assert result["outcome"] == "no-cached-match"
    assert result["currentness"]["status"] == "within-policy"
    assert result["currentness"]["reason_code"] == "currentness.within-policy"
    assert "not proof that creating is safe" in result["next_step"]
    assert result["live_verification_required"] is True
    assert result["authorizes_mutation"] is False
    assert result["human_review_required"] is False


def test_no_match_when_the_index_offers_no_refresh_log_is_stale_or_unverified():
    result = precreate_preflight(LookupOnly(sample_index()), PreCreateRequest("dashboard", "Brand New Dashboard"), **POLICY)
    assert result["outcome"] == "stale-or-unverified"
    assert result["currentness"]["status"] == "unverified"
    assert result["currentness"]["reason_code"] == "currentness.refresh-log-unavailable"
    assert result["currentness"]["detail"] == "index-has-no-refresh-log"


def test_no_match_without_a_freshness_policy_is_unverified_but_shows_the_evidence():
    result = run(PreCreateRequest("dashboard", "Brand New Dashboard"))
    assert result["outcome"] == "stale-or-unverified"
    assert result["currentness"]["reason_code"] == "currentness.no-freshness-policy"
    assert result["currentness"]["latest_refresh_utc"] == "2026-10-13T06:00:00Z"
    assert result["currentness"]["latest_refresh_by_source_row"] == {
        "source_row": 5,
        "raw": "2026-10-13 06:00 UTC",
        "status": "explicit-utc",
    }


def test_a_policy_needs_both_the_clock_and_the_maximum_age():
    assert run(PreCreateRequest("dashboard", "X"), now=NOW)["currentness"]["reason_code"] == "currentness.no-freshness-policy"
    assert run(PreCreateRequest("dashboard", "X"), max_age=MAX_AGE)["currentness"]["reason_code"] == "currentness.no-freshness-policy"


def test_no_match_in_a_stale_cache_is_stale_or_unverified():
    index = WithLog(sample_index(), explicit_log(utc="2026-10-10T06:00:00Z", raw="2026-10-10 06:00 UTC"))
    result = run(PreCreateRequest("dashboard", "Brand New Dashboard"), index, **POLICY)
    assert result["outcome"] == "stale-or-unverified"
    assert result["currentness"]["status"] == "stale"
    assert result["currentness"]["reason_code"] == "currentness.stale"
    assert result["currentness"]["age_seconds"] == int((NOW - datetime(2026, 10, 10, 6, tzinfo=timezone.utc)).total_seconds())
    assert result["currentness"]["max_age_seconds"] == 86400


def test_freshness_boundary_is_inclusive():
    at_limit = WithLog(sample_index(), explicit_log(utc="2026-10-12T12:00:00Z"))
    just_over = WithLog(sample_index(), explicit_log(utc="2026-10-12T11:59:59Z"))
    assert run(PreCreateRequest("dashboard", "X"), at_limit, **POLICY)["currentness"]["status"] == "within-policy"
    assert run(PreCreateRequest("dashboard", "X"), just_over, **POLICY)["currentness"]["status"] == "stale"


def test_a_refresh_dated_after_now_is_unverified_not_fresh():
    index = WithLog(sample_index(), explicit_log(utc="2026-10-14T06:00:00Z"))
    result = run(PreCreateRequest("dashboard", "X"), index, **POLICY)
    assert result["currentness"]["status"] == "unverified"
    assert result["currentness"]["reason_code"] == "currentness.refresh-time-in-future"
    assert result["currentness"]["age_seconds"] < 0
    assert result["outcome"] == "stale-or-unverified"


def test_an_empty_refresh_log_means_missing_chronology_is_unverified():
    result = run(PreCreateRequest("dashboard", "X"), WithLog(sample_index(), empty_log()), **POLICY)
    assert result["currentness"]["reason_code"] == "currentness.no-refresh-records"
    assert result["outcome"] == "stale-or-unverified"


def test_unresolved_refresh_timestamps_are_unverified_and_stay_visible():
    result = run(PreCreateRequest("dashboard", "X"), WithLog(sample_index(), unresolved_log()), **POLICY)
    assert result["outcome"] == "stale-or-unverified"
    assert result["currentness"]["reason_code"] == "currentness.refresh-time-unresolved"
    assert result["currentness"]["detail"] == "timestamps-not-all-explicit"
    assert result["currentness"]["latest_refresh_utc"] is None
    assert result["currentness"]["latest_refresh_by_source_row"]["raw"] == "2026-08-09 16:37:20.339"
    assert result["currentness"]["latest_refresh_by_source_row"]["status"] == "ambiguous-timezone"


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        "not a mapping",
        {},
        {"total_populated_rows": True, "latest_observed_refresh": {}},
        {"total_populated_rows": 2, "latest_observed_refresh": "nope"},
        {
            "total_populated_rows": 2,
            "latest_observed_refresh": {"by_source_row": None, "by_timestamp": entry(3, "x", "explicit-utc", "garbage")},
        },
        {
            "total_populated_rows": 2,
            "latest_observed_refresh": {"by_source_row": None, "by_timestamp": entry(3, "x", "explicit-utc", "2026-10-13T06:00:00")},
        },
    ],
)
def test_malformed_refresh_log_evidence_is_unverified_never_fresh(evidence):
    result = run(PreCreateRequest("dashboard", "X"), WithLog(sample_index(), evidence), **POLICY)
    assert result["currentness"]["status"] == "unverified"
    assert result["currentness"]["reason_code"] == "currentness.refresh-log-malformed"
    assert result["outcome"] == "stale-or-unverified"


def test_a_failing_refresh_log_probe_degrades_to_unverified_without_leaking_its_message():
    index = WithLog(sample_index(), RuntimeError("secret token abc123 in message"))
    result = run(PreCreateRequest("dashboard", "X"), index, **POLICY)
    assert result["currentness"]["reason_code"] == "currentness.refresh-log-unavailable"
    assert result["currentness"]["detail"] == "RuntimeError"
    assert "abc123" not in json.dumps(result)
    assert result["outcome"] == "stale-or-unverified"


def test_a_failure_in_a_primary_lookup_is_not_swallowed():
    class Broken(LookupOnly):
        def check_duplicate_risk(self, name):
            raise RuntimeError("tab fetch failed")

    with pytest.raises(RuntimeError, match="tab fetch failed"):
        precreate_preflight(Broken(sample_index()), PreCreateRequest("dashboard", "X"), **POLICY)


def test_an_existing_match_keeps_its_outcome_while_a_stale_cache_stays_visible():
    index = WithLog(sample_index(), explicit_log(utc="2026-09-01T06:00:00Z"))
    result = run(PreCreateRequest("dashboard", "Curriculum Source Control"), index, **POLICY)
    assert result["outcome"] == "existing-match"
    assert result["currentness"]["status"] == "stale"
    assert "currentness.stale" in result["reason_codes"]


def test_a_duplicate_risk_outcome_keeps_its_outcome_while_currentness_is_unverified():
    result = run(PreCreateRequest("field", "Readiness", database="DM Units"), WithLog(sample_index(), empty_log()), **POLICY)
    assert result["outcome"] == "duplicate-risk-review"
    assert result["currentness"]["reason_code"] == "currentness.no-refresh-records"


# --- routing: verification guidance only ---------------------------------------------


def test_matched_record_route_copies_only_the_routing_columns():
    result = run(PreCreateRequest("dashboard", "Curriculum Source Control"), **POLICY)
    (route,) = result["routing"]["routes"]
    assert route["source"] == "matched-record"
    assert route["kind"] == "dashboard"
    assert route["key"] == "Curriculum Source Control"
    assert route["fields"]["Owner / Source of Truth?"] == "Yes - curriculum/source authority"
    assert set(route["fields"]) <= set(precreate._ROUTE_FIELDS["dashboard"])
    assert "Safe Agent Actions" not in route["fields"]
    assert "routing.matched-record" in result["reason_codes"]


def test_a_field_request_also_routes_to_its_parent_database():
    result = run(PreCreateRequest("field", "Brand New Field", database="DM Units"), **POLICY)
    (route,) = result["routing"]["routes"]
    assert route["source"] == "parent-database"
    assert route["kind"] == "database"
    assert route["key"] == "DM Units"
    assert route["fields"]["Database ID"] == "ddbed54e-8043-4096-9698-ebd22f9c888e"
    assert "routing.parent-database" in result["reason_codes"]


def test_an_uncached_parent_database_is_reported_as_an_evidence_gap():
    result = run(PreCreateRequest("field", "Brand New Field", database="Unknown DB"), **POLICY)
    assert result["routing"]["routes"] == []
    assert "routing.parent-database-not-cached" in result["reason_codes"]


def test_an_information_type_adds_its_source_of_truth_matrix_route():
    result = run(PreCreateRequest("dashboard", "Brand New", information_type="Curriculum readiness"), **POLICY)
    (route,) = result["routing"]["routes"]
    assert route["source"] == "source-of-truth-matrix"
    assert route["fields"]["Source-of-Truth Database"] == "DM Units / DM Curriculum Elements"
    assert "Verification Step Before Editing" in route["fields"]
    assert "routing.source-of-truth-matrix" in result["reason_codes"]


def test_an_unknown_information_type_is_an_evidence_gap():
    result = run(PreCreateRequest("dashboard", "Brand New", information_type="Nonexistent type"), **POLICY)
    assert result["routing"]["routes"] == []
    assert "routing.information-type-not-cached" in result["reason_codes"]


def test_no_routing_evidence_is_reported_explicitly():
    result = run(PreCreateRequest("workflow", "Brand New Flow"), **POLICY)
    assert result["routing"] == {"routes": []}
    assert result["reason_codes"][-1] == "routing.none"


def test_routes_accumulate_in_a_fixed_order():
    result = run(
        PreCreateRequest("field", "Generation Gate", database="DM Units", information_type="Curriculum readiness"), **POLICY
    )
    assert [route["source"] for route in result["routing"]["routes"]] == [
        "matched-record",
        "parent-database",
        "source-of-truth-matrix",
    ]


def test_field_route_supports_the_legacy_field_name_header():
    tabs = {
        **SAMPLE_TABS,
        "Property Dictionary": tab(
            ["Database Name", "Field Name", "Recommended Owner", "Human Review Needed?"],
            ["DM Units", "Lesson Tag", "Curriculum Agent", "No"],
        ),
    }
    result = run(PreCreateRequest("field", "Lesson Tag", database="DM Units"), current_index(tabs), **POLICY)
    route = result["routing"]["routes"][0]
    assert route["fields"]["Field Name"] == "Lesson Tag"
    assert "Property Name" not in route["fields"]


# --- human review ----------------------------------------------------------------------


def dashboard_with_flag(flag):
    row = ["Unit Hub", "", "", "Source of Truth", "Owner A"] + ([] if flag is None else [flag])
    header = DASHBOARD_HEADER if flag is not None else DASHBOARD_HEADER[:-1]
    return {**SAMPLE_TABS, "Dashboard Registry": tab(header, row)}


@pytest.mark.parametrize("flag", ["No", "no", " NO "])
def test_only_an_explicit_no_clears_a_record(flag):
    result = run(PreCreateRequest("dashboard", "Unit Hub"), current_index(dashboard_with_flag(flag)), **POLICY)
    assert result["outcome"] == "existing-match"
    assert result["human_review_required"] is False
    assert "review.record-flagged" not in result["reason_codes"]
    assert "review.flag-unclear" not in result["reason_codes"]


@pytest.mark.parametrize("flag", ["Yes", "yes", "Yes if owner unclear"])
def test_a_yes_flag_requires_review_and_is_reported(flag):
    result = run(PreCreateRequest("dashboard", "Unit Hub"), current_index(dashboard_with_flag(flag)), **POLICY)
    assert result["outcome"] == "existing-match"
    assert result["human_review_required"] is True
    assert "review.record-flagged" in result["reason_codes"]
    assert result["identity"]["matches"][0]["record"]["Human Review Needed?"] == flag


@pytest.mark.parametrize("flag", ["", "  ", "maybe", "Needs human review", "Not sure", "None", "n/a", None])
def test_a_blank_unknown_or_missing_flag_fails_closed_as_unclear(flag):
    result = run(PreCreateRequest("dashboard", "Unit Hub"), current_index(dashboard_with_flag(flag)), **POLICY)
    assert result["human_review_required"] is True
    assert "review.flag-unclear" in result["reason_codes"]
    assert "review.record-flagged" not in result["reason_codes"]


def test_prompt_records_use_their_own_review_column():
    result = run(PreCreateRequest("prompt", "Curriculum readiness check"), **POLICY)
    assert result["identity"]["matches"][0]["record"]["Human Review Required?"] == "Yes if owner unclear"
    assert result["human_review_required"] is True
    assert "review.record-flagged" in result["reason_codes"]


def test_a_flagged_parent_database_requires_review_too():
    tabs = {
        **SAMPLE_TABS,
        "Database Registry": tab(
            ["Database Name", "Database ID", "Source-of-Truth Role", "Owner Dashboard", "Human Review Needed?"],
            ["DM Units", "id-1", "Operational source", "Curriculum Source Control", "Yes"],
        ),
    }
    result = run(PreCreateRequest("field", "Brand New Field", database="DM Units"), current_index(tabs), **POLICY)
    assert result["outcome"] == "no-cached-match"
    assert result["human_review_required"] is True
    assert "review.record-flagged" in result["reason_codes"]


# --- invalid requests ------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_, codes",
    [
        (PreCreateRequest("schema", "X"), ["request.unsupported-kind"]),
        (PreCreateRequest("", "X"), ["request.unsupported-kind"]),
        (PreCreateRequest("dashboard", ""), ["request.empty-name"]),
        (PreCreateRequest("dashboard", "   \t"), ["request.empty-name"]),
        (PreCreateRequest("dashboard", None), ["request.empty-name"]),
        (PreCreateRequest("dashboard", 42), ["request.empty-name"]),
        (PreCreateRequest("field", "X"), ["request.database-required"]),
        (PreCreateRequest("field", "X", database="  "), ["request.database-required"]),
        (PreCreateRequest("dashboard", "X", database="DM Units"), ["request.database-not-applicable"]),
        (PreCreateRequest("dashboard", "X", information_type=""), ["request.empty-information-type"]),
        (PreCreateRequest("dashboard", "X", information_type="  "), ["request.empty-information-type"]),
        (
            PreCreateRequest("field", "", information_type=""),
            ["request.empty-name", "request.database-required", "request.empty-information-type"],
        ),
    ],
)
def test_invalid_requests_are_manual_review_and_look_nothing_up(request_, codes):
    spy = LookupOnly(sample_index())
    result = precreate_preflight(spy, request_, **POLICY)
    assert result["outcome"] == "manual-review"
    assert result["reason_codes"] == codes
    assert result["human_review_required"] is True
    assert result["identity"] == {"status": "not-evaluated", "matches": []}
    assert result["duplicate_risk"]["hits"] == []
    assert result["routing"] == {"routes": []}
    assert result["currentness"]["status"] == "not-evaluated"
    assert result["live_verification_required"] is True
    assert result["authorizes_mutation"] is False
    assert spy.calls == []
    json.dumps(result)


def test_a_non_string_request_value_is_echoed_safely():
    result = run(PreCreateRequest("dashboard", 42), **POLICY)
    assert result["request"]["name"] == "<int>"


def test_programming_errors_raise_instead_of_returning_a_verdict():
    index = current_index()
    with pytest.raises(TypeError):
        precreate_preflight(index, {"kind": "dashboard", "name": "X"})
    with pytest.raises(ValueError, match="timezone-aware"):
        precreate_preflight(index, PreCreateRequest("dashboard", "X"), now=datetime(2026, 10, 13, 12, 0), max_age=MAX_AGE)
    with pytest.raises(ValueError, match="timezone-aware"):
        precreate_preflight(index, PreCreateRequest("dashboard", "X"), now="2026-10-13", max_age=MAX_AGE)
    for bad in (timedelta(0), timedelta(hours=-1), 3600):
        with pytest.raises(ValueError, match="positive timedelta"):
            precreate_preflight(index, PreCreateRequest("dashboard", "X"), now=NOW, max_age=bad)


# --- outcome precedence ----------------------------------------------------------------


def test_outcome_precedence_is_manual_then_duplicate_then_match_then_stale_then_none():
    twins = dashboard_tabs(
        ["Readiness", "", "", "Source of Truth", "A", "No"],
        ["readiness", "", "", "Source of Truth", "B", "No"],
    )
    stale_index = WithLog(sample_index(), explicit_log(utc="2026-01-01T00:00:00Z"))
    current = current_index()

    # ambiguous identity outranks a watchlist hit on the same name
    ambiguous_and_hit = run(PreCreateRequest("dashboard", "Readiness"), current_index(twins), **POLICY)
    assert ambiguous_and_hit["duplicate_risk"]["hit_count"] == 1
    assert ambiguous_and_hit["outcome"] == "manual-review"
    # a watchlist hit outranks an exact match
    hit_and_match = run(PreCreateRequest("field", "Generation Gate", database="DM Units"), current, **POLICY)
    assert hit_and_match["identity"]["status"] == "exact-match"
    assert hit_and_match["outcome"] == "duplicate-risk-review"
    # an exact match outranks a stale cache
    match_and_stale = run(PreCreateRequest("dashboard", "Curriculum Source Control"), stale_index, **POLICY)
    assert match_and_stale["currentness"]["status"] == "stale"
    assert match_and_stale["outcome"] == "existing-match"
    # staleness outranks "no match"
    none_and_stale = run(PreCreateRequest("dashboard", "Brand New"), stale_index, **POLICY)
    assert none_and_stale["outcome"] == "stale-or-unverified"
    # and only a current cache with no findings yields no-cached-match
    assert run(PreCreateRequest("dashboard", "Brand New"), current, **POLICY)["outcome"] == "no-cached-match"


# --- the non-authority contract, determinism, and purity -------------------------------

SCENARIOS = {
    "existing-match": (PreCreateRequest("dashboard", "Curriculum Source Control"), None),
    "duplicate-risk-review": (PreCreateRequest("field", "Readiness", database="DM Units"), None),
    "no-cached-match": (PreCreateRequest("dashboard", "Brand New"), None),
    "stale-or-unverified": (PreCreateRequest("dashboard", "Brand New"), "no-log"),
    "manual-review": (PreCreateRequest("dashboard", ""), None),
}


def scenario_result(outcome):
    request_, mode = SCENARIOS[outcome]
    index = LookupOnly(sample_index()) if mode == "no-log" else current_index()
    return precreate_preflight(index, request_, **POLICY)


def test_the_scenarios_cover_exactly_the_five_documented_outcomes():
    assert set(SCENARIOS) == set(OUTCOMES) == set(NEXT_STEP)
    assert len(OUTCOMES) == 5
    for outcome in OUTCOMES:
        assert scenario_result(outcome)["outcome"] == outcome


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_no_outcome_authorizes_anything_or_waives_live_verification(outcome):
    result = scenario_result(outcome)
    assert result["authorizes_mutation"] is False
    assert result["live_verification_required"] is True
    assert result["navigation_warning"] == NAVIGATION_WARNING
    assert result["next_step"] == NEXT_STEP[outcome]
    assert result["contract"] == "navigation-index-precreate-preflight"
    assert "verify" in result["next_step"].lower()
    flat = json.dumps(result).lower()
    for forbidden in ("write_allowed", "can_create", "safe_to_create", "approved", "authorized\": true"):
        assert forbidden not in flat
    json.loads(json.dumps(result))


def test_the_five_outcome_names_are_the_finite_documented_set():
    assert OUTCOMES == (
        "existing-match",
        "duplicate-risk-review",
        "no-cached-match",
        "stale-or-unverified",
        "manual-review",
    )
    assert PREFLIGHT_KINDS == ("dashboard", "database", "field", "workflow", "prompt")


def test_reason_codes_are_deterministic_deduplicated_and_from_the_documented_vocabulary():
    vocabulary = {value for name, value in vars(precreate).items() if name.startswith("R_")}
    for outcome in OUTCOMES:
        first = scenario_result(outcome)
        second = scenario_result(outcome)
        assert first == second
        codes = first["reason_codes"]
        assert codes == list(dict.fromkeys(codes))
        assert set(codes) <= vocabulary
        assert codes


def test_the_preflight_does_not_mutate_the_cache_and_results_do_not_alias_it():
    tabs = copy.deepcopy(SAMPLE_TABS)
    index = current_index(tabs)
    first = precreate_preflight(index, PreCreateRequest("field", "Readiness", database="DM Units"), **POLICY)
    expected = copy.deepcopy(first)
    first["identity"]["matches"][0]["record"]["Canonical Meaning"] = "tampered"
    first["duplicate_risk"]["hits"][0]["record"]["Risk Type"] = "tampered"
    first["routing"]["routes"].clear()
    assert tabs == SAMPLE_TABS
    assert precreate_preflight(index, PreCreateRequest("field", "Readiness", database="DM Units"), **POLICY) == expected


def test_precreate_module_is_pure_it_imports_no_io_network_or_github_code():
    tree = ast.parse((PACKAGE_DIR / "precreate.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
    assert imported <= {"__future__", "unicodedata", "dataclasses", "datetime", "typing", ".records"}


def test_the_preflight_performs_no_network_io(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    for outcome in OUTCOMES:
        scenario_result(outcome)


def test_the_preflight_source_has_no_sheet_or_notion_api_calls():
    source = (PACKAGE_DIR / "precreate.py").read_text()
    for needle in ("spreadsheets", "googleapiclient", "notion_client", "requests", "urllib", "batchUpdate"):
        assert needle not in source


# --- #3306 compatibility (activates once get_refresh_log exists on NavigationIndex) ----

needs_refresh_log = pytest.mark.skipif(
    not hasattr(NavigationIndex, "get_refresh_log"), reason="requires NavigationIndex.get_refresh_log (#3306)"
)
LOG_HEADER = [
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


def real_index_with_log(*data_rows):
    return sample_index({**SAMPLE_TABS, "Refresh Log": tab(LOG_HEADER, *data_rows)})


def log_row(refresh_date):
    return [refresh_date, "v0.1.2", "Operator A", "1", "2", "3", "4", "", "", "note"]


@needs_refresh_log
def test_real_refresh_log_with_explicit_recent_timestamps_makes_the_cache_current():
    index = real_index_with_log(log_row("2026-10-12 06:00 UTC"), log_row("2026-10-13 06:00 UTC"))
    result = run(PreCreateRequest("dashboard", "Brand New Dashboard"), index, **POLICY)
    assert result["currentness"]["status"] == "within-policy"
    assert result["currentness"]["latest_refresh_utc"] == "2026-10-13T06:00:00Z"
    assert result["outcome"] == "no-cached-match"


@needs_refresh_log
def test_real_refresh_log_in_the_current_live_shape_leaves_currentness_unverified():
    # One explicit-UTC row followed by zone-less rows: the latest refresh time is not provable.
    index = real_index_with_log(
        log_row("2026-07-04 16:04 UTC"), log_row("2026-08-09 16:10:03.654"), log_row("2026-08-09 16:37:20.339")
    )
    result = run(PreCreateRequest("dashboard", "Brand New Dashboard"), index, **POLICY)
    assert result["currentness"]["reason_code"] == "currentness.refresh-time-unresolved"
    assert result["currentness"]["detail"] == "timestamps-not-all-explicit"
    assert result["currentness"]["latest_refresh_by_source_row"]["raw"] == "2026-08-09 16:37:20.339"
    assert result["outcome"] == "stale-or-unverified"


@needs_refresh_log
def test_real_empty_refresh_log_maps_missing_chronology_to_unverified():
    result = run(PreCreateRequest("dashboard", "Brand New Dashboard"), real_index_with_log(), **POLICY)
    assert result["currentness"]["reason_code"] == "currentness.no-refresh-records"
    assert result["outcome"] == "stale-or-unverified"
