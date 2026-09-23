from __future__ import annotations

import pytest

from scripts.agent_os_github_issue_provider.check_run_resolution import authoritative_check_runs


def run(name="gate", conclusion="success", *, run_id=1, completed="2026-09-01T10:00:00Z", app="actions"):
    return {"id": run_id, "name": name, "status": "completed", "conclusion": conclusion, "completed_at": completed, "app": {"slug": app}}


def test_single_check_is_preserved():
    assert authoritative_check_runs([run()])[0]["conclusion"] == "success"


def test_newer_success_replaces_older_same_name_failure():
    result = authoritative_check_runs([
        run(conclusion="failure", run_id=1, completed="2026-09-01T09:00:00Z"),
        run(conclusion="success", run_id=2, completed="2026-09-01T10:00:00Z"),
    ])
    assert len(result) == 1
    assert result[0]["conclusion"] == "success"


def test_newer_failure_replaces_older_same_name_success():
    result = authoritative_check_runs([
        run(conclusion="success", run_id=1, completed="2026-09-01T09:00:00Z"),
        run(conclusion="failure", run_id=2, completed="2026-09-01T10:00:00Z"),
    ])
    assert result[0]["conclusion"] == "failure"


def test_cancelled_or_skipped_history_does_not_override_newer_success():
    result = authoritative_check_runs([
        run(conclusion="cancelled", run_id=1, completed="2026-09-01T08:00:00Z"),
        run(conclusion="skipped", run_id=2, completed="2026-09-01T09:00:00Z"),
        run(conclusion="success", run_id=3, completed="2026-09-01T10:00:00Z"),
    ])
    assert result[0]["conclusion"] == "success"


def test_distinct_check_names_remain_visible():
    result = authoritative_check_runs([run("a"), run("b", conclusion="failure", run_id=2)])
    assert {item["name"] for item in result} == {"a", "b"}


def test_same_name_from_distinct_apps_remains_distinct():
    result = authoritative_check_runs([run(app="actions"), run(app="other", run_id=2)])
    assert len(result) == 2


def test_duplicate_without_ordering_metadata_fails_closed():
    first = run(run_id=1)
    second = run(run_id=2)
    first.pop("completed_at")
    first.pop("id")
    with pytest.raises(ValueError):
        authoritative_check_runs([first, second])
