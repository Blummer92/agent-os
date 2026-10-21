"""Bounded Draft final-candidate validation dispatch (#2410).

Consumes an accepted ``draft-final-candidate-validation`` transport envelope
from :mod:`workflow_scheduler.governance.github_issue_comment_ingress` and
performs exactly one fixed operation: dispatch the existing
``agent-os-validation.yml`` workflow for one open Draft pull request at its
exact current head, then correlate the created run and emit a receipt.

The target workflow identity is hardcoded. The comment grammar carries no
workflow, ref, or shell input: the dispatch ref is derived from the live pull
request head at dispatch time, and the workflow itself re-verifies the exact
head and fails closed on any mismatch. A dispatch acknowledgment is never
treated as validation evidence; the receipt records ``validation_executed``
as False and carries only the correlated run identity for canonical readback.

This module is transport/dispatch only. It never marks a pull request Ready,
never merges, and never closes an issue.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

OPERATION = "draft-final-candidate-validation"
VALIDATION_WORKFLOW_FILE = "agent-os-validation.yml"
EXPECTED_REASON = "accepted-draft-validation-envelope"
RECEIPT_SCHEMA_VERSION = "1.0"
RECEIPT_MARKER_PREFIX = "agent-os-draft-validation-receipt:"
CORRELATION_SKEW = timedelta(seconds=10)
MAX_RUNS_INSPECTED = 50
# A completed run with one of these conclusions did not produce validation
# evidence and may be retried by a new owner command; any other terminal
# conclusion (success, skipped, neutral, ...) is final for that head.
RETRYABLE_CONCLUSIONS = frozenset({"failure", "cancelled", "timed_out", "startup_failure"})
# Total failed/cancelled dispatch runs tolerated per exact head; the next
# command after this many is blocked until an owner decides otherwise.
MAX_FAILED_DISPATCHES_PER_HEAD = 3
_REASON_CODE_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True, kw_only=True)
class PullRequestState:
    state: str
    draft: bool
    base_ref: str
    head_ref: str | None
    head_sha: str | None
    head_repo_full_name: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkflowRunSummary:
    run_id: int
    url: str
    head_sha: str
    created_at: datetime
    status: str | None
    conclusion: str | None


class DispatchClient(Protocol):
    """The only GitHub surface the bounded dispatch may touch."""

    def get_pull_request(self, pr_number: int) -> PullRequestState: ...

    def list_validation_dispatch_runs(
        self, *, head_ref: str
    ) -> list[WorkflowRunSummary]: ...

    def create_validation_dispatch(
        self, *, ref: str, pr_number: int, expected_head_sha: str
    ) -> None: ...


def verify_pr_state(
    pr: PullRequestState,
    *,
    pr_number: int,
    expected_head_sha: str,
    repository: str,
) -> list[str]:
    """Return fail-closed reason codes; an empty list means dispatch may proceed.

    Fork pull requests are rejected: the dispatched workflow runs the workflow
    definition found on the head ref, so only same-repository heads are
    admitted unless an independently authorized fork-support contract exists.
    """
    reasons: list[str] = []
    if pr.state != "open":
        reasons.append("pr-not-open")
    if not pr.draft:
        reasons.append("pr-not-draft")
    if pr.base_ref != "main":
        reasons.append("pr-base-not-main")
    if not pr.head_ref:
        reasons.append("pr-head-ref-missing")
    if pr.head_repo_full_name is None or pr.head_repo_full_name.casefold() != repository.casefold():
        reasons.append("pr-head-fork-not-supported")
    if pr.head_sha != expected_head_sha:
        reasons.append("pr-head-mismatch")
    return reasons


def select_duplicate_run(
    runs: list[WorkflowRunSummary], *, expected_head_sha: str
) -> tuple[WorkflowRunSummary | None, list[str]]:
    """Decide whether earlier dispatch runs for the exact head block a new one.

    Returns ``(blocking_run, reason_codes)``. An active run, a successful or
    otherwise final run, and an exhausted retry budget all block. A run that
    completed with a retryable conclusion does not block until
    ``MAX_FAILED_DISPATCHES_PER_HEAD`` such runs exist for the head.
    """
    head_runs = [run for run in runs if run.head_sha == expected_head_sha]
    for run in head_runs:
        if run.status != "completed":
            return run, ["duplicate-active-run"]
    for run in head_runs:
        if run.conclusion not in RETRYABLE_CONCLUSIONS:
            return run, ["duplicate-dispatch-prevented"]
    if len(head_runs) >= MAX_FAILED_DISPATCHES_PER_HEAD:
        return head_runs[0], ["retry-limit-reached"]
    return None, []


def correlate_run(
    runs: list[WorkflowRunSummary],
    *,
    expected_head_sha: str,
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
        if run.head_sha == expected_head_sha
        and run.created_at >= window_start
        and run.run_id not in exclude_run_ids
    ]
    if len(candidates) == 1:
        return "correlated", candidates[0]
    if not candidates:
        return "run-not-found", None
    return "run-ambiguous", None


def _base_receipt(transport: dict) -> dict:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": OPERATION,
        "workflow": VALIDATION_WORKFLOW_FILE,
        "repository": transport.get("repository"),
        "issue_number": transport.get("issue_number"),
        "comment_id": transport.get("comment_id"),
        "actor": transport.get("actor"),
        "trigger_id": transport.get("logical_trigger_id_or_none"),
        "pr_number": transport.get("draft_validation_pr_number_or_none"),
        "expected_head_sha": transport.get("draft_validation_head_sha_or_none"),
        "observed_head_sha": None,
        "head_ref": None,
        "decision": "blocked",
        "reason_codes": [],
        "run_id_or_none": None,
        "run_url_or_none": None,
        "run_status_or_none": None,
        "run_conclusion_or_none": None,
        "dispatched_at_or_none": None,
        "validation_executed": False,
    }


def _failure_reasons(code: str, exc: Exception) -> list[str]:
    """Primary reason code plus an HTTP status detail when the error carries one."""
    status = getattr(exc, "status", None)
    if type(status) is int and 100 <= status <= 599:
        return [code, f"{code}-http-{status}"]
    return [code]


def execute_dispatch(
    transport: dict,
    client: DispatchClient,
    *,
    dispatched_at: datetime | None = None,
    poll_attempts: int = 10,
    poll_interval_seconds: float = 6.0,
    sleeper=time.sleep,
) -> dict:
    """Run the bounded dispatch once and return the receipt (never raises for
    expected fail-closed conditions; every outcome is a receipt)."""
    receipt = _base_receipt(transport)
    if (
        transport.get("status") != "accepted"
        or transport.get("reason") != EXPECTED_REASON
        or type(receipt["pr_number"]) is not int
        or type(receipt["expected_head_sha"]) is not str
        or type(receipt["trigger_id"]) is not str
    ):
        receipt["reason_codes"] = ["transport-not-accepted"]
        return receipt
    pr_number: int = receipt["pr_number"]
    expected_head_sha: str = receipt["expected_head_sha"]

    repository = receipt["repository"]
    if type(repository) is not str:
        receipt["reason_codes"] = ["transport-not-accepted"]
        return receipt

    try:
        pr = client.get_pull_request(pr_number)
    except Exception as exc:  # lookup failure: fail closed with a diagnosable reason
        receipt["reason_codes"] = _failure_reasons("pr-lookup-failed", exc)
        return receipt
    receipt["observed_head_sha"] = pr.head_sha
    receipt["head_ref"] = pr.head_ref
    reasons = verify_pr_state(
        pr, pr_number=pr_number, expected_head_sha=expected_head_sha, repository=repository
    )
    if reasons:
        receipt["reason_codes"] = reasons
        return receipt
    assert pr.head_ref is not None  # verified above

    try:
        prior_runs = client.list_validation_dispatch_runs(head_ref=pr.head_ref)
    except Exception as exc:
        receipt["reason_codes"] = _failure_reasons("run-lookup-failed", exc)
        return receipt
    duplicate, duplicate_reasons = select_duplicate_run(
        prior_runs, expected_head_sha=expected_head_sha
    )
    if duplicate is not None:
        retry_limited = duplicate_reasons == ["retry-limit-reached"]
        receipt["decision"] = "blocked" if retry_limited else "duplicate"
        receipt["reason_codes"] = duplicate_reasons
        receipt["run_id_or_none"] = duplicate.run_id
        receipt["run_url_or_none"] = duplicate.url
        receipt["run_status_or_none"] = duplicate.status
        receipt["run_conclusion_or_none"] = duplicate.conclusion
        return receipt

    dispatch_time = dispatched_at or datetime.now(timezone.utc)
    receipt["dispatched_at_or_none"] = dispatch_time.isoformat()
    try:
        client.create_validation_dispatch(
            ref=pr.head_ref, pr_number=pr_number, expected_head_sha=expected_head_sha
        )
    except Exception as exc:  # dispatch transport failure: fail closed, no run identity claimed
        receipt["reason_codes"] = _failure_reasons("dispatch-failed", exc)
        return receipt

    preexisting = frozenset(run.run_id for run in prior_runs)
    outcome = "run-not-found"
    run: WorkflowRunSummary | None = None
    for attempt in range(max(1, poll_attempts)):
        try:
            runs = client.list_validation_dispatch_runs(head_ref=pr.head_ref)
        except Exception as exc:
            receipt["decision"] = "correlation-failed"
            receipt["reason_codes"] = _failure_reasons("run-lookup-failed", exc)
            return receipt
        outcome, run = correlate_run(
            runs,
            expected_head_sha=expected_head_sha,
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
        return receipt

    receipt["decision"] = "dispatched"
    receipt["reason_codes"] = ["dispatch-correlated"]
    receipt["run_id_or_none"] = run.run_id
    receipt["run_url_or_none"] = run.url
    receipt["run_status_or_none"] = run.status
    receipt["run_conclusion_or_none"] = run.conclusion
    return receipt


def receipt_marker(trigger_id: str, comment_id: int) -> str:
    """Marker for one receipt per invoking comment.

    The logical trigger ID is stable across retries of the same PR head, so it
    alone would suppress the receipt for a retry after a blocked attempt. The
    invoking comment ID makes each owner command receive its own receipt while
    a re-run of the same comment still posts at most once.
    """
    return f"<!-- {RECEIPT_MARKER_PREFIX}{trigger_id}:{comment_id} -->"


def receipt_from_job_outputs(
    transport: dict,
    *,
    decision: str,
    reason_codes_csv: str,
    run_id: str,
    observed_head_sha: str,
    run_status: str,
    run_conclusion: str,
    dispatch_trigger_id: str,
) -> dict:
    """Rebuild the receipt in the low-privilege receipt job from dispatch job
    outputs, keeping the detailed reason codes. Every value is validated; an
    unrecognized value is dropped or fails the receipt closed."""
    receipt = _base_receipt(transport)
    trigger_id = receipt["trigger_id"]
    reasons = [code for code in reason_codes_csv.split(",") if code]
    if not reasons or not all(_REASON_CODE_PATTERN.fullmatch(code) for code in reasons):
        reasons = ["dispatch-job-no-output"]
        decision = "blocked"
    if decision not in {"dispatched", "duplicate", "blocked", "correlation-failed"}:
        decision = "blocked"
        reasons = ["dispatch-job-no-output"]
    if type(trigger_id) is not str or trigger_id != dispatch_trigger_id:
        decision = "blocked"
        reasons = ["receipt-trigger-mismatch"]
    receipt["decision"] = decision
    receipt["reason_codes"] = reasons
    if _SHA_PATTERN.fullmatch(observed_head_sha):
        receipt["observed_head_sha"] = observed_head_sha
    if run_id.isascii() and run_id.isdigit() and decision in {"dispatched", "duplicate", "blocked"}:
        receipt["run_id_or_none"] = int(run_id)
        receipt["run_url_or_none"] = (
            f"https://github.com/{receipt['repository']}/actions/runs/{int(run_id)}"
        )
    for key, value in (("run_status_or_none", run_status), ("run_conclusion_or_none", run_conclusion)):
        if _REASON_CODE_PATTERN.fullmatch(value.replace("_", "-")):
            receipt[key] = value
    return receipt


def render_receipt_comment(receipt: dict) -> str:
    trigger_id = receipt.get("trigger_id")
    lines = [
        receipt_marker(str(trigger_id), receipt.get("comment_id")),  # type: ignore[arg-type]
        "## Agent OS Draft final-candidate validation dispatch receipt (#2410)",
        "",
        f"- Operation: `{receipt.get('operation')}`",
        f"- Workflow: `{receipt.get('workflow')}` (hardcoded; no workflow input exists)",
        f"- Trigger: `{trigger_id}`",
        f"- Pull request: #{receipt.get('pr_number')}",
        f"- Expected head SHA: `{receipt.get('expected_head_sha')}`",
        f"- Observed head SHA: `{receipt.get('observed_head_sha')}`",
        f"- Decision: `{receipt.get('decision')}`",
        f"- Reasons: `{','.join(receipt.get('reason_codes') or [])}`",
        f"- Invoking comment: `{receipt.get('comment_id')}`",
        f"- Run ID: `{receipt.get('run_id_or_none')}`",
        f"- Run URL: {receipt.get('run_url_or_none')}",
        f"- Run status: `{receipt.get('run_status_or_none')}` / conclusion: `{receipt.get('run_conclusion_or_none')}`",
        "",
        "A dispatch is not validation. Authoritative evidence is the correlated "
        "run's terminal `agent-os/authoritative-aggregate` result on the exact "
        "head, read back through the canonical route. This receipt grants no "
        "Ready, merge, or closure authority.",
    ]
    return "\n".join(lines) + "\n"


def find_existing_receipt(comment_bodies: list[str], trigger_id: str, comment_id: int) -> bool:
    marker = receipt_marker(trigger_id, comment_id)
    return any(marker in (body or "") for body in comment_bodies)


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
            head_ref=pr.head.ref,
            head_sha=pr.head.sha,
            head_repo_full_name=pr.head.repo.full_name if pr.head.repo else None,
        )

    def list_validation_dispatch_runs(
        self, *, head_ref: str
    ) -> list[WorkflowRunSummary]:
        runs = self._workflow.get_runs(event="workflow_dispatch", branch=head_ref)
        summaries: list[WorkflowRunSummary] = []
        for run in runs[:MAX_RUNS_INSPECTED]:
            summaries.append(
                WorkflowRunSummary(
                    run_id=run.id,
                    url=run.html_url,
                    head_sha=run.head_sha,
                    created_at=run.created_at,
                    status=run.status,
                    conclusion=run.conclusion,
                )
            )
        return summaries

    def create_validation_dispatch(
        self, *, ref: str, pr_number: int, expected_head_sha: str
    ) -> None:
        created = self._workflow.create_dispatch(
            ref,
            {"pr_number": str(pr_number), "expected_head_sha": expected_head_sha},
        )
        if not created:
            raise RuntimeError("workflow dispatch was not accepted")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _dispatch_main(args: argparse.Namespace) -> int:
    transport = json.loads(Path(args.transport).read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for dispatch mode")
    if transport.get("repository") != args.repository:
        receipt = _base_receipt(transport)
        receipt["reason_codes"] = ["transport-repository-mismatch"]
        _write_json(Path(args.output), receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    client = _PyGithubClient(args.repository, token)
    receipt = execute_dispatch(transport, client)
    _write_json(Path(args.output), receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


def _receipt_main(args: argparse.Namespace) -> int:
    from github import Github  # imported lazily so tests need no PyGithub

    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for receipt mode")
    trigger_id = receipt.get("trigger_id")
    comment_id = receipt.get("comment_id")
    result = {"trigger_id": trigger_id, "posted": False, "reason": "not-attempted"}
    if type(trigger_id) is str and type(comment_id) is int:
        repo = Github(token).get_repo(args.repository)
        issue = repo.get_issue(args.issue_number)
        bodies = [comment.body or "" for comment in issue.get_comments()]
        if find_existing_receipt(bodies, trigger_id, comment_id):
            result["reason"] = "receipt-already-posted"
        else:
            issue.create_comment(render_receipt_comment(receipt))
            result = {"trigger_id": trigger_id, "posted": True, "reason": "receipt-posted"}
    _write_json(Path(args.output), result)
    print(json.dumps(result, sort_keys=True))
    return 0


def _assemble_main(args: argparse.Namespace) -> int:
    """Rebuild the receipt from dispatch job outputs passed via environment."""
    transport = json.loads(Path(args.transport).read_text(encoding="utf-8"))
    receipt = receipt_from_job_outputs(
        transport,
        decision=os.environ.get("DISPATCH_DECISION", ""),
        reason_codes_csv=os.environ.get("DISPATCH_REASON_CODES", ""),
        run_id=os.environ.get("DISPATCH_RUN_ID", ""),
        observed_head_sha=os.environ.get("DISPATCH_OBSERVED_HEAD_SHA", ""),
        run_status=os.environ.get("DISPATCH_RUN_STATUS", ""),
        run_conclusion=os.environ.get("DISPATCH_RUN_CONCLUSION", ""),
        dispatch_trigger_id=os.environ.get("DISPATCH_TRIGGER_ID", ""),
    )
    _write_json(Path(args.output), receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dispatch", "assemble", "receipt"), default="dispatch")
    parser.add_argument("--transport", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.mode in ("dispatch", "assemble"):
        if args.transport is None:
            parser.error(f"--transport is required in {args.mode} mode")
        return _dispatch_main(args) if args.mode == "dispatch" else _assemble_main(args)
    if args.receipt is None or args.issue_number is None:
        parser.error("--receipt and --issue-number are required in receipt mode")
    return _receipt_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
