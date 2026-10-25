"""Contract regressions for the #2410 bounded Ready-recovery dispatch module.

The dispatch module re-verifies the pull request, live main, workflow
revision, source-run identity, and attempt budget before dispatching, and
correlates exactly one created run. The validation workflow verifies all of
it again, plus receipt provenance, before admitting recovery.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from workflow_scheduler.governance.ready_recovery_dispatch import (
    MAX_READY_RECOVERY_ATTEMPTS,
    PullRequestState,
    SourceRunState,
    WorkflowRunSummary,
    compute_receipt_id,
    correlate_run,
    execute_dispatch,
    recovery_run_title,
    select_duplicate_run,
    verify_pr_state,
    verify_source_run,
)

HEAD_SHA = "a" * 40
MAIN_SHA = "b" * 40
WORKFLOW_SHA = "b" * 40
OTHER_SHA = "d" * 40
WORKFLOW_ID = 314047915
SOURCE_RUN_ID = 40150153359
INGRESS_RUN_ID = 40151280000
NOW = datetime(2026, 10, 25, 2, 0, 0, tzinfo=timezone.utc)
TRIGGER_ID = "issue-comment-trigger:" + "c" * 64
REPOSITORY = "Blummer92/agent-os"
TITLE = recovery_run_title(3723, HEAD_SHA)


def pr(**overrides: object) -> PullRequestState:
    values = dict(
        state="open",
        draft=False,
        base_ref="main",
        base_sha=MAIN_SHA,
        head_ref="agent/3723-example",
        head_sha=HEAD_SHA,
        head_repo_full_name=REPOSITORY,
    )
    values.update(overrides)
    return PullRequestState(**values)  # type: ignore[arg-type]


def source(**overrides: object) -> SourceRunState:
    values = dict(
        run_id=SOURCE_RUN_ID,
        event="pull_request",
        status="completed",
        conclusion="action_required",
        head_sha=HEAD_SHA,
        head_branch="agent/3723-example",
        workflow_id=WORKFLOW_ID,
        workflow_path=".github/workflows/agent-os-validation.yml",
        pr_numbers=(3723,),
        jobs_total_count=0,
    )
    values.update(overrides)
    return SourceRunState(**values)  # type: ignore[arg-type]


def run(**overrides: object) -> WorkflowRunSummary:
    values = dict(
        run_id=101,
        url="https://github.com/Blummer92/agent-os/actions/runs/101",
        head_sha=WORKFLOW_SHA,
        title=TITLE,
        created_at=NOW + timedelta(seconds=5),
        status="completed",
        conclusion="success",
    )
    values.update(overrides)
    return WorkflowRunSummary(**values)  # type: ignore[arg-type]


def transport(**overrides: object) -> dict:
    values = dict(
        status="accepted",
        reason="accepted-ready-recovery-envelope",
        repository=REPOSITORY,
        issue_number=2410,
        comment_id=7001,
        actor="chatgpt-codex-connector[bot]",
        logical_trigger_id_or_none=TRIGGER_ID,
        ready_recovery_pr_number_or_none=3723,
        ready_recovery_head_sha_or_none=HEAD_SHA,
        ready_recovery_main_sha_or_none=MAIN_SHA,
        ready_recovery_workflow_sha_or_none=WORKFLOW_SHA,
        ready_recovery_source_run_id_or_none=SOURCE_RUN_ID,
    )
    values.update(overrides)
    return values


class FakeClient:
    def __init__(self, pr_state, source_state, *, run_pages, raise_on_dispatch=False):
        self._pr = pr_state
        self._source = source_state
        self._pages = list(run_pages)
        self.raise_on_dispatch = raise_on_dispatch
        self.dispatch_calls: list[dict] = []

    def get_pull_request(self, pr_number: int) -> PullRequestState:
        assert pr_number == 3723
        return self._pr

    def get_main_head_sha(self) -> str:
        return MAIN_SHA

    def get_source_run(self, run_id: int) -> SourceRunState:
        assert run_id == SOURCE_RUN_ID
        return self._source

    def get_validation_workflow_id(self) -> int:
        return WORKFLOW_ID

    def list_recovery_dispatch_runs(self) -> list[WorkflowRunSummary]:
        if self._pages:
            return self._pages.pop(0)
        return []

    def create_recovery_dispatch(self, **kwargs: object) -> None:
        if self.raise_on_dispatch:
            error = RuntimeError("403 Resource not accessible by integration")
            error.status = 403  # type: ignore[attr-defined]
            raise error
        self.dispatch_calls.append(dict(kwargs))


# --- verify_pr_state -------------------------------------------------------


def test_verify_pr_state_accepts_exact_ready_on_main() -> None:
    assert (
        verify_pr_state(
            pr(),
            pr_number=3723,
            expected_head_sha=HEAD_SHA,
            expected_main_sha=MAIN_SHA,
            live_main_sha=MAIN_SHA,
            expected_workflow_sha=WORKFLOW_SHA,
            repository=REPOSITORY,
        )
        == []
    )


def test_verify_pr_state_rejects_each_bad_state() -> None:
    base = dict(
        pr_number=3723,
        expected_head_sha=HEAD_SHA,
        expected_main_sha=MAIN_SHA,
        live_main_sha=MAIN_SHA,
        expected_workflow_sha=WORKFLOW_SHA,
        repository=REPOSITORY,
    )
    assert "pr-not-open" in verify_pr_state(pr(state="closed"), **base)
    assert "pr-not-ready" in verify_pr_state(pr(draft=True), **base)
    assert "pr-base-not-main" in verify_pr_state(pr(base_ref="develop"), **base)
    assert "pr-base-mismatch" in verify_pr_state(pr(base_sha=OTHER_SHA), **base)
    assert "pr-head-mismatch" in verify_pr_state(pr(head_sha=OTHER_SHA), **base)
    assert "pr-head-ref-missing" in verify_pr_state(pr(head_ref=None), **base)
    assert "pr-head-fork-not-supported" in verify_pr_state(
        pr(head_repo_full_name="fork/agent-os"), **base
    )
    assert "main-mismatch" in verify_pr_state(pr(), **{**base, "live_main_sha": OTHER_SHA})
    assert "workflow-revision-mismatch" in verify_pr_state(
        pr(), **{**base, "expected_workflow_sha": OTHER_SHA}
    )


# --- verify_source_run -----------------------------------------------------


def test_verify_source_run_accepts_suppressed_zero_job_run() -> None:
    assert verify_source_run(source(), pr_number=3723, expected_head_sha=HEAD_SHA, expected_workflow_id=WORKFLOW_ID) == []


def test_verify_source_run_rejects_each_bad_provenance() -> None:
    base = dict(pr_number=3723, expected_head_sha=HEAD_SHA, expected_workflow_id=WORKFLOW_ID)
    assert "source-run-event-mismatch" in verify_source_run(source(event="workflow_dispatch"), **base)
    assert "source-run-not-completed" in verify_source_run(source(status="in_progress"), **base)
    assert "source-run-conclusion-mismatch" in verify_source_run(source(conclusion="success"), **base)
    assert "source-run-head-mismatch" in verify_source_run(source(head_sha=OTHER_SHA), **base)
    assert "source-run-workflow-mismatch" in verify_source_run(source(workflow_id=1), **base)
    assert "source-run-path-mismatch" in verify_source_run(
        source(workflow_path=".github/workflows/other.yml"), **base
    )
    assert "source-run-pr-mismatch" in verify_source_run(source(pr_numbers=(9999,)), **base)
    assert "source-run-has-jobs" in verify_source_run(source(jobs_total_count=3), **base)


# --- dedupe / correlation ---------------------------------------------------


def test_select_duplicate_run_matches_exact_title_only() -> None:
    assert select_duplicate_run([run()], title=TITLE)[0] is not None
    assert select_duplicate_run([run(title="other")], title=TITLE) == (None, [])
    assert select_duplicate_run([], title=TITLE) == (None, [])


def test_select_duplicate_run_blocks_active_final_and_exhausted() -> None:
    active = run(status="in_progress", conclusion=None)
    assert select_duplicate_run([active], title=TITLE)[1] == ["duplicate-active-run"]
    assert select_duplicate_run([run()], title=TITLE)[1] == ["duplicate-dispatch-prevented"]
    one_failed = run(status="completed", conclusion="failure", run_id=201)
    assert select_duplicate_run([one_failed], title=TITLE) == (None, [])
    two_failed = [one_failed, run(status="completed", conclusion="cancelled", run_id=202)]
    blocked, reasons = select_duplicate_run(two_failed, title=TITLE)
    assert blocked is not None and reasons == ["recovery-attempt-limit"]
    assert MAX_READY_RECOVERY_ATTEMPTS == 2


def test_correlate_run_requires_exactly_one_run_in_window() -> None:
    outcome, found = correlate_run(
        [run()], title=TITLE, expected_workflow_sha=WORKFLOW_SHA, dispatched_at=NOW
    )
    assert outcome == "correlated" and found is not None and found.run_id == 101
    for candidate, label in (
        ([], "none"),
        ([run(), run(run_id=102)], "ambiguous"),
        ([run(created_at=NOW - timedelta(minutes=5))], "stale"),
        ([run(title="other")], "wrong title"),
        ([run(head_sha=OTHER_SHA)], "wrong workflow sha"),
    ):
        outcome, found = correlate_run(
            candidate, title=TITLE, expected_workflow_sha=WORKFLOW_SHA, dispatched_at=NOW
        )
        assert (outcome, found) != ("correlated", found) or found is None, label
    outcome, found = correlate_run(
        [run()],
        title=TITLE,
        expected_workflow_sha=WORKFLOW_SHA,
        dispatched_at=NOW,
        exclude_run_ids=frozenset({101}),
    )
    assert outcome == "run-not-found" and found is None


# --- execute_dispatch -------------------------------------------------------


def test_execute_dispatch_happy_path_correlates_run() -> None:
    client = FakeClient(pr(), source(), run_pages=[[], [run()]])
    receipt = execute_dispatch(
        transport(),
        client,
        ingress_run_id=INGRESS_RUN_ID,
        dispatched_at=NOW,
        poll_attempts=3,
        poll_interval_seconds=0,
        sleeper=lambda s: None,
    )
    assert receipt["decision"] == "dispatched"
    assert receipt["reason_codes"] == ["dispatch-correlated"]
    assert receipt["run_id_or_none"] == 101
    assert receipt["validation_executed"] is False
    assert receipt["ingress_run_id"] == INGRESS_RUN_ID
    assert receipt["ingress_trigger_id"] == TRIGGER_ID
    assert receipt["receipt_id"] == compute_receipt_id(receipt)
    assert client.dispatch_calls == [
        {
            "pr_number": 3723,
            "expected_head_sha": HEAD_SHA,
            "expected_workflow_sha": WORKFLOW_SHA,
            "expected_main_sha": MAIN_SHA,
            "source_validation_run_id": SOURCE_RUN_ID,
            "ingress_run_id": INGRESS_RUN_ID,
            "ingress_trigger_id": TRIGGER_ID,
        }
    ]


def test_execute_dispatch_rejects_unaccepted_transport_without_dispatch() -> None:
    client = FakeClient(pr(), source(), run_pages=[])
    receipt = execute_dispatch(transport(status="blocked", reason="actor-not-allowed"), client)
    assert receipt["decision"] == "blocked"
    assert receipt["reason_codes"] == ["transport-not-accepted"]
    assert client.dispatch_calls == []
    receipt = execute_dispatch(transport(), client, ingress_run_id=None)
    assert receipt["reason_codes"] == ["transport-not-accepted"]
    assert client.dispatch_calls == []


def test_execute_dispatch_fails_closed_on_stale_bindings() -> None:
    cases = (
        (pr(head_sha=OTHER_SHA), source(), ["pr-head-mismatch"]),
        (pr(base_sha=OTHER_SHA), source(), ["pr-base-mismatch"]),
        (pr(draft=True), source(), ["pr-not-ready"]),
        (pr(), source(jobs_total_count=2), ["source-run-has-jobs"]),
        (pr(), source(pr_numbers=(1,)), ["source-run-pr-mismatch"]),
        (pr(), source(conclusion="success"), ["source-run-conclusion-mismatch"]),
    )
    for pr_state, source_state, expected in cases:
        client = FakeClient(pr_state, source_state, run_pages=[])
        receipt = execute_dispatch(transport(), client, ingress_run_id=INGRESS_RUN_ID)
        assert receipt["reason_codes"] == expected, expected
        assert client.dispatch_calls == []


def test_execute_dispatch_blocks_duplicates_and_exhaustion() -> None:
    active = run(status="in_progress", conclusion=None)
    client = FakeClient(pr(), source(), run_pages=[[active]])
    receipt = execute_dispatch(transport(), client, ingress_run_id=INGRESS_RUN_ID)
    assert receipt["decision"] == "duplicate"
    assert receipt["reason_codes"] == ["duplicate-active-run"]
    assert client.dispatch_calls == []

    client = FakeClient(pr(), source(), run_pages=[[run()]])
    receipt = execute_dispatch(transport(), client, ingress_run_id=INGRESS_RUN_ID)
    assert receipt["reason_codes"] == ["duplicate-dispatch-prevented"]
    assert client.dispatch_calls == []

    failed = [run(status="completed", conclusion="failure", run_id=201),
              run(status="completed", conclusion="cancelled", run_id=202)]
    client = FakeClient(pr(), source(), run_pages=[failed])
    receipt = execute_dispatch(transport(), client, ingress_run_id=INGRESS_RUN_ID)
    assert receipt["decision"] == "blocked"
    assert receipt["reason_codes"] == ["recovery-attempt-limit"]
    assert client.dispatch_calls == []


def test_execute_dispatch_reports_provider_and_correlation_failures() -> None:
    client = FakeClient(pr(), source(), run_pages=[[]], raise_on_dispatch=True)
    receipt = execute_dispatch(transport(), client, ingress_run_id=INGRESS_RUN_ID)
    assert receipt["reason_codes"] == ["dispatch-failed", "dispatch-failed-http-403"]
    assert receipt["run_id_or_none"] is None

    client = FakeClient(pr(), source(), run_pages=[[], []])
    receipt = execute_dispatch(
        transport(),
        client,
        ingress_run_id=INGRESS_RUN_ID,
        dispatched_at=NOW,
        poll_attempts=2,
        poll_interval_seconds=0,
        sleeper=lambda s: None,
    )
    assert receipt["decision"] == "correlation-failed"
    assert receipt["reason_codes"] == ["run-not-found"]
