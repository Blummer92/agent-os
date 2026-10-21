from __future__ import annotations

from datetime import datetime, timedelta, timezone

from workflow_scheduler.governance.draft_validation_dispatch import (
    PullRequestState,
    WorkflowRunSummary,
    correlate_run,
    execute_dispatch,
    find_existing_receipt,
    render_receipt_comment,
    select_duplicate_run,
    verify_pr_state,
)

HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40
NOW = datetime(2026, 10, 21, 14, 0, 0, tzinfo=timezone.utc)
TRIGGER_ID = "issue-comment-trigger:" + "c" * 64


def pr(**overrides: object) -> PullRequestState:
    values = dict(
        state="open",
        draft=True,
        base_ref="main",
        head_ref="agent/2411-example",
        head_sha=HEAD_SHA,
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
    assert verify_pr_state(pr(), pr_number=2411, expected_head_sha=HEAD_SHA) == []


def test_verify_pr_state_rejects_each_bad_state() -> None:
    assert "pr-not-open" in verify_pr_state(pr(state="closed"), pr_number=2411, expected_head_sha=HEAD_SHA)
    assert "pr-not-draft" in verify_pr_state(pr(draft=False), pr_number=2411, expected_head_sha=HEAD_SHA)
    assert "pr-base-not-main" in verify_pr_state(pr(base_ref="develop"), pr_number=2411, expected_head_sha=HEAD_SHA)
    assert "pr-head-mismatch" in verify_pr_state(pr(head_sha=OTHER_SHA), pr_number=2411, expected_head_sha=HEAD_SHA)
    assert "pr-head-ref-missing" in verify_pr_state(pr(head_ref=None), pr_number=2411, expected_head_sha=HEAD_SHA)


# --- dedupe / correlation ---------------------------------------------------


def test_select_duplicate_run_matches_exact_head_only() -> None:
    assert select_duplicate_run([run()], expected_head_sha=HEAD_SHA) is not None
    assert select_duplicate_run([run(head_sha=OTHER_SHA)], expected_head_sha=HEAD_SHA) is None
    assert select_duplicate_run([], expected_head_sha=HEAD_SHA) is None


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
    assert find_existing_receipt([comment], TRIGGER_ID) is True
    assert find_existing_receipt(["unrelated comment"], TRIGGER_ID) is False
    assert "not validation" in comment
