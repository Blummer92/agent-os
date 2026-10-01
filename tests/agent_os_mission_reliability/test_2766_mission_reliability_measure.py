"""Focused tests for the #2766 mission-reliability read-only measurement.

Proves, against synthetic fixture data, that:
- derivation reports the right conversions, counts, and elapsed-time
  distributions over normalized mission records;
- fields without durable evidence stay "unknown" and are never estimated;
- the read-only GitHub acquisition links PRs to issues through the canonical
  closing-keyword parser and the agent/<issue>-<slug> branch convention, marks
  follow-up PRs as repairs, and never attempts a write.
"""
from __future__ import annotations

import sys
from pathlib import Path

# CI runs each package's tests with only that package's src on sys.path, so the
# repo root is added here (same sys.path.insert convention as commit 891dc771).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from scripts.agent_os_mission_reliability import (
    acquire_mission_records,
    derive_mission_reliability,
)

WINDOW = "test-window 2026-09-01..2026-09-21, owner/repo, issues 1,2,3"


def _mission(issue_number: int, **overrides) -> dict:
    record = {
        "issue_number": issue_number,
        "admitted": True,
        "admitted_at": "2026-09-01T00:00:00Z",
        "issue_state": "open",
        "issue_closed_at": None,
        "implementation_prs": [],
        "requested_items": None,
        "delivered_items": None,
        "terminal_state": "unknown",
        "user_interventions": None,
        "continuation_prompts": None,
        "bug_family": None,
        "prior_completed_fix_issue": None,
        "finding_issue": None,
        "retest_at": None,
    }
    record.update(overrides)
    return record


def _pr(number: int, created_at: str, merged: bool, merged_at=None, repair=False) -> dict:
    return {
        "number": number,
        "created_at": created_at,
        "merged": merged,
        "merged_at": merged_at,
        "repair": repair,
        "first_terminal_validation_at": None,
    }


def _by_name(report: dict, name: str) -> dict:
    for metric in report["metrics"]:
        if metric["metric"] == name:
            return metric
    raise AssertionError(f"metric {name!r} missing from report")


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def test_issue_to_pr_conversion_and_pr_merge_conversion() -> None:
    records = [
        _mission(1, implementation_prs=[
            _pr(101, "2026-09-02T00:00:00Z", True, "2026-09-03T00:00:00Z"),
        ]),
        _mission(2, implementation_prs=[
            _pr(102, "2026-09-04T00:00:00Z", False),
        ]),
        _mission(3),  # no implementation PR
    ]
    report = derive_mission_reliability(records, window=WINDOW)

    issue_to_pr = _by_name(report, "issue_to_pr_conversion")
    assert issue_to_pr["numerator"] == 2
    assert issue_to_pr["denominator"] == 3
    assert issue_to_pr["ratio"] == pytest.approx(2 / 3)
    elapsed = issue_to_pr["elapsed_hours"]
    assert elapsed["n"] == 2
    assert elapsed["median"] == pytest.approx(48.0)  # 24h and 72h

    pr_merge = _by_name(report, "pr_merge_conversion")
    assert pr_merge["numerator"] == 1
    assert pr_merge["denominator"] == 2
    assert pr_merge["ratio"] == pytest.approx(0.5)
    assert pr_merge["elapsed_hours"]["n"] == 1
    assert pr_merge["elapsed_hours"]["median"] == pytest.approx(24.0)


def test_repair_attempts_per_delivered_and_reentries() -> None:
    records = [
        _mission(1, implementation_prs=[
            _pr(101, "2026-09-02T00:00:00Z", True, "2026-09-03T00:00:00Z"),
            _pr(103, "2026-09-05T00:00:00Z", True, "2026-09-06T00:00:00Z", repair=True),
        ]),
        _mission(2, implementation_prs=[
            _pr(104, "2026-09-04T00:00:00Z", True, "2026-09-05T00:00:00Z"),
        ]),
    ]
    report = derive_mission_reliability(records, window=WINDOW)

    repair = _by_name(report, "repair_attempts_per_delivered_implementation")
    assert repair["numerator"] == 1
    assert repair["denominator"] == 2
    assert repair["confidence"] == "weakly_evidenced"

    reentries = _by_name(report, "failed_repair_reentries")
    assert reentries["numerator"] == 1
    assert reentries["denominator"] == 2


def test_terminal_states_and_blocker_split_exclude_unknowns() -> None:
    records = [
        _mission(1, terminal_state="completed_truthful"),
        _mission(2, terminal_state="blocked_systemic"),
        _mission(3, terminal_state="blocked_item_local"),
        _mission(4, terminal_state="intermediate_stop"),
        _mission(5),  # unknown terminal state
    ]
    report = derive_mission_reliability(records, window=WINDOW)

    completion = _by_name(report, "truthful_terminal_completion")
    assert completion["numerator"] == 1
    assert completion["denominator"] == 4  # unknown excluded, not estimated
    assert completion["n"] == 4

    stops = _by_name(report, "intermediate_stops")
    assert stops["numerator"] == 1
    assert stops["denominator"] == 5

    split = _by_name(report, "blocker_split")
    assert "systemic=1" in split["note"]
    assert "item_local=1" in split["note"]


def test_unmeasurable_fields_stay_unknown_without_durable_evidence() -> None:
    records = [_mission(1, terminal_state="completed_truthful")]
    report = derive_mission_reliability(records, window=WINDOW)

    interventions = _by_name(report, "user_interventions_per_completed_mission")
    assert interventions["confidence"] == "unknown"
    assert interventions["ratio"] is None

    continuations = _by_name(report, "continuation_prompts")
    assert continuations["confidence"] == "unknown"

    requested = _by_name(report, "requested_vs_delivered")
    assert requested["confidence"] == "unknown"

    validation = _by_name(report, "pr_to_first_terminal_validation")
    assert validation["confidence"] == "unknown"


def test_interventions_and_requested_delivered_when_evidence_exists() -> None:
    records = [
        _mission(1, terminal_state="completed_truthful", user_interventions=2,
                 requested_items=10, delivered_items=8),
        _mission(2, terminal_state="completed_truthful", user_interventions=0,
                 requested_items=5, delivered_items=5),
    ]
    report = derive_mission_reliability(records, window=WINDOW)

    interventions = _by_name(report, "user_interventions_per_completed_mission")
    assert interventions["confidence"] == "measured"
    assert interventions["numerator"] == 2
    assert interventions["denominator"] == 2

    requested = _by_name(report, "requested_vs_delivered")
    assert requested["confidence"] == "measured"
    assert requested["numerator"] == 13
    assert requested["denominator"] == 15


def test_merge_to_issue_convergence_time() -> None:
    records = [
        _mission(1, issue_state="closed", issue_closed_at="2026-09-04T12:00:00Z",
                 implementation_prs=[
                     _pr(101, "2026-09-02T00:00:00Z", True, "2026-09-04T00:00:00Z"),
                 ]),
        _mission(2, issue_state="open",
                 implementation_prs=[
                     _pr(102, "2026-09-02T00:00:00Z", True, "2026-09-04T00:00:00Z"),
                 ]),
    ]
    report = derive_mission_reliability(records, window=WINDOW)

    convergence = _by_name(report, "merge_to_issue_convergence")
    assert convergence["numerator"] == 1
    assert convergence["denominator"] == 2
    assert convergence["elapsed_hours"]["median"] == pytest.approx(12.0)


def test_bug_family_recurrence_and_finding_lineage() -> None:
    records = [
        _mission(1, bug_family="validation-timeout", prior_completed_fix_issue=7,
                 retest_at="2026-09-10T00:00:00Z"),
        _mission(2, bug_family="validation-timeout"),  # first occurrence, no prior fix
        _mission(3, finding_issue=42,
                 implementation_prs=[
                     _pr(103, "2026-09-03T00:00:00Z", True, "2026-09-04T00:00:00Z"),
                 ],
                 retest_at="2026-09-11T00:00:00Z"),
        _mission(4, finding_issue=43),  # finding with no implementation
    ]
    report = derive_mission_reliability(records, window=WINDOW)

    recurrence = _by_name(report, "bug_family_recurrence")
    assert recurrence["numerator"] == 1  # only mission 1 has a prior completed fix
    assert recurrence["denominator"] == 4

    finding = _by_name(report, "finding_to_implementation_to_retest")
    assert finding["numerator"] == 1
    assert finding["denominator"] == 2


def test_derivation_rejects_malformed_records() -> None:
    with pytest.raises(TypeError):
        derive_mission_reliability([{"admitted": True}], window=WINDOW)
    with pytest.raises(TypeError):
        derive_mission_reliability(
            [_mission(1, terminal_state="bogus")], window=WINDOW
        )
    with pytest.raises(TypeError):
        derive_mission_reliability([_mission(1)], window="")


def test_elapsed_distribution_reports_median_and_p90() -> None:
    records = [
        _mission(1, implementation_prs=[
            _pr(101, "2026-09-01T00:00:00Z", True, "2026-09-01T01:00:00Z"),
        ]),
        _mission(2, implementation_prs=[
            _pr(102, "2026-09-01T00:00:00Z", True, "2026-09-01T10:00:00Z"),
        ]),
        _mission(3, implementation_prs=[
            _pr(103, "2026-09-01T00:00:00Z", True, "2026-09-02T00:00:00Z"),
        ]),
    ]
    report = derive_mission_reliability(records, window=WINDOW)
    elapsed = _by_name(report, "pr_merge_conversion")["elapsed_hours"]
    assert elapsed["n"] == 3
    assert elapsed["min"] == pytest.approx(1.0)
    assert elapsed["median"] == pytest.approx(10.0)
    assert elapsed["p90"] == pytest.approx(24.0)
    assert elapsed["max"] == pytest.approx(24.0)


# ---------------------------------------------------------------------------
# Read-only acquisition
# ---------------------------------------------------------------------------


class _FakeGitHub:
    """Read-only fake transport; records every path and performs no writes."""

    def __init__(self, issues: dict, pr_pages: list):
        self.issues = issues
        self.pr_pages = pr_pages
        self.paths: list[str] = []

    def __call__(self, path: str, params):
        assert path.startswith("/repos/"), f"unexpected path {path!r}"
        self.paths.append(path)
        if path.endswith("/pulls"):
            page = (params or {}).get("page", 1)
            prs = self.pr_pages[page - 1] if page - 1 < len(self.pr_pages) else []
            # The real /pulls list view omits merged/merged_at; detail carries them.
            return [
                {k: v for k, v in pr.items() if k not in ("merged", "merged_at")}
                for pr in prs
            ]
        if "/pulls/" in path:
            number = int(path.rsplit("/", 1)[-1])
            for page in self.pr_pages:
                for pr in page:
                    if pr["number"] == number:
                        return dict(pr)
            raise AssertionError(f"unknown PR detail path {path!r}")
        number = int(path.rsplit("/", 1)[-1])
        return self.issues[number]


def _issue(number: int, state: str = "open", closed_at=None) -> dict:
    return {"number": number, "state": state, "closed_at": closed_at}


def _pr_payload(number: int, title: str, body: str, created_at: str,
                merged: bool, merged_at=None, head_ref: str = "main") -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "created_at": created_at,
        "merged": merged,
        "merged_at": merged_at,
        "head": {"ref": head_ref},
    }


def test_acquire_links_prs_by_closing_keyword_and_branch() -> None:
    fake = _FakeGitHub(
        issues={1: _issue(1, "closed", "2026-09-04T00:00:00Z"), 2: _issue(2)},
        pr_pages=[[
            _pr_payload(101, "Fix #1: first attempt",
                        "Fixes #1\n\n## Summary", "2026-09-02T00:00:00Z",
                        True, "2026-09-03T00:00:00Z", head_ref="agent/1-first"),
            _pr_payload(102, "Fix #1: repair",
                        "Fixes #1\n\n## Summary", "2026-09-05T00:00:00Z",
                        True, "2026-09-06T00:00:00Z", head_ref="agent/1-repair"),
            _pr_payload(103, "Unrelated docs change", "Docs only",
                        "2026-09-03T00:00:00Z", True, "2026-09-03T01:00:00Z",
                        head_ref="agent/2-docs"),
        ]],
    )
    frozen = acquire_mission_records(
        fake,
        owner="owner",
        repository="repo",
        issue_numbers=[1, 2],
        admitted_map={1: {"admitted": True, "admitted_at": "2026-09-01T00:00:00Z"}},
    )
    by_issue = {r["issue_number"]: r for r in frozen["records"]}

    record_1 = by_issue[1]
    assert record_1["admitted"] is True
    assert record_1["issue_state"] == "closed"
    pr_numbers = [pr["number"] for pr in record_1["implementation_prs"]]
    assert pr_numbers == [101, 102]
    assert record_1["implementation_prs"][0]["repair"] is False
    assert record_1["implementation_prs"][1]["repair"] is True
    assert record_1["implementation_prs"][0]["merged_at"] == "2026-09-03T00:00:00Z"

    # PR 103 linked only via the agent/<issue>- branch convention.
    record_2 = by_issue[2]
    assert [pr["number"] for pr in record_2["implementation_prs"]] == [103]
    assert record_2["admitted"] is False

    # Fields without durable evidence stay unknown/None.
    assert record_1["terminal_state"] == "unknown"
    assert record_1["user_interventions"] is None
    assert record_1["requested_items"] is None


def test_acquire_reports_issue_state_unknown_for_unexpected_state() -> None:
    fake = _FakeGitHub(
        issues={9: {"number": 9, "state": "locked", "closed_at": None}},
        pr_pages=[[]],
    )
    frozen = acquire_mission_records(
        fake, owner="o", repository="r", issue_numbers=[9]
    )
    assert frozen["records"][0]["issue_state"] == "unknown"


def test_acquire_is_read_only_and_bounded() -> None:
    calls: list[tuple[str, object]] = []

    def read_json(path: str, params):
        calls.append((path, params))
        if path.endswith("/pulls"):
            return []
        return _issue(1)

    acquire_mission_records(read_json, owner="o", repository="r", issue_numbers=[1])
    # Only GET-style paths were touched; no write-shaped path appears.
    for path, _ in calls:
        assert path.startswith("/repos/o/r/")
        assert "/pulls" in path or "/issues/" in path
    # Bounded window reads the newest PRs first so recent linkage is covered.
    pulls_calls = [params for path, params in calls if path.endswith("/pulls")]
    assert pulls_calls and all(
        params["direction"] == "desc" for params in pulls_calls
    )
