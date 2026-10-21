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


@dataclass(frozen=True, slots=True, kw_only=True)
class PullRequestState:
    state: str
    draft: bool
    base_ref: str
    head_ref: str | None
    head_sha: str | None


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
) -> list[str]:
    """Return fail-closed reason codes; an empty list means dispatch may proceed."""
    reasons: list[str] = []
    if pr.state != "open":
        reasons.append("pr-not-open")
    if not pr.draft:
        reasons.append("pr-not-draft")
    if pr.base_ref != "main":
        reasons.append("pr-base-not-main")
    if not pr.head_ref:
        reasons.append("pr-head-ref-missing")
    if pr.head_sha != expected_head_sha:
        reasons.append("pr-head-mismatch")
    return reasons


def select_duplicate_run(
    runs: list[WorkflowRunSummary], *, expected_head_sha: str
) -> WorkflowRunSummary | None:
    """Any earlier workflow_dispatch run for the exact head makes this a duplicate."""
    for run in runs:
        if run.head_sha == expected_head_sha:
            return run
    return None


def correlate_run(
    runs: list[WorkflowRunSummary],
    *,
    expected_head_sha: str,
    dispatched_at: datetime,
) -> tuple[str, WorkflowRunSummary | None]:
    """Bind the dispatch to exactly one created run, failing closed otherwise."""
    window_start = dispatched_at - CORRELATION_SKEW
    candidates = [
        run
        for run in runs
        if run.head_sha == expected_head_sha and run.created_at >= window_start
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

    pr = client.get_pull_request(pr_number)
    receipt["observed_head_sha"] = pr.head_sha
    receipt["head_ref"] = pr.head_ref
    reasons = verify_pr_state(pr, pr_number=pr_number, expected_head_sha=expected_head_sha)
    if reasons:
        receipt["reason_codes"] = reasons
        return receipt
    assert pr.head_ref is not None  # verified above

    prior_runs = client.list_validation_dispatch_runs(head_ref=pr.head_ref)
    duplicate = select_duplicate_run(prior_runs, expected_head_sha=expected_head_sha)
    if duplicate is not None:
        receipt["decision"] = "duplicate"
        receipt["reason_codes"] = ["duplicate-dispatch-prevented"]
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
    except Exception:  # dispatch transport failure: fail closed, no run identity claimed
        receipt["reason_codes"] = ["dispatch-failed"]
        return receipt

    outcome = "run-not-found"
    run: WorkflowRunSummary | None = None
    for attempt in range(max(1, poll_attempts)):
        runs = client.list_validation_dispatch_runs(head_ref=pr.head_ref)
        outcome, run = correlate_run(
            runs, expected_head_sha=expected_head_sha, dispatched_at=dispatch_time
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


def receipt_marker(trigger_id: str) -> str:
    return f"<!-- {RECEIPT_MARKER_PREFIX}{trigger_id} -->"


def render_receipt_comment(receipt: dict) -> str:
    trigger_id = receipt.get("trigger_id")
    lines = [
        receipt_marker(str(trigger_id)),
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
        f"- Run ID: `{receipt.get('run_id_or_none')}`",
        f"- Run URL: {receipt.get('run_url_or_none')}",
        "",
        "A dispatch is not validation. Authoritative evidence is the correlated "
        "run's terminal `agent-os/authoritative-aggregate` result on the exact "
        "head, read back through the canonical route. This receipt grants no "
        "Ready, merge, or closure authority.",
    ]
    return "\n".join(lines) + "\n"


def find_existing_receipt(comment_bodies: list[str], trigger_id: str) -> bool:
    marker = receipt_marker(trigger_id)
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
    result = {"trigger_id": trigger_id, "posted": False, "reason": "not-attempted"}
    if type(trigger_id) is str:
        repo = Github(token).get_repo(args.repository)
        issue = repo.get_issue(args.issue_number)
        bodies = [comment.body or "" for comment in issue.get_comments()]
        if find_existing_receipt(bodies, trigger_id):
            result["reason"] = "receipt-already-posted"
        else:
            issue.create_comment(render_receipt_comment(receipt))
            result = {"trigger_id": trigger_id, "posted": True, "reason": "receipt-posted"}
    _write_json(Path(args.output), result)
    print(json.dumps(result, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dispatch", "receipt"), default="dispatch")
    parser.add_argument("--transport", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.mode == "dispatch":
        if args.transport is None:
            parser.error("--transport is required in dispatch mode")
        return _dispatch_main(args)
    if args.receipt is None or args.issue_number is None:
        parser.error("--receipt and --issue-number are required in receipt mode")
    return _receipt_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
