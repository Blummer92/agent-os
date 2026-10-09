"""Finite GitHub Actions consumer for the fixed Ready-for-Review admission operation (#3446).

Consumes one accepted ``accepted-ready-admission-envelope`` transport record from
the existing governed issue-comment ingress, independently reacquires the PR
from GitHub, calls the single canonical evaluator
(``ready_for_review_admission.evaluate_ready_for_review_admission``), and writes
one bounded, reason-coded, non-authorizing receipt.

This module performs no GitHub write. It never marks a PR Ready; the host
consumer does that with native GitHub Mark Ready only after
``verify_ready_admission_receipt`` accepts the receipt against a fresh PR
readback. It accepts no shell, argv, module, URL, or caller-supplied evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .ready_for_review_admission import (
    DRAFT_FOCUSED_MODE,
    FINAL_CANDIDATE_MODE,
    evaluate_ready_for_review_admission,
)

RECEIPT_SCHEMA_VERSION = "1.0"
READY_ADMISSION_REASON = "accepted-ready-admission-envelope"
FOCUSED_CHECK_NAME = "Run validation plan"
AGGREGATE_CONTEXT = "agent-os/authoritative-aggregate"
AGGREGATE_JOB_NAME = "Run aggregate validation"
_MAX_ITEMS = 200
_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_STATUSES = frozenset({"success", "failure", "pending", "skipped", "missing"})


def body_revision(body: str | None) -> str:
    """Canonical PR body revision: sha256 of the UTF-8 body ("" when absent)."""
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReadyAdmissionTrigger:
    repository: str
    issue_number: int
    comment_id: int
    logical_trigger_id: str
    pr_number: int
    head_sha: str
    body_sha256: str


@dataclass(frozen=True, slots=True)
class PullRequestReadySnapshot:
    """Independently reacquired GitHub evidence for one PR head."""

    repository: str
    pr_number: int
    state: str
    draft: bool
    merged: bool
    head_sha: str
    title: str
    body: str
    requested_changes: bool
    blocking_unresolved: int
    focused_status: str
    aggregate_status: str
    validation_head_sha: str


class ReadyAdmissionEvidenceProvider(Protocol):
    def read_pull_request(self, repository: str, pr_number: int) -> PullRequestReadySnapshot: ...


def parse_trigger(transport: object, *, repository: str) -> tuple[ReadyAdmissionTrigger | None, str | None]:
    """Re-validate the ingress record; return (trigger, refusal_reason)."""
    if type(transport) is not dict:
        return None, "transport-malformed"
    if transport.get("status") != "accepted" or transport.get("reason") != READY_ADMISSION_REASON:
        return None, "transport-not-ready-admission"
    if transport.get("repository") != repository or not _REPOSITORY.fullmatch(repository):
        return None, "repository-mismatch"
    pr_number = transport.get("ready_admission_pr_number_or_none")
    head = transport.get("ready_admission_head_sha_or_none")
    body = transport.get("ready_admission_body_sha256_or_none")
    issue = transport.get("issue_number")
    comment = transport.get("comment_id")
    trigger_id = transport.get("logical_trigger_id_or_none")
    if type(pr_number) is not int or pr_number < 1 or type(issue) is not int or type(comment) is not int:
        return None, "transport-malformed"
    if type(head) is not str or not _SHA40.fullmatch(head):
        return None, "transport-malformed"
    if type(body) is not str or not _SHA256.fullmatch(body):
        return None, "transport-malformed"
    if type(trigger_id) is not str or not trigger_id:
        return None, "transport-malformed"
    return ReadyAdmissionTrigger(repository, issue, comment, trigger_id, pr_number, head, body), None


def _receipt(trigger: ReadyAdmissionTrigger | None, *, repository: str, admitted: bool, reasons: Iterable[str],
             next_action: str, provisional: bool = False, rollback: bool = False,
             observed_head: str | None = None, observed_body: str | None = None,
             aggregate: str | None = None, focused: str | None = None) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation": "ready-admit",
        "repository": repository,
        "pr_number": trigger.pr_number if trigger else None,
        "logical_trigger_id": trigger.logical_trigger_id if trigger else None,
        "expected_head_sha": trigger.head_sha if trigger else None,
        "expected_body_sha256": trigger.body_sha256 if trigger else None,
        "observed_head_sha": observed_head,
        "observed_body_sha256": observed_body,
        "focused_status": focused,
        "aggregate_status": aggregate,
        "transition_admissible": admitted,
        "provisional_ready": provisional,
        "rollback_to_draft_required": rollback,
        "reason_codes": sorted(set(reasons)),
        "next_action": next_action,
    }
    receipt_id = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        **core,
        "receipt_id": f"ready-admission-receipt:{receipt_id}",
        "ready_for_review_authorized": False,
        "merge_authorized": False,
        "issue_closure_authorized": False,
        "workflow_authorized": False,
        "protected_setting_authorized": False,
        "production_authorized": False,
        "external_system_write_authorized": False,
        "side_effects_performed": False,
    }


def evaluate_ready_admission(transport: object, *, repository: str,
                             provider: ReadyAdmissionEvidenceProvider) -> dict[str, object]:
    """Produce one fail-closed receipt for one accepted Ready-admission envelope."""
    trigger, refusal = parse_trigger(transport, repository=repository)
    if trigger is None:
        return _receipt(None, repository=repository, admitted=False, reasons=(refusal or "transport-malformed",),
                        next_action="resubmit-fixed-ready-admission-request")
    try:
        snap = provider.read_pull_request(repository, trigger.pr_number)
    except Exception:
        return _receipt(trigger, repository=repository, admitted=False, reasons=("pr-evidence-unavailable",),
                        next_action="retry-with-fresh-ready-admission-request")
    observed_body = body_revision(snap.body)
    refused = _binding_refusals(trigger, snap, observed_body)
    if refused:
        return _receipt(trigger, repository=repository, admitted=False, reasons=refused,
                        next_action="reacquire-pr-and-resubmit-ready-admission",
                        observed_head=snap.head_sha, observed_body=observed_body,
                        aggregate=snap.aggregate_status, focused=snap.focused_status)
    mode = FINAL_CANDIDATE_MODE if snap.aggregate_status == "success" else DRAFT_FOCUSED_MODE
    try:
        result = evaluate_ready_for_review_admission(
            repository=repository,
            pr_number=trigger.pr_number,
            pr_lifecycle_state="draft" if snap.draft and snap.state == "open" and not snap.merged else "not-draft",
            expected_head_sha=trigger.head_sha,
            observed_head_sha=snap.head_sha,
            validation_head_sha=snap.validation_head_sha,
            validation_admission_mode=mode,
            aggregate_status=snap.aggregate_status,
            focused_status=snap.focused_status,
            requested_changes=snap.requested_changes,
            blocking_unresolved=snap.blocking_unresolved,
            # The ingress already admitted only the allowed owner actor's exact fixed
            # comment; that comment is the explicit Ready request bound to this PR/head/body.
            ready_for_review_authority_supplied=True,
            pr_title=snap.title,
            pr_body=snap.body,
            # No canonical close-issue authorization is reacquirable here, so any
            # GitHub-effective closing reference fails closed.
            closure_admissions=(),
        )
    except (TypeError, ValueError):
        return _receipt(trigger, repository=repository, admitted=False, reasons=("pr-evidence-invalid",),
                        next_action="reacquire-pr-and-resubmit-ready-admission",
                        observed_head=snap.head_sha, observed_body=observed_body)
    return _receipt(trigger, repository=repository, admitted=result.transition_admissible,
                    reasons=result.reason_codes, next_action=result.next_action,
                    provisional=result.provisional_ready, rollback=result.rollback_to_draft_required,
                    observed_head=snap.head_sha, observed_body=observed_body,
                    aggregate=snap.aggregate_status, focused=snap.focused_status)


def _binding_refusals(trigger: ReadyAdmissionTrigger, snap: PullRequestReadySnapshot, observed_body: str) -> list[str]:
    reasons: list[str] = []
    if snap.repository.lower() != trigger.repository.lower():
        reasons.append("repository-mismatch")
    if snap.pr_number != trigger.pr_number:
        reasons.append("pr-identity-mismatch")
    if snap.head_sha != trigger.head_sha:
        reasons.append("stale-head")
    if observed_body != trigger.body_sha256:
        reasons.append("stale-body-revision")
    if snap.focused_status not in _STATUSES or snap.aggregate_status not in _STATUSES:
        reasons.append("validation-status-uninterpretable")
    return reasons


# --------------------------------------------------------------------- host side

def verify_ready_admission_receipt(
    receipt: object,
    *,
    repository: str,
    pr_number: int,
    expected_trigger_id: str,
    current_head_sha: str,
    current_body: str | None,
    consumed_receipt_ids: frozenset[str] = frozenset(),
) -> tuple[bool, tuple[str, ...]]:
    """Host-side gate run against a fresh PR readback immediately before native Mark Ready.

    Returns ``(may_mark_ready, reason_codes)``. Fails closed on a missing, forged,
    malformed, duplicate, stale, or non-admitting receipt.
    """
    if type(receipt) is not dict:
        return False, ("receipt-missing",)
    reasons: list[str] = []
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION or receipt.get("operation") != "ready-admit":
        reasons.append("receipt-malformed")
    for flag in ("ready_for_review_authorized", "merge_authorized", "issue_closure_authorized",
                 "workflow_authorized", "protected_setting_authorized", "production_authorized",
                 "external_system_write_authorized", "side_effects_performed"):
        if receipt.get(flag) is not False:
            reasons.append("receipt-malformed")
            break
    core = {k: v for k, v in receipt.items()
            if k not in {"receipt_id", "ready_for_review_authorized", "merge_authorized", "issue_closure_authorized",
                         "workflow_authorized", "protected_setting_authorized", "production_authorized",
                         "external_system_write_authorized", "side_effects_performed"}}
    expected_id = "ready-admission-receipt:" + hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt_id = receipt.get("receipt_id")
    if receipt_id != expected_id:
        reasons.append("receipt-forged")
    elif receipt_id in consumed_receipt_ids:
        reasons.append("receipt-duplicate")
    if receipt.get("repository") != repository or receipt.get("pr_number") != pr_number:
        reasons.append("receipt-identity-mismatch")
    if receipt.get("logical_trigger_id") != expected_trigger_id:
        reasons.append("receipt-trigger-mismatch")
    if receipt.get("expected_head_sha") != current_head_sha or receipt.get("observed_head_sha") != current_head_sha:
        reasons.append("receipt-stale-head")
    if receipt.get("expected_body_sha256") != body_revision(current_body) or \
            receipt.get("observed_body_sha256") != body_revision(current_body):
        reasons.append("receipt-stale-body")
    if receipt.get("transition_admissible") is not True:
        reasons.append("receipt-not-admitting")
    return (not reasons), tuple(dict.fromkeys(reasons))


def run_ready_batch(requests: Iterable[Mapping[str, object]],
                    decide: Callable[[Mapping[str, object]], tuple[bool, tuple[str, ...]]]) -> list[dict[str, object]]:
    """Finite batch cursor: record each item's disposition and continue past item-local blockers."""
    dispositions: list[dict[str, object]] = []
    for index, request in enumerate(requests):
        if index >= _MAX_ITEMS:
            dispositions.append({"pr_number": None, "disposition": "batch-bound-exceeded", "reason_codes": []})
            break
        try:
            admitted, reasons = decide(request)
        except Exception:
            admitted, reasons = False, ("item-evaluation-failed",)
        dispositions.append({
            "pr_number": request.get("pr_number"),
            "disposition": "ready-eligible" if admitted else "blocked-item-local",
            "reason_codes": list(reasons),
        })
    return dispositions


# ------------------------------------------------------------------- PyGithub provider

class PyGithubReadyAdmissionProvider:
    """Read-only GitHub evidence provider (PR, reviews, review threads, checks, statuses)."""

    _THREADS = ("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)"
                "{pullRequest(number:$number){reviewThreads(first:100){pageInfo{hasNextPage}"
                "nodes{isResolved isOutdated}}}}}")

    def __init__(self, github_client: object) -> None:
        if not hasattr(github_client, "get_repo"):
            raise TypeError("github_client must provide get_repo")
        self._client = github_client

    def read_pull_request(self, repository: str, pr_number: int) -> PullRequestReadySnapshot:
        repo = self._client.get_repo(repository)
        pr = repo.get_pull(pr_number)
        head = pr.head.sha
        latest: dict[str, str] = {}
        for index, review in enumerate(pr.get_reviews()):
            if index >= _MAX_ITEMS * 5:
                raise RuntimeError("review evidence incomplete")
            if review.state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"} and review.user is not None:
                latest[review.user.login] = review.state
        owner, name = repository.split("/", 1)
        _, data = self._client.requester.graphql_query(
            self._THREADS, {"owner": owner, "name": name, "number": pr_number})
        threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        if threads["pageInfo"]["hasNextPage"]:
            raise RuntimeError("review thread evidence incomplete")
        unresolved = sum(1 for node in threads["nodes"] if not node["isResolved"] and not node["isOutdated"])
        commit = repo.get_commit(head)
        focused = "missing"
        aggregate_job = "missing"
        for index, run in enumerate(commit.get_check_runs()):
            if index >= _MAX_ITEMS:
                raise RuntimeError("check evidence incomplete")
            if run.name == FOCUSED_CHECK_NAME:
                focused = _check_status(run.status, run.conclusion)
            elif run.name == AGGREGATE_JOB_NAME:
                aggregate_job = _check_status(run.status, run.conclusion)
        aggregate = aggregate_job
        for index, status in enumerate(commit.get_statuses()):  # newest first
            if index >= _MAX_ITEMS:
                break
            if status.context == AGGREGATE_CONTEXT:
                aggregate = {"success": "success", "pending": "pending"}.get(status.state, "failure")
                break
        return PullRequestReadySnapshot(
            repository=repository, pr_number=pr_number, state=pr.state, draft=bool(pr.draft),
            merged=bool(pr.merged), head_sha=head, title=pr.title or "", body=pr.body or "",
            requested_changes="CHANGES_REQUESTED" in latest.values(), blocking_unresolved=unresolved,
            focused_status=focused, aggregate_status=aggregate, validation_head_sha=head)


def _check_status(status: str | None, conclusion: str | None) -> str:
    if status != "completed":
        return "pending"
    if conclusion == "success":
        return "success"
    if conclusion == "skipped":
        return "skipped"
    return "failure"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate one fixed Ready-for-Review admission request")
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        transport = json.loads(args.transport.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        transport = None
    try:
        from scripts.agent_os_github_issue_provider.auth import build_token_client

        provider: ReadyAdmissionEvidenceProvider = PyGithubReadyAdmissionProvider(
            build_token_client(dict(os.environ), user_agent="agent-os-ready-admission/1"))
    except Exception:
        provider = _UnavailableProvider()
    receipt = evaluate_ready_admission(transport, repository=args.repository, provider=provider)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


class _UnavailableProvider:
    def read_pull_request(self, repository: str, pr_number: int) -> PullRequestReadySnapshot:
        raise RuntimeError("github client unavailable")


if __name__ == "__main__":
    raise SystemExit(main())
