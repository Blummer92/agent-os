from __future__ import annotations

from tests.agent_os_github_issue_provider.test_sprint_evidence import _collect, _response


def _run(
    name: str = "validation-gate",
    conclusion: str = "success",
    *,
    run_id: int = 1,
    completed_at: str = "2026-09-01T10:00:00Z",
    app: str = "actions",
    status: str = "completed",
):
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "completed_at": completed_at,
        "app": {"slug": app},
    }


def _checks(*runs):
    return {"checks": [_response({"check_runs": list(runs)})]}


def test_newer_success_removes_false_red_from_older_same_check_failure():
    collection, _ = _collect(
        scripts=_checks(
            _run(conclusion="failure", run_id=1, completed_at="2026-09-01T09:00:00Z"),
            _run(conclusion="success", run_id=2, completed_at="2026-09-01T10:00:00Z"),
        )
    )

    pull = collection.candidates[0].pull_request
    assert pull is not None
    assert pull.checks_status == "passing"
    assert len(pull.checks) == 1
    assert pull.checks[0].conclusion == "success"


def test_newer_failure_remains_failing_for_same_logical_check():
    collection, _ = _collect(
        scripts=_checks(
            _run(conclusion="success", run_id=1, completed_at="2026-09-01T09:00:00Z"),
            _run(conclusion="failure", run_id=2, completed_at="2026-09-01T10:00:00Z"),
        )
    )

    pull = collection.candidates[0].pull_request
    assert pull is not None
    assert pull.checks_status == "failing"
    assert len(pull.checks) == 1
    assert pull.checks[0].conclusion == "failure"


def test_distinct_producer_apps_with_same_name_remain_independent():
    collection, _ = _collect(
        scripts=_checks(
            _run(app="actions", conclusion="success", run_id=1),
            _run(app="other", conclusion="failure", run_id=2),
        )
    )

    pull = collection.candidates[0].pull_request
    assert pull is not None
    assert pull.checks_status == "failing"
    assert len(pull.checks) == 2


def test_ambiguous_duplicate_ordering_fails_closed_to_unknown():
    first = _run(run_id=1)
    second = _run(run_id=2)
    first.pop("completed_at")
    first.pop("id")

    collection, _ = _collect(scripts=_checks(first, second))

    pull = collection.candidates[0].pull_request
    assert pull is not None
    assert pull.checks is None
    assert pull.checks_status == "unknown"
    assert "checks:unknown" in collection.candidates[0].reason_codes
