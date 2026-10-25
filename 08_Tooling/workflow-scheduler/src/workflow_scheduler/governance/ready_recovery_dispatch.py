"""Bounded Ready-recovery dispatch through the governed issue-comment ingress (#2410).

Consumes an accepted ``ready-recovery`` transport envelope from
:mod:`workflow_scheduler.governance.github_issue_comment_ingress` and
performs exactly one fixed operation: dispatch the existing
``agent-os-validation.yml`` workflow in ready-recovery mode for one open,
already-Ready pull request at its exact current head, then correlate the
created run and emit a receipt.

This module is transport/dispatch only. It never marks a pull request Ready,
never merges, and never closes an issue. A dispatch acknowledgment is never
treated as validation evidence; the receipt records ``validation_executed``
as False and carries only the correlated run identity for canonical
readback.

Defense in depth, not a replacement for validation-side admission: this
module re-verifies the pull request, live main, workflow revision, source
run identity, and zero-job suppression evidence before dispatching, and it
pre-enforces the two-attempt limit from provider history. The validation
workflow independently re-verifies every one of those bindings plus the
ingress receipt provenance (see
``scripts/agent_os_ready_recovery_ingress.py``) before admitting recovery,
so a forged or stale dispatch that somehow reaches it still fails closed.
The dispatch ref is always ``main``: the validation workflow runs the
definition found on the dispatch ref, so only same-repository main heads
are admitted, and the expected workflow SHA must equal live main.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

OPERATION = "ready-recovery-validation"
VALIDATION_WORKFLOW_FILE = "agent-os-validation.yml"
GOVERNED_INVOCATION_WORKFLOW_FILE = "agent-os-governed-invocation.yml"
EXPECTED_REASON = "accepted-ready-recovery-envelope"
RECEIPT_SCHEMA_VERSION = "1.0"
RECEIPT_MARKER_PREFIX = "agent-os-ready-recovery-receipt:"
CORRELATION_SKEW = timedelta(seconds=10)
MAX_RUNS_INSPECTED = 200
MAX_READY_RECOVERY_ATTEMPTS = 2
# A completed recovery run with one of these conclusions did not produce
# validation evidence and may be retried once (attempt 2). Any other
# terminal conclusion (success, skipped, neutral, ...) is final for that
# exact recovery identity.
RETRYABLE_CONCLUSIONS = frozenset({"failure", "cancelled", "timed_out", "startup_failure"})
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_TRIGGER_PATTERN = re.compile(r"issue-comment-trigger:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True, kw_only=True)
class PullRequestState:
    state: str
    draft: bool
    base_ref: str
    base_sha: str | None
    head_ref: str | None
    head_sha: str | None
    head_repo_full_name: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowRunSummary:
    run_id: int
    url: str
    head_sha: str
    title: str
    created_at: datetime
    status: str | None
    conclusion: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRunState:
    run_id: int
    event: str
    status: str
    conclusion: str | None
    head_sha: str
    head_branch: str
    workflow_id: int
    workflow_path: str
    pr_numbers: tuple[int, ...]
    jobs_total_count: int


class DispatchClient(Protocol):
    """The only GitHub surface the bounded dispatch may touch."""

    def get_pull_request(self, pr_number: int) -> PullRequestState: ...

    def get_main_head_sha(self) -> str: ...

    def get_source_run(self, run_id: int) -> SourceRunState: ...

    def get_validation_workflow_id(self) -> int: ...

    def list_recovery_dispatch_runs(self) -> list[WorkflowRunSummary]: ...

    def create_recovery_dispatch(
        self,
        *,
        pr_number: int,
        expected_head_sha: str,
        expected_workflow_sha: str,
        expected_main_sha: str,
        source_validation_run_id: int,
        ingress_run_id: int,
        ingress_trigger_id: str,
    ) -> None: ...


def recovery_run_title(pr_number: int, expected_head_sha: str) -> str:
    """The validation workflow's run-name for a ready-recovery dispatch.

    Kept in sync with the ``run-name`` expression in
    ``agent-os-validation.yml``; the dispatch module and the validation
    workflow both count attempts by this exact title.
    """
    return f"agent-os-ready-recovery:{pr_number}:{expected_head_sha}"


def verify_pr_state(
    pr: PullRequestState,
    *,
    pr_number: int,
    expected_head_sha: str,
    expected_main_sha: str,
    live_main_sha: str,
    expected_workflow_sha: str,
    repository: str,
) -> list[str]:
    """Return fail-closed reason codes; an empty list means dispatch may proceed.

    Fork pull requests are rejected: the dispatched workflow runs the workflow
    definition found on the main ref, so only same-repository heads are
    admitted unless an independently authorized fork-support contract exists.
    The workflow revision must equal live main: a recovery dispatched from a
    stale workflow definition cannot be admitted by the validation workflow.
    """
    reasons: list[str] = []
    if pr.state != "open":
        reasons.append("pr-not-open")
    if pr.draft:
        reasons.append("pr-not-ready")
    if pr.base_ref != "main":
        reasons.append("pr-base-not-main")
    if pr.base_sha != expected_main_sha:
        reasons.append("pr-base-mismatch")
    if not pr.head_ref:
        reasons.append("pr-head-ref-missing")
    if pr.head_repo_full_name is None or pr.head_repo_full_name.casefold() != repository.casefold():
        reasons.append("pr-head-fork-not-supported")
    if pr.head_sha != expected_head_sha:
        reasons.append("pr-head-mismatch")
    if live_main_sha != expected_main_sha:
        reasons.append("main-mismatch")
    if live_main_sha != expected_workflow_sha:
        reasons.append("workflow-revision-mismatch")
    return reasons


def verify_source_run(
    source: SourceRunState,
    *,
    pr_number: int,
    expected_head_sha: str,
    expected_workflow_id: int,
) -> list[str]:
    """Return fail-closed reason codes for the suppressed validation run.

    Mirrors the validation workflow's source-run admission: the source run
    must be the validation workflow's own pull_request run for this exact PR
    head, completed action_required (the bot-suppression signature), with
    zero jobs. Any other provenance is rejected here and again downstream.
    """
    reasons: list[str] = []
    if source.event != "pull_request":
        reasons.append("source-run-event-mismatch")
    if source.status != "completed":
        reasons.append("source-run-not-completed")
    if source.conclusion != "action_required":
        reasons.append("source-run-conclusion-mismatch")
    if source.head_sha != expected_head_sha:
        reasons.append("source-run-head-mismatch")
    if source.workflow_id != expected_workflow_id:
        reasons.append("source-run-workflow-mismatch")
    if source.workflow_path != f".github/workflows/{VALIDATION_WORKFLOW_FILE}":
        reasons.append("source-run-path-mismatch")
    if pr_number not in source.pr_numbers:
        reasons.append("source-run-pr-mismatch")
    if source.jobs_total_count != 0:
        reasons.append("source-run-has-jobs")
    return reasons


def select_duplicate_run(
    runs: list[WorkflowRunSummary], *, title: str
) -> tuple[WorkflowRunSummary | None, list[str]]:
    """Decide whether earlier recovery runs for the exact title block a new one.

    Returns ``(blocking_run, reason_codes)``. An active run, a successful or
    otherwise final run, and an exhausted two-attempt budget all block. A
    run that completed with a retryable conclusion does not block until the
    budget is exhausted. The validation workflow counts attempts
    authoritatively from full provider history; this pre-check only avoids
    dispatching a run the workflow would reject.
    """
    title_runs = [run for run in runs if run.title == title]
    for run in title_runs:
        if run.status != "completed":
            return run, ["duplicate-active-run"]
    for run in title_runs:
        if run.conclusion not in RETRYABLE_CONCLUSIONS:
            return run, ["duplicate-dispatch-prevented"]
    if len(title_runs) >= MAX_READY_RECOVERY_ATTEMPTS:
        return title_runs[0], ["recovery-attempt-limit"]
    return None, []


def correlate_run(
    runs: list[WorkflowRunSummary],
    *,
    title: str,
    expected_workflow_sha: str,
    dispatched_at: datetime,
    exclude_run_ids: frozenset[int] = frozenset(),
) -> tuple[str, WorkflowRunSummary | None]:
    """Bind the dispatch to exactly one created run, failing closed otherwise.

    Runs that existed before the dispatch (``exclude_run_ids``) are never
    candidates, so a just-failed earlier run cannot be mistaken for the new one.
    """
    window_start = dispatched_at - CORRELATION_SKEW
    candidates = [
        run
        for run in runs
        if run.title == title
        and run.head_sha == expected_workflow_sha
        and run.created_at >= window_start
        and run.run_id not in exclude_run_ids
    ]
    if len(candidates) == 1:
        return "correlated", candidates[0]
    if not candidates:
        return "run-not-found", None
    return "run-ambiguous", None


def _receipt_core(receipt: dict) -> dict:
    return {key: value for key, value in receipt.items() if key != "receipt_id"}


def compute_receipt_id(receipt: dict) -> str:
    """Content-derived receipt identity.

    The validation workflow recomputes this over the artifact receipt and
    compares it, so a receipt whose fields were altered after dispatch (or
    invented without passing the ingress dispatch) fails verification even
    when every individual field looks plausible.
    """
    material = json.dumps(_receipt_core(receipt), sort_keys=True, separators=(",", ":"))
    return f"{RECEIPT_MARKER_PREFIX}{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def _base_receipt(transport: dict, *, ingress_run_id: int | None) -> dict:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": OPERATION,
        "workflow": VALIDATION_WORKFLOW_FILE,
        "repository": transport.get("repository"),
        "issue_number": transport.get("issue_number"),
        "comment_id": transport.get("comment_id"),
        "actor": transport.get("actor"),
        "trigger_id": transport.get("logical_trigger_id_or_none"),
        "receipt_id": None,
        "pr_number": transport.get("ready_recovery_pr_number_or_none"),
        "expected_head_sha": transport.get("ready_recovery_head_sha_or_none"),
        "observed_head_sha": None,
        "head_ref": None,
        "expected_main_sha": transport.get("ready_recovery_main_sha_or_none"),
        "expected_workflow_sha": transport.get("ready_recovery_workflow_sha_or_none"),
        "source_validation_run_id": transport.get("ready_recovery_source_run_id_or_none"),
        "ingress_run_id": ingress_run_id,
        "ingress_trigger_id": transport.get("logical_trigger_id_or_none"),
        "decision": "blocked",
        "reason_codes": [],
        "run_id_or_none": None,
        "run_url_or_none": None,
        "run_status_or_none": None,
        "run_conclusion_or_none": None,
        "dispatched_at_or_none": None,
        "validation_executed": False,
    }


def _finalize_receipt(receipt: dict) -> dict:
    receipt["receipt_id"] = compute_receipt_id(receipt)
    return receipt


def _failure_reasons(code: str, exc: Exception) -> list[str]:
    """Primary reason code plus an HTTP status detail when the error carries one.

    The exception class and a bounded one-line message go to stderr (job log
    only, never the receipt) so a non-HTTP failure stays diagnosable.
    """
    detail = " ".join(str(exc).split())[:300]
    print(f"{code}: {type(exc).__name__}: {detail}", file=sys.stderr)
    status = getattr(exc, "status", None)
    if type(status) is int and 100 <= status <= 599:
        return [code, f"{code}-http-{status}"]
    return [code]


def execute_dispatch(
    transport: dict,
    client: DispatchClient,
    *,
    ingress_run_id: int | None = None,
    dispatched_at: datetime | None = None,
    poll_attempts: int = 10,
    poll_interval_seconds: float = 6.0,
    sleeper=time.sleep,
) -> dict:
    """Run the bounded dispatch once and return the receipt (never raises for
    expected fail-closed conditions; every outcome is a receipt)."""
    receipt = _base_receipt(transport, ingress_run_id=ingress_run_id)
    if (
        transport.get("status") != "accepted"
        or transport.get("reason") != EXPECTED_REASON
        or type(receipt["pr_number"]) is not int
        or type(receipt["expected_head_sha"]) is not str
        or type(receipt["expected_main_sha"]) is not str
        or type(receipt["expected_workflow_sha"]) is not str
        or type(receipt["source_validation_run_id"]) is not int
        or type(receipt["trigger_id"]) is not str
        or type(ingress_run_id) is not int
    ):
        receipt["reason_codes"] = ["transport-not-accepted"]
        return _finalize_receipt(receipt)
    pr_number: int = receipt["pr_number"]
    expected_head_sha: str = receipt["expected_head_sha"]
    expected_main_sha: str = receipt["expected_main_sha"]
    expected_workflow_sha: str = receipt["expected_workflow_sha"]
    source_run_id: int = receipt["source_validation_run_id"]

    repository = receipt["repository"]
    if type(repository) is not str:
        receipt["reason_codes"] = ["transport-not-accepted"]
        return _finalize_receipt(receipt)

    try:
        pr = client.get_pull_request(pr_number)
    except Exception as exc:  # lookup failure: fail closed with a diagnosable reason
        receipt["reason_codes"] = _failure_reasons("pr-lookup-failed", exc)
        return _finalize_receipt(receipt)
    receipt["observed_head_sha"] = pr.head_sha
    receipt["head_ref"] = pr.head_ref
    try:
        live_main_sha = client.get_main_head_sha()
    except Exception as exc:
        receipt["reason_codes"] = _failure_reasons("main-lookup-failed", exc)
        return _finalize_receipt(receipt)
    reasons = verify_pr_state(
        pr,
        pr_number=pr_number,
        expected_head_sha=expected_head_sha,
        expected_main_sha=expected_main_sha,
        live_main_sha=live_main_sha,
        expected_workflow_sha=expected_workflow_sha,
        repository=repository,
    )
    if reasons:
        receipt["reason_codes"] = reasons
        return _finalize_receipt(receipt)

    try:
        source = client.get_source_run(source_run_id)
        workflow_id = client.get_validation_workflow_id()
    except Exception as exc:
        receipt["reason_codes"] = _failure_reasons("source-run-lookup-failed", exc)
        return _finalize_receipt(receipt)
    reasons = verify_source_run(
        source,
        pr_number=pr_number,
        expected_head_sha=expected_head_sha,
        expected_workflow_id=workflow_id,
    )
    if reasons:
        receipt["reason_codes"] = reasons
        return _finalize_receipt(receipt)

    title = recovery_run_title(pr_number, expected_head_sha)
    try:
        prior_runs = client.list_recovery_dispatch_runs()
    except Exception as exc:
        receipt["reason_codes"] = _failure_reasons("run-lookup-failed", exc)
        return _finalize_receipt(receipt)
    duplicate, duplicate_reasons = select_duplicate_run(prior_runs, title=title)
    if duplicate is not None:
        retry_limited = duplicate_reasons == ["recovery-attempt-limit"]
        receipt["decision"] = "blocked" if retry_limited else "duplicate"
        receipt["reason_codes"] = duplicate_reasons
        receipt["run_id_or_none"] = duplicate.run_id
        receipt["run_url_or_none"] = duplicate.url
        receipt["run_status_or_none"] = duplicate.status
        receipt["run_conclusion_or_none"] = duplicate.conclusion
        return _finalize_receipt(receipt)

    dispatch_time = dispatched_at or datetime.now(timezone.utc)
    receipt["dispatched_at_or_none"] = dispatch_time.isoformat()
    try:
        client.create_recovery_dispatch(
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
            expected_workflow_sha=expected_workflow_sha,
            expected_main_sha=expected_main_sha,
            source_validation_run_id=source_run_id,
            ingress_run_id=ingress_run_id,
            ingress_trigger_id=receipt["trigger_id"],
        )
    except Exception as exc:  # dispatch transport failure: fail closed, no run identity claimed
        receipt["reason_codes"] = _failure_reasons("dispatch-failed", exc)
        return _finalize_receipt(receipt)

    preexisting = frozenset(run.run_id for run in prior_runs)
    outcome = "run-not-found"
    run: WorkflowRunSummary | None = None
    for attempt in range(max(1, poll_attempts)):
        try:
            runs = client.list_recovery_dispatch_runs()
        except Exception as exc:
            receipt["decision"] = "correlation-failed"
            receipt["reason_codes"] = _failure_reasons("run-lookup-failed", exc)
            return _finalize_receipt(receipt)
        outcome, run = correlate_run(
            runs,
            title=title,
            expected_workflow_sha=expected_workflow_sha,
            dispatched_at=dispatch_time,
            exclude_run_ids=preexisting,
        )
        if outcome == "correlated" or outcome == "run-ambiguous":
            break
        if attempt < poll_attempts - 1:
            sleeper(poll_interval_seconds)
    if outcome != "correlated" or run is None:
        receipt["decision"] = "correlation-failed"
        receipt["reason_codes"] = [outcome]
        return _finalize_receipt(receipt)

    receipt["decision"] = "dispatched"
    receipt["reason_codes"] = ["dispatch-correlated"]
    receipt["run_id_or_none"] = run.run_id
    receipt["run_url_or_none"] = run.url
    receipt["run_status_or_none"] = run.status
    receipt["run_conclusion_or_none"] = run.conclusion
    return _finalize_receipt(receipt)


class _PyGithubClient:
    """Thin PyGithub-backed client; the only place network calls live."""

    def __init__(self, repository: str, token: str) -> None:
        from github import Github  # imported lazily so tests need no PyGithub

        self._repo = Github(token).get_repo(repository)
        self._workflow = self._repo.get_workflow(VALIDATION_WORKFLOW_FILE)

    def get_pull_request(self, pr_number: int) -> PullRequestState:
        pr = self._repo.get_pull(pr_number)
        return PullRequestState(
            state=pr.state,
            draft=bool(pr.draft),
            base_ref=pr.base.ref,
            base_sha=pr.base.sha,
            head_ref=pr.head.ref,
            head_sha=pr.head.sha,
            head_repo_full_name=pr.head.repo.full_name if pr.head.repo else None,
        )

    def get_main_head_sha(self) -> str:
        return self._repo.get_branch("main").commit.sha

    def get_source_run(self, run_id: int) -> SourceRunState:
        run = self._repo.get_workflow_run(run_id)
        jobs = run.jobs()
        return SourceRunState(
            run_id=run.id,
            event=run.event,
            status=run.status,
            conclusion=run.conclusion,
            head_sha=run.head_sha,
            head_branch=run.head_branch,
            workflow_id=run.workflow_id,
            workflow_path=run.path,
            pr_numbers=tuple(pr.number for pr in (run.pull_requests or [])),
            jobs_total_count=jobs.totalCount,
        )

    def get_validation_workflow_id(self) -> int:
        return self._workflow.id

    def list_recovery_dispatch_runs(self) -> list[WorkflowRunSummary]:
        runs = self._workflow.get_runs(event="workflow_dispatch", branch="main")
        summaries: list[WorkflowRunSummary] = []
        # islice, not runs[:N]: PyGithub 2.10.0 raises IndexError when slicing an
        # empty PaginatedList, i.e. for the first dispatch on a fresh branch.
        for run in itertools.islice(runs, MAX_RUNS_INSPECTED):
            summaries.append(
                WorkflowRunSummary(
                    run_id=run.id,
                    url=run.html_url,
                    head_sha=run.head_sha,
                    title=run.display_title or "",
                    created_at=run.created_at,
                    status=run.status,
                    conclusion=run.conclusion,
                )
            )
        return summaries

    def create_recovery_dispatch(
        self,
        *,
        pr_number: int,
        expected_head_sha: str,
        expected_workflow_sha: str,
        expected_main_sha: str,
        source_validation_run_id: int,
        ingress_run_id: int,
        ingress_trigger_id: str,
    ) -> None:
        created = self._workflow.create_dispatch(
            "main",
            {
                "pr_number": str(pr_number),
                "expected_head_sha": expected_head_sha,
                "ready_recovery": True,
                "expected_workflow_sha": expected_workflow_sha,
                "expected_main_sha": expected_main_sha,
                "source_validation_run_id": str(source_validation_run_id),
                "ingress_run_id": str(ingress_run_id),
                "ingress_trigger_id": ingress_trigger_id,
            },
        )
        if not created:
            raise RuntimeError("workflow dispatch was not accepted")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ingress-run-id", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    transport = json.loads(Path(args.transport).read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for dispatch mode")
    ingress_run_id = args.ingress_run_id
    if ingress_run_id is None:
        raw = os.environ.get("GITHUB_RUN_ID", "")
        ingress_run_id = int(raw) if raw.isdigit() else None
    if transport.get("repository") != args.repository:
        receipt = _base_receipt(transport, ingress_run_id=ingress_run_id)
        receipt["reason_codes"] = ["transport-repository-mismatch"]
        _write_json(Path(args.output), _finalize_receipt(receipt))
        print(json.dumps(receipt, sort_keys=True))
        return 0
    client = _PyGithubClient(args.repository, token)
    receipt = execute_dispatch(transport, client, ingress_run_id=ingress_run_id)
    _write_json(Path(args.output), receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
