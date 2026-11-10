"""Finite GitHub Actions execution adapter for governed PR refresh (#1807)."""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Callable, Mapping

from .pr_branch_refresh_actions import BranchRefreshActionsTrigger, classify_event_file
from .pr_branch_refresh_authorization import resolve_branch_refresh_authorization
from .pr_branch_refresh_authorization_source import (
    MAX_COMMENTS,
    RefreshAuthorizationCommentSnapshot,
    RefreshAuthorizationReceipt,
    RefreshAuthorizationSourceSnapshot,
    RefreshAuthorizationSourceStatus,
    reacquire_refresh_authorization_source,
    serialize_refresh_authorization_receipt,
)
from .pr_branch_refresh_operator import build_branch_refresh_github_client, refresh_pr

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
# Bounded terminal marker (#3463): one line in ordinary Actions job logs.
# The payload is a strict projection of the result, never the full receipt:
# no refresh-receipt blob, no environment, no exception text, no credential
# can reach stdout through this line.
RESULT_MARKER = "agent-os-pr-refresh-result/v1"


@dataclass(slots=True)
class PyGithubRefreshAuthorizationSourceTransport:
    github_client: object

    def __post_init__(self) -> None:
        if not hasattr(self.github_client, "get_repo"):
            raise TypeError("github_client must provide get_repo")

    def read_refresh_authorization_source(self, repository: str, pr_number: int) -> RefreshAuthorizationSourceSnapshot:
        repo = self.github_client.get_repo(repository)
        owner = repo.owner
        issue = repo.get_issue(pr_number)
        comments = []
        complete = True
        for index, comment in enumerate(issue.get_comments()):
            if index >= MAX_COMMENTS:
                complete = False
                break
            author = getattr(comment, "user", None)
            author_login = getattr(author, "login", None)
            if not isinstance(author_login, str) or not author_login:
                raise RuntimeError("comment author unavailable")
            created_at = getattr(comment, "created_at", None)
            created_text = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or "")
            comments.append(RefreshAuthorizationCommentSnapshot(comment_id=int(comment.id), author_login=author_login, created_at=created_text, body=str(getattr(comment, "body", "") or "")))
        owner_login = getattr(owner, "login", None)
        owner_type = getattr(owner, "type", None)
        if not isinstance(owner_login, str) or not owner_login:
            raise RuntimeError("repository owner unavailable")
        if not isinstance(owner_type, str) or not owner_type:
            raise RuntimeError("repository owner type unavailable")
        return RefreshAuthorizationSourceSnapshot(repository=repository, pr_number=pr_number, owner_login=owner_login, owner_type=owner_type, comments_complete=complete, comments=tuple(comments))


@dataclass(frozen=True, slots=True)
class BranchRefreshActionsExecutionResult:
    repository: str
    pr_number: int | None
    status: str
    reason_codes: tuple[str, ...]
    authorization_id: str | None = None
    refresh_receipt: dict[str, object] | None = None
    authorization_receipt_published: bool = False
    receipt_publication_http_status: int | None = None
    mutation_count: int = 0
    side_effects_performed: bool = False
    # Correlation evidence only; neither field grants authority.
    invocation_id: str | None = None
    trigger_comment_id: int | None = None
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)
    workflow_authorized: bool = field(default=False, init=False)
    credential_change_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.mutation_count not in {0, 1}:
            raise ValueError("mutation_count must be 0 or 1")
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("reason_codes must be sorted and unique")
        if self.side_effects_performed and self.mutation_count != 1:
            raise ValueError("branch side effects require one mutation attempt")
        if self.receipt_publication_http_status is not None and not (100 <= self.receipt_publication_http_status <= 599):
            raise ValueError("receipt_publication_http_status must be an HTTP status")
        if self.invocation_id is not None and (not isinstance(self.invocation_id, str) or not self.invocation_id.strip()):
            raise ValueError("invocation_id must be a non-empty string when present")
        if self.trigger_comment_id is not None and (type(self.trigger_comment_id) is not int or self.trigger_comment_id < 1):
            raise ValueError("trigger_comment_id must be a positive integer when present")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha40(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA40.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase 40-character SHA")
    return value


def _strict_receipt_bool(payload: Mapping[str, object], field_name: str) -> bool:
    value = payload.get(field_name, False)
    if type(value) is not bool:
        raise ValueError(f"refresh receipt {field_name} must be a boolean")
    return value


def _strict_receipt_fields(payload: Mapping[str, object]) -> tuple[int, str, tuple[str, ...]]:
    mutation_count = payload.get("mutation_count", 0)
    if type(mutation_count) is not int or mutation_count not in {0, 1}:
        raise ValueError("refresh receipt mutation_count must be 0 or 1")
    status = payload.get("status", "blocked")
    if type(status) is not str or not status.strip():
        raise ValueError("refresh receipt status must be a non-empty string")
    raw_reasons = payload.get("reason_codes", ())
    if type(raw_reasons) not in {tuple, list}:
        raise ValueError("refresh receipt reason_codes must be a list or tuple")
    if any(type(item) is not str or not item for item in raw_reasons):
        raise ValueError("refresh receipt reason_codes must contain non-empty strings")
    return mutation_count, status, tuple(sorted(set(raw_reasons)))


def _current_pr_evidence(github_client: object, repository: str, pr_number: int) -> tuple[str, str, tuple[str, ...]]:
    repo = github_client.get_repo(repository)
    pr = repo.get_pull(pr_number)
    head_sha = _sha40(pr.head.sha, "head_sha")
    main_sha = _sha40(repo.get_branch("main").commit.sha, "main_sha")
    changed_paths = tuple(sorted({str(item.filename) for item in pr.get_files() if isinstance(getattr(item, "filename", None), str) and item.filename}))
    return head_sha, main_sha, changed_paths


def _receipt_dict(receipt: object) -> dict[str, object]:
    if is_dataclass(receipt):
        return asdict(receipt)
    if isinstance(receipt, Mapping):
        return dict(receipt)
    raise TypeError("refresh receipt must be a dataclass or mapping")


def _publication_status(error: Exception) -> int | None:
    status = getattr(error, "status", None)
    return status if isinstance(status, int) and 100 <= status <= 599 else None


def _blocked(trigger: BranchRefreshActionsTrigger, *reason_codes: str, authorization_id: str | None = None, invocation_id: str | None = None, trigger_comment_id: int | None = None) -> BranchRefreshActionsExecutionResult:
    if trigger_comment_id is None:
        trigger_comment_id = getattr(trigger, "trigger_comment_id", None)
    return BranchRefreshActionsExecutionResult(repository=trigger.repository, pr_number=trigger.pr_number, status="blocked", reason_codes=tuple(sorted(set(reason_codes or (trigger.reason,)))), authorization_id=authorization_id, invocation_id=invocation_id, trigger_comment_id=trigger_comment_id)


def format_refresh_result_line(result: BranchRefreshActionsExecutionResult) -> str:
    """Render the single bounded terminal result line for one runner outcome.

    Only fixed, coded fields are projected; the refresh receipt, environment,
    and any exception text are deliberately excluded, so stdout can never
    carry a token, secret, or unbounded provider message through this line.
    The output is deterministic: canonical compact JSON with sorted keys.
    """
    if type(result) is not BranchRefreshActionsExecutionResult:
        raise TypeError("result must be exact BranchRefreshActionsExecutionResult")
    # A blank repository is not a real repository: it is emitted as null so
    # even a malformed-CLI invocation still yields exactly one parseable
    # marker (QA F1). A non-string repository remains a hard error.
    if result.repository is not None and not isinstance(result.repository, str):
        raise ValueError("result repository must be a string when present")
    if not isinstance(result.status, str) or not result.status.strip():
        raise ValueError("result status is required")
    if type(result.reason_codes) is not tuple or any(type(code) is not str or not code for code in result.reason_codes):
        raise ValueError("result reason_codes must be non-empty strings")
    if result.authorization_id is not None and not isinstance(result.authorization_id, str):
        raise ValueError("result authorization_id must be a string when present")
    payload: dict[str, object] = {
        "repository": result.repository if result.repository else None,
        "pr_number": result.pr_number,
        "status": result.status,
        "reason_codes": sorted(set(result.reason_codes)),
        "authorization_id": result.authorization_id,
        "invocation_id": result.invocation_id,
        "trigger_comment_id": result.trigger_comment_id,
        "mutation_count": result.mutation_count,
        "side_effects_performed": result.side_effects_performed,
        "authorization_receipt_published": result.authorization_receipt_published,
        "receipt_publication_http_status": result.receipt_publication_http_status,
    }
    return RESULT_MARKER + " " + json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def emit_refresh_result(result: BranchRefreshActionsExecutionResult) -> str:
    """Print exactly one terminal result line and return it."""
    line = format_refresh_result_line(result)
    print(line)
    return line


def run_branch_refresh_actions(*, trigger: BranchRefreshActionsTrigger, github_client: object, repository_root: str, invocation_id: str, environment: Mapping[str, str], refresh_callable: Callable[..., object] = refresh_pr) -> BranchRefreshActionsExecutionResult:
    # Correlation is validated first so even a blocked trigger carries the
    # invocation id a log reader needs; a missing/malformed id fails closed
    # instead of producing an uncorrelated result.
    if not isinstance(invocation_id, str) or not invocation_id.strip():
        raise ValueError("invocation_id is required")
    if trigger.status != "accepted" or trigger.pr_number is None:
        return _blocked(trigger, invocation_id=invocation_id)
    if not isinstance(repository_root, str) or not repository_root:
        raise ValueError("repository_root is required")
    if not isinstance(environment, Mapping):
        raise TypeError("environment must be a mapping")

    transport = PyGithubRefreshAuthorizationSourceTransport(github_client)
    try:
        head_sha, main_sha, changed_paths = _current_pr_evidence(github_client, trigger.repository, trigger.pr_number)
        source = reacquire_refresh_authorization_source(
            transport=transport,
            repository=trigger.repository,
            pr_number=trigger.pr_number,
            current_head_sha=head_sha,
            current_main_sha=main_sha,
        )
        if source.status is not RefreshAuthorizationSourceStatus.CURRENT:
            return _blocked(trigger, *source.reason_codes, invocation_id=invocation_id)
        resolved = resolve_branch_refresh_authorization(source.records, repository=trigger.repository, pr_number=trigger.pr_number, current_head_sha=head_sha, current_main_sha=main_sha, current_changed_paths=changed_paths)
    except (TypeError, ValueError, RuntimeError):
        return _blocked(trigger, "actions.current-evidence-unavailable", invocation_id=invocation_id)
    if not resolved.applicable or resolved.authorization_id is None:
        return _blocked(trigger, *resolved.reason_codes, authorization_id=resolved.authorization_id, invocation_id=invocation_id)

    receipt = refresh_callable(**resolved.refresh_pr_kwargs(repository_root=repository_root, invocation_id=invocation_id, environment=environment))
    payload = _receipt_dict(receipt)
    try:
        mutation_count, status, reason_codes = _strict_receipt_fields(payload)
        side_effects = _strict_receipt_bool(payload, "side_effects_performed")
        authorization_consumed = _strict_receipt_bool(payload, "authorization_consumed")
    except ValueError:
        return BranchRefreshActionsExecutionResult(repository=trigger.repository, pr_number=trigger.pr_number, status="needs-decision", reason_codes=("actions.malformed-refresh-receipt",), authorization_id=resolved.authorization_id, refresh_receipt=payload, mutation_count=0, side_effects_performed=False, invocation_id=invocation_id, trigger_comment_id=trigger.trigger_comment_id)
    published = False

    if authorization_consumed:
        authorization_receipt = RefreshAuthorizationReceipt(schema_version="1.0", repository=trigger.repository, pr_number=trigger.pr_number, authorization_id=resolved.authorization_id, admitted_head_sha=head_sha, admitted_main_sha=main_sha, mutation_attempted=True, mutation_succeeded=(status == "converged" and mutation_count == 1 and isinstance(payload.get("new_head_sha"), str) and payload.get("new_head_sha") is not None), terminal_status=status, reason_codes=reason_codes)
        try:
            github_client.get_repo(trigger.repository).get_issue(trigger.pr_number).create_comment(serialize_refresh_authorization_receipt(authorization_receipt))
            published = True
        except Exception as error:
            http_status = _publication_status(error)
            publication_reasons = {"authorization.receipt-publication-failed"}
            if http_status is not None:
                publication_reasons.add(f"authorization.receipt-publication-http-{http_status}")
            return BranchRefreshActionsExecutionResult(repository=trigger.repository, pr_number=trigger.pr_number, status="needs-decision", reason_codes=tuple(sorted(set(reason_codes) | publication_reasons)), authorization_id=resolved.authorization_id, refresh_receipt=payload, authorization_receipt_published=False, receipt_publication_http_status=http_status, mutation_count=mutation_count, side_effects_performed=side_effects, invocation_id=invocation_id, trigger_comment_id=trigger.trigger_comment_id)

    return BranchRefreshActionsExecutionResult(repository=trigger.repository, pr_number=trigger.pr_number, status=status, reason_codes=reason_codes, authorization_id=resolved.authorization_id, refresh_receipt=payload, authorization_receipt_published=published, mutation_count=mutation_count, side_effects_performed=side_effects, invocation_id=invocation_id, trigger_comment_id=trigger.trigger_comment_id)


def _write_result(path: str, result: BranchRefreshActionsExecutionResult) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _publish_result(path: str, result: BranchRefreshActionsExecutionResult) -> None:
    """Write result.json and emit exactly one terminal result line.

    The marker is printed even if the artifact write fails, so the job log
    still carries the reason code; the write error then propagates unchanged.
    """
    try:
        _write_result(path, result)
    finally:
        emit_refresh_result(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one finite governed PR refresh")
    parser.add_argument("--event", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True, type=int)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if not isinstance(args.repository, str) or not args.repository.strip() or not isinstance(args.invocation_id, str) or not args.invocation_id.strip():
        # Malformed CLI correlation (blank repository and/or invocation id):
        # fail closed with a marker that honestly carries null correlation,
        # rather than an uncorrelated blocked result or a bare traceback.
        # QA F1: a blank repository previously raised before any marker.
        result = BranchRefreshActionsExecutionResult(
            repository=args.repository if isinstance(args.repository, str) and args.repository.strip() else None,  # type: ignore[arg-type]
            pr_number=None, status="needs-decision", reason_codes=("actions.runtime-failure",),
            invocation_id=args.invocation_id if isinstance(args.invocation_id, str) and args.invocation_id.strip() else None,
        )
        _publish_result(args.output, result)
        return 1
    try:
        trigger = classify_event_file(args.event, repository=args.repository, repository_id=args.repository_id, ref=args.ref, workflow_ref=args.workflow_ref, run_attempt=args.run_attempt)
    except Exception:
        # Parser-rejected / unreadable event: a runtime failure, not a silent
        # exit. The trigger comment id is unknowable here, so it stays null.
        result = BranchRefreshActionsExecutionResult(repository=args.repository, pr_number=None, status="needs-decision", reason_codes=("actions.runtime-failure",), invocation_id=args.invocation_id)
        _publish_result(args.output, result)
        return 1
    if trigger.status != "accepted":
        # Existing exit-code contract preserved: a parser/classifier block is
        # not a runner failure, but it now leaves a terminal marker behind.
        result = _blocked(trigger, invocation_id=args.invocation_id)
        _publish_result(args.output, result)
        return 0
    try:
        client = build_branch_refresh_github_client(os.environ)
        result = run_branch_refresh_actions(trigger=trigger, github_client=client, repository_root=args.repository_root, invocation_id=args.invocation_id, environment=dict(os.environ))
    except Exception:
        result = BranchRefreshActionsExecutionResult(repository=trigger.repository, pr_number=trigger.pr_number, status="needs-decision", reason_codes=("actions.runtime-failure",), invocation_id=args.invocation_id, trigger_comment_id=trigger.trigger_comment_id)
    _publish_result(args.output, result)
    return 0 if result.status == "converged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
