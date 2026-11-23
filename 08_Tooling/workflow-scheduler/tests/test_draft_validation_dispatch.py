from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from workflow_scheduler.governance.draft_validation_dispatch import (
    MAX_RUNS_INSPECTED,
    PullRequestState,
    WorkflowRunSummary,
    correlate_run,
    execute_dispatch,
    find_existing_receipt,
    receipt_from_job_outputs,
    render_receipt_comment,
    select_duplicate_run,
    verify_pr_state,
)

HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40
NOW = datetime(2026, 10, 21, 14, 0, 0, tzinfo=timezone.utc)
TRIGGER_ID = "issue-comment-trigger:" + "c" * 64
REPOSITORY = "Blummer92/agent-os"


def pr(**overrides: object) -> PullRequestState:
    values = dict(
        state="open",
        draft=True,
        base_ref="main",
        head_ref="agent/2411-example",
        head_sha=HEAD_SHA,
        head_repo_full_name=REPOSITORY,
    )
    values.update(overrides)
    return PullRequestState(**values)  # type: ignore[arg-type]


def run(**overrides: object) -> WorkflowRunSummary:
    values = dict(
        run_id=101,
        url="https://github.com/Blummer92/agent-os/actions/runs/101",
        head_sha=HEAD_SHA,
        created_at=NOW + timedelta(seconds=5),
        status="completed",
        conclusion="success",
    )
    values.update(overrides)
    return WorkflowRunSummary(**values)  # type: ignore[arg-type]


def transport(**overrides: object) -> dict:
    values = dict(
        status="accepted",
        reason="accepted-draft-validation-envelope",
        repository="Blummer92/agent-os",
        issue_number=2410,
        comment_id=7001,
        actor="Blummer92",
        logical_trigger_id_or_none=TRIGGER_ID,
        draft_validation_pr_number_or_none=2411,
        draft_validation_head_sha_or_none=HEAD_SHA,
    )
    values.update(overrides)
    return values


class FakeClient:
    def __init__(self, pr_state: PullRequestState, run_pages: list[list[WorkflowRunSummary]]):
        self._pr = pr_state
        self._pages = list(run_pages)
        self.dispatch_calls: list[dict] = []
        self.raise_on_dispatch = False

    def get_pull_request(self, pr_number: int) -> PullRequestState:
        return self._pr

    def list_validation_dispatch_runs(self, *, head_ref: str) -> list[WorkflowRunSummary]:
        if self._pages:
            return self._pages.pop(0)
        return []

    def create_validation_dispatch(self, *, ref: str, pr_number: int, expected_head_sha: str) -> None:
        if self.raise_on_dispatch:
            raise RuntimeError("403 Resource not accessible by integration")
        self.dispatch_calls.append(
            {"ref": ref, "pr_number": pr_number, "expected_head_sha": expected_head_sha}
        )


# --- verify_pr_state -------------------------------------------------------


def test_verify_pr_state_accepts_exact_open_draft_on_main() -> None:
    assert verify_pr_state(pr(), pr_number=2411, expected_head_sha=HEAD_SHA, repository=REPOSITORY) == []


def test_verify_pr_state_rejects_each_bad_state() -> None:
    assert "pr-not-open" in verify_pr_state(pr(state="closed"), pr_number=2411, expected_head_sha=HEAD_SHA, repository=REPOSITORY)
    assert "pr-not-draft" in verify_pr_state(pr(draft=False), pr_number=2411, expected_head_sha=HEAD_SHA, repository=REPOSITORY)
    assert "pr-base-not-main" in verify_pr_state(pr(base_ref="develop"), pr_number=2411, expected_head_sha=HEAD_SHA, repository=REPOSITORY)
    assert "pr-head-mismatch" in verify_pr_state(pr(head_sha=OTHER_SHA), pr_number=2411, expected_head_sha=HEAD_SHA, repository=REPOSITORY)
    assert "pr-head-ref-missing" in verify_pr_state(pr(head_ref=None), pr_number=2411, expected_head_sha=HEAD_SHA, repository=REPOSITORY)


# --- dedupe / correlation ---------------------------------------------------


def test_select_duplicate_run_matches_exact_head_only() -> None:
    assert select_duplicate_run([run()], expected_head_sha=HEAD_SHA)[0] is not None
    assert select_duplicate_run([run(head_sha=OTHER_SHA)], expected_head_sha=HEAD_SHA) == (None, [])
    assert select_duplicate_run([], expected_head_sha=HEAD_SHA) == (None, [])


def test_correlate_run_requires_exactly_one_run_in_window() -> None:
    outcome, found = correlate_run([run()], expected_head_sha=HEAD_SHA, dispatched_at=NOW)
    assert outcome == "correlated" and found is not None and found.run_id == 101

    outcome, found = correlate_run([], expected_head_sha=HEAD_SHA, dispatched_at=NOW)
    assert outcome == "run-not-found" and found is None

    outcome, found = correlate_run(
        [run(), run(run_id=102)], expected_head_sha=HEAD_SHA, dispatched_at=NOW
    )
    assert outcome == "run-ambiguous" and found is None

    stale = run(created_at=NOW - timedelta(minutes=5))
    outcome, found = correlate_run([stale], expected_head_sha=HEAD_SHA, dispatched_at=NOW)
    assert outcome == "run-not-found" and found is None

    wrong_head = run(head_sha=OTHER_SHA)
    outcome, found = correlate_run([wrong_head], expected_head_sha=HEAD_SHA, dispatched_at=NOW)
    assert outcome == "run-not-found" and found is None


# --- execute_dispatch -------------------------------------------------------


def test_execute_dispatch_happy_path_correlates_run() -> None:
    client = FakeClient(pr(), run_pages=[[], [run()]])
    receipt = execute_dispatch(
        transport(), client, dispatched_at=NOW, poll_attempts=3, poll_interval_seconds=0, sleeper=lambda s: None
    )
    assert receipt["decision"] == "dispatched"
    assert receipt["run_id_or_none"] == 101
    assert receipt["validation_executed"] is False
    assert client.dispatch_calls == [
        {"ref": "agent/2411-example", "pr_number": 2411, "expected_head_sha": HEAD_SHA}
    ]


def test_execute_dispatch_rejects_unaccepted_transport_without_client_calls() -> None:
    client = FakeClient(pr(), run_pages=[])
    receipt = execute_dispatch(transport(status="blocked", reason="actor-not-allowed"), client)
    assert receipt["decision"] == "blocked"
    assert receipt["reason_codes"] == ["transport-not-accepted"]
    assert client.dispatch_calls == []


def test_execute_dispatch_blocks_stale_head() -> None:
    client = FakeClient(pr(head_sha=OTHER_SHA), run_pages=[])
    receipt = execute_dispatch(transport(), client, dispatched_at=NOW)
    assert receipt["decision"] == "blocked"
    assert "pr-head-mismatch" in receipt["reason_codes"]
    assert client.dispatch_calls == []


def test_execute_dispatch_blocks_ready_or_closed_pr() -> None:
    for state in (pr(draft=False), pr(state="closed")):
        client = FakeClient(state, run_pages=[])
        receipt = execute_dispatch(transport(), client, dispatched_at=NOW)
        assert receipt["decision"] == "blocked"
        assert client.dispatch_calls == []


def test_execute_dispatch_prevents_duplicate() -> None:
    client = FakeClient(pr(), run_pages=[[run(run_id=99)]])
    receipt = execute_dispatch(transport(), client, dispatched_at=NOW)
    assert receipt["decision"] == "duplicate"
    assert receipt["run_id_or_none"] == 99
    assert client.dispatch_calls == []


def test_execute_dispatch_fails_closed_when_dispatch_raises() -> None:
    client = FakeClient(pr(), run_pages=[[]])
    client.raise_on_dispatch = True
    receipt = execute_dispatch(transport(), client, dispatched_at=NOW)
    assert receipt["decision"] == "blocked"
    assert receipt["reason_codes"] == ["dispatch-failed"]
    assert receipt["run_id_or_none"] is None


def test_execute_dispatch_fails_closed_on_ambiguous_correlation() -> None:
    client = FakeClient(pr(), run_pages=[[], [run(), run(run_id=102)]])
    receipt = execute_dispatch(
        transport(), client, dispatched_at=NOW, poll_attempts=3, poll_interval_seconds=0, sleeper=lambda s: None
    )
    assert receipt["decision"] == "correlation-failed"
    assert receipt["reason_codes"] == ["run-ambiguous"]
    assert receipt["run_id_or_none"] is None


def test_execute_dispatch_fails_closed_when_no_run_appears() -> None:
    client = FakeClient(pr(), run_pages=[[], [], []])
    receipt = execute_dispatch(
        transport(), client, dispatched_at=NOW, poll_attempts=2, poll_interval_seconds=0, sleeper=lambda s: None
    )
    assert receipt["decision"] == "correlation-failed"
    assert receipt["reason_codes"] == ["run-not-found"]


# --- receipt rendering / idempotency ---------------------------------------


def test_receipt_comment_is_idempotently_detectable() -> None:
    receipt = execute_dispatch(
        transport(),
        FakeClient(pr(), run_pages=[[], [run()]]),
        dispatched_at=NOW,
        poll_attempts=3,
        poll_interval_seconds=0,
        sleeper=lambda s: None,
    )
    comment = render_receipt_comment(receipt)
    assert TRIGGER_ID in comment
    assert find_existing_receipt([comment], TRIGGER_ID, 7001) is True
    assert find_existing_receipt(["unrelated comment"], TRIGGER_ID, 7001) is False
    assert "not validation" in comment


# --- #2410 follow-up repairs -----------------------------------------------

FAILED = dict(status="completed", conclusion="failure")


def _dispatch(client: FakeClient, **kwargs: object) -> dict:
    return execute_dispatch(
        transport(), client, dispatched_at=NOW, poll_attempts=2, poll_interval_seconds=0,
        sleeper=lambda s: None, **kwargs,  # type: ignore[arg-type]
    )


# Repair 1: a retry after a blocked attempt must receive its own receipt.


def test_receipt_marker_is_per_comment_so_blocked_retry_gets_a_receipt() -> None:
    blocked = _dispatch(FakeClient(pr(draft=False), run_pages=[]))
    first = render_receipt_comment(blocked)
    assert blocked["decision"] == "blocked"
    # Same logical trigger, same comment: a workflow re-run must not double-post.
    assert find_existing_receipt([first], TRIGGER_ID, 7001) is True
    # Same logical trigger, new invoking comment (the owner's retry): not suppressed.
    assert find_existing_receipt([first], TRIGGER_ID, 7002) is False


# Repair 2: fork pull requests are rejected explicitly.


def test_fork_pull_request_is_rejected_without_dispatch() -> None:
    client = FakeClient(pr(head_repo_full_name="someone/agent-os"), run_pages=[])
    receipt = _dispatch(client)
    assert receipt["decision"] == "blocked"
    assert "pr-head-fork-not-supported" in receipt["reason_codes"]
    assert client.dispatch_calls == []


def test_deleted_head_repository_is_rejected_as_fork() -> None:
    client = FakeClient(pr(head_repo_full_name=None), run_pages=[])
    receipt = _dispatch(client)
    assert "pr-head-fork-not-supported" in receipt["reason_codes"]
    assert client.dispatch_calls == []


def test_same_repository_match_is_case_insensitive() -> None:
    client = FakeClient(pr(head_repo_full_name="blummer92/AGENT-OS"), run_pages=[[], [run()]])
    assert _dispatch(client)["decision"] == "dispatched"


# Repair 3: failed/cancelled dedup is controlled retry, never duplicate active runs.


def test_failed_prior_run_allows_one_controlled_retry() -> None:
    client = FakeClient(pr(), run_pages=[[run(run_id=90, **FAILED)], [run(run_id=90, **FAILED), run(run_id=91, status="queued", conclusion=None)]])
    receipt = _dispatch(client)
    assert receipt["decision"] == "dispatched"
    assert receipt["run_id_or_none"] == 91  # the new run, not the pre-existing failed one
    assert len(client.dispatch_calls) == 1


def test_cancelled_and_timed_out_runs_are_retryable() -> None:
    for conclusion in ("cancelled", "timed_out", "startup_failure"):
        prior = run(run_id=90, status="completed", conclusion=conclusion)
        client = FakeClient(pr(), run_pages=[[prior], [prior, run(run_id=91)]])
        assert _dispatch(client)["decision"] == "dispatched"


def test_active_run_blocks_dispatch_even_when_a_failed_run_exists() -> None:
    for status in ("queued", "in_progress", "waiting", "requested", "pending"):
        active = run(run_id=95, status=status, conclusion=None)
        client = FakeClient(pr(), run_pages=[[run(run_id=90, **FAILED), active]])
        receipt = _dispatch(client)
        assert receipt["decision"] == "duplicate"
        assert receipt["reason_codes"] == ["duplicate-active-run"]
        assert receipt["run_id_or_none"] == 95
        assert client.dispatch_calls == []


def test_successful_or_final_prior_run_is_a_duplicate_not_retried() -> None:
    for conclusion in ("success", "skipped", "neutral", "action_required"):
        client = FakeClient(pr(), run_pages=[[run(run_id=90, status="completed", conclusion=conclusion)]])
        receipt = _dispatch(client)
        assert receipt["decision"] == "duplicate"
        assert receipt["reason_codes"] == ["duplicate-dispatch-prevented"]
        assert client.dispatch_calls == []


def test_retry_budget_is_bounded_per_head() -> None:
    failed = [run(run_id=80 + i, **FAILED) for i in range(3)]
    client = FakeClient(pr(), run_pages=[failed])
    receipt = _dispatch(client)
    assert receipt["decision"] == "blocked"
    assert receipt["reason_codes"] == ["retry-limit-reached"]
    assert client.dispatch_calls == []
    two = FakeClient(pr(), run_pages=[failed[:2], failed[:2] + [run(run_id=99)]])
    assert _dispatch(two)["decision"] == "dispatched"


def test_failed_run_on_other_head_does_not_consume_budget_or_block() -> None:
    other = [run(run_id=70 + i, head_sha=OTHER_SHA, **FAILED) for i in range(5)]
    client = FakeClient(pr(), run_pages=[other, other + [run(run_id=99)]])
    assert _dispatch(client)["decision"] == "dispatched"


def test_preexisting_recent_failed_run_is_not_correlated_as_the_new_run() -> None:
    recent_failed = run(run_id=90, created_at=NOW - timedelta(seconds=3), **FAILED)
    # The new run never appears: correlation must fail closed, not adopt run 90.
    client = FakeClient(pr(), run_pages=[[recent_failed], [recent_failed], [recent_failed]])
    receipt = _dispatch(client)
    assert receipt["decision"] == "correlation-failed"
    assert receipt["reason_codes"] == ["run-not-found"]
    assert receipt["run_id_or_none"] is None
    outcome, found = correlate_run(
        [recent_failed], expected_head_sha=HEAD_SHA, dispatched_at=NOW, exclude_run_ids=frozenset()
    )
    assert outcome == "correlated" and found is not None  # excluded only when known pre-dispatch


# Repair 4: detailed failure reasons survive into the receipt.


class _HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def test_dispatch_failure_preserves_http_status_reason() -> None:
    class Failing(FakeClient):
        def create_validation_dispatch(self, **kwargs: object) -> None:
            raise _HttpError(403)

    receipt = _dispatch(Failing(pr(), run_pages=[[]]))
    assert receipt["reason_codes"] == ["dispatch-failed", "dispatch-failed-http-403"]
    assert receipt["decision"] == "blocked"


def test_pr_and_run_lookup_failures_are_receipted_not_raised() -> None:
    class PrFails(FakeClient):
        def get_pull_request(self, pr_number: int) -> PullRequestState:
            raise _HttpError(404)

    assert _dispatch(PrFails(pr(), run_pages=[]))["reason_codes"] == ["pr-lookup-failed", "pr-lookup-failed-http-404"]

    class RunsFail(FakeClient):
        def list_validation_dispatch_runs(self, **kwargs: object) -> list[WorkflowRunSummary]:
            raise RuntimeError("boom")

    assert _dispatch(RunsFail(pr(), run_pages=[]))["reason_codes"] == ["run-lookup-failed"]


def _outputs(**overrides: str) -> dict:
    values = dict(
        decision="blocked",
        reason_codes_csv="pr-not-draft,pr-head-mismatch",
        run_id="",
        observed_head_sha=OTHER_SHA,
        run_status="",
        run_conclusion="",
        dispatch_trigger_id=TRIGGER_ID,
    )
    values.update(overrides)
    return values


def test_receipt_job_keeps_reason_codes_and_observed_head() -> None:
    receipt = receipt_from_job_outputs(transport(), **_outputs())
    assert receipt["decision"] == "blocked"
    assert receipt["reason_codes"] == ["pr-not-draft", "pr-head-mismatch"]
    assert receipt["observed_head_sha"] == OTHER_SHA
    assert receipt["comment_id"] == 7001
    comment = render_receipt_comment(receipt)
    assert "pr-not-draft,pr-head-mismatch" in comment
    assert OTHER_SHA in comment


def test_receipt_job_carries_run_identity_and_status() -> None:
    receipt = receipt_from_job_outputs(
        transport(),
        **_outputs(decision="duplicate", reason_codes_csv="duplicate-active-run", run_id="95",
                   run_status="in_progress", run_conclusion=""),
    )
    assert receipt["run_id_or_none"] == 95
    assert receipt["run_url_or_none"] == "https://github.com/Blummer92/agent-os/actions/runs/95"
    assert receipt["run_status_or_none"] == "in_progress"
    assert receipt["validation_executed"] is False


def test_receipt_job_fails_closed_on_missing_or_malformed_outputs() -> None:
    missing = receipt_from_job_outputs(transport(), **_outputs(decision="", reason_codes_csv="", observed_head_sha=""))
    assert missing["decision"] == "blocked"
    assert missing["reason_codes"] == ["dispatch-job-no-output"]
    hostile = receipt_from_job_outputs(
        transport(),
        **_outputs(decision="dispatched", reason_codes_csv="ok`$(id)`", run_id="12; rm", observed_head_sha="zz"),
    )
    assert hostile["decision"] == "blocked"
    assert hostile["run_id_or_none"] is None
    assert hostile["observed_head_sha"] is None
    mismatch = receipt_from_job_outputs(transport(), **_outputs(dispatch_trigger_id="issue-comment-trigger:" + "d" * 64))
    assert mismatch["reason_codes"] == ["receipt-trigger-mismatch"]


# --- #2410 live defect: run lookup on a branch with no prior dispatch runs ---


def _paginated_runs(items: list[dict]):
    """A real PyGithub PaginatedList served through its real lazy fetch path.

    The first page is fetched on demand (as in production), so an empty result
    reproduces the live IndexError; no network access is possible.
    """
    pytest.importorskip("github")
    from github.PaginatedList import PaginatedList
    from github.WorkflowRun import WorkflowRun

    class _CannedRequester:
        per_page = 30
        is_not_lazy = False

        def requestJsonAndCheck(self, *args: object, **kwargs: object):
            return {}, {"total_count": len(items), "workflow_runs": items}

    return PaginatedList(
        WorkflowRun,
        _CannedRequester(),
        "/repos/o/r/actions/workflows/w.yml/runs",
        {},
        list_item="workflow_runs",
        total_count_item="total_count",
    )


class _FakeWorkflow:
    def __init__(self, items: list[dict]) -> None:
        self._items = items
        self.calls: list[dict] = []

    def get_runs(self, **kwargs: object):
        self.calls.append(kwargs)
        return _paginated_runs(self._items)


def _client_over(items: list[dict]):
    from workflow_scheduler.governance.draft_validation_dispatch import _PyGithubClient

    client = object.__new__(_PyGithubClient)
    client._workflow = _FakeWorkflow(items)  # type: ignore[attr-defined]
    return client


def _run_json(run_id: int, head_sha: str = HEAD_SHA) -> dict:
    return {
        "id": run_id,
        "html_url": f"https://github.com/Blummer92/agent-os/actions/runs/{run_id}",
        "head_sha": head_sha,
        "created_at": "2026-10-21T14:00:05Z",
        "status": "completed",
        "conclusion": "failure",
    }


def test_run_lookup_with_no_prior_runs_returns_empty_instead_of_raising() -> None:
    # Observed live: PyGithub 2.10.0 raised IndexError for runs[:50] on an empty
    # PaginatedList, so the first dispatch on a fresh branch was always blocked.
    client = _client_over([])
    assert client.list_validation_dispatch_runs(head_ref="agent/x") == []
    assert client._workflow.calls == [{"event": "workflow_dispatch", "branch": "agent/x"}]  # type: ignore[attr-defined]


def test_run_lookup_returns_summaries_and_honours_the_inspection_cap() -> None:
    client = _client_over([_run_json(101), _run_json(102, OTHER_SHA)])
    found = client.list_validation_dispatch_runs(head_ref="agent/x")
    assert [(r.run_id, r.head_sha) for r in found] == [(101, HEAD_SHA), (102, OTHER_SHA)]
    assert found[0].status == "completed" and found[0].conclusion == "failure"

    many = _client_over([_run_json(1000 + i) for i in range(MAX_RUNS_INSPECTED + 7)])
    assert len(many.list_validation_dispatch_runs(head_ref="agent/x")) == MAX_RUNS_INSPECTED


def test_first_dispatch_on_a_fresh_branch_reaches_dispatch_through_the_real_client_path() -> None:
    # Full path: empty history -> dispatch allowed -> new run correlated.
    class Fresh(FakeClient):
        def __init__(self) -> None:
            super().__init__(pr(), run_pages=[])
            self._lookups = 0

        def list_validation_dispatch_runs(self, *, head_ref: str) -> list[WorkflowRunSummary]:
            self._lookups += 1
            real = _client_over([]) if self._lookups == 1 else _client_over(
                [{**_run_json(101), "created_at": NOW.isoformat().replace("+00:00", "Z")}]
            )
            return real.list_validation_dispatch_runs(head_ref=head_ref)

    client = Fresh()
    receipt = _dispatch(client)
    assert receipt["decision"] == "dispatched", receipt
    assert receipt["run_id_or_none"] == 101
    assert len(client.dispatch_calls) == 1


def test_lookup_failure_writes_exception_class_to_stderr_but_not_the_receipt(capsys) -> None:
    class RunsFail(FakeClient):
        def list_validation_dispatch_runs(self, **kwargs: object) -> list[WorkflowRunSummary]:
            raise IndexError("list index out of range")

    receipt = _dispatch(RunsFail(pr(), run_pages=[]))
    assert receipt["reason_codes"] == ["run-lookup-failed"]
    err = capsys.readouterr().err
    assert "run-lookup-failed: IndexError: list index out of range" in err
    assert "IndexError" not in str(receipt)
