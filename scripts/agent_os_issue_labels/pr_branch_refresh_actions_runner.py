"""Finite GitHub Actions execution adapter for governed PR refresh (#1807).

The issue-comment trigger selects only a PR number. This adapter reacquires all
mutation authority and currentness from canonical GitHub evidence before calling
the existing #1402 ``refresh_pr`` facade. It introduces no branch-refresh
algorithm, retry path, credential store, or fallback transport.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Callable, Mapping

from .pr_branch_refresh_actions import (
    BranchRefreshActionsTrigger,
    classify_event_file,
)
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
from .pr_branch_refresh_operator import (
    build_branch_refresh_github_client,
    refresh_pr,
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(slots=True)
class PyGithubRefreshAuthorizationSourceTransport:
    """Read one complete bounded PR conversation through an injected PyGithub client."""

    github_client: object

    def __post_init__(self) -> None:
        if not hasattr(self.github_client, "get_repo"):
            raise TypeError("github_client must provide get_repo")

    def read_refresh_authorization_source(
        self, repository: str, pr_number: int
    ) -> RefreshAuthorizationSourceSnapshot:
        repo = self.github_client.get_repo(repository)
        owner = repo.owner
        issue = repo.get_issue(pr_number)

        comments: list[RefreshAuthorizationCommentSnapshot] = []
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
            if hasattr(created_at, "isoformat"):
                created_text = created_at.isoformat()
            else:
                created_text = str(created_at or "")
            comments.append(
                RefreshAuthorizationCommentSnapshot(
                    comment_id=int(comment.id),
                    author_login=author_login,
                    created_at=created_text,
                    body=str(getattr(comment, "body", "") or ""),
                )
            )

        owner_login = getattr(owner, "login", None)
        owner_type = getattr(owner, "type", None)
        if not isinstance(owner_login, str) or not owner_login:
            raise RuntimeError("repository owner unavailable")
        if not isinstance(owner_type, str) or not owner_type:
            raise RuntimeError("repository owner type unavailable")

        return RefreshAuthorizationSourceSnapshot(
            repository=repository,
            pr_number=pr_number,
            owner_login=owner_login,
            owner_type=owner_type,
            comments_complete=complete,
            comments=tuple(comments),
        )


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
        if self.receipt_publication_http_status is not None and not (
            100 <= self.receipt_publication_http_status <= 599
        ):
            raise ValueError("receipt_publication_http_status must be an HTTP status")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _sha40(value: object, field_name: str) -> str:
    text = str(value).lower()
    if _SHA40.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a lowercase 40-character SHA")
    return text


def _current_pr_evidence(
    github_client: object, repository: str, pr_number: int
) -> tuple[str, str, tuple[str, ...]]:
    repo = github_client.get_repo(repository)
    pr = repo.get_pull(pr_number)
    head_sha = _sha40(pr.head.sha, "head_sha")
    main_sha = _sha40(repo.get_branch("main").commit.sha, "main_sha")
    changed_paths = tuple(
        sorted(
            {
                str(item.filename)
                for item in pr.get_files()
                if isinstance(getattr(item, "filename", None), str)
                and item.filename
            }
        )
    )
    return head_sha, main_sha, changed_paths


def _receipt_dict(receipt: object) -> dict[str, object]:
    if is_dataclass(receipt):
        payload = asdict(receipt)
    elif isinstance(receipt, Mapping):
        payload = dict(receipt)
    else:
        raise TypeError("refresh receipt must be a dataclass or mapping")
    return payload


def _publication_status(error: Exception) -> int | None:
    status = getattr(error, "status", None)
    if isinstance(status, int) and 100 <= status <= 599:
        return status
    return None


def _blocked(
    trigger: BranchRefreshActionsTrigger,
    *reason_codes: str,
    authorization_id: str | None = None,
) -> BranchRefreshActionsExecutionResult:
    reasons = tuple(sorted(set(reason_codes or (trigger.reason,))))
    return BranchRefreshActionsExecutionResult(
        repository=trigger.repository,
        pr_number=trigger.pr_number,
        status="blocked",
        reason_codes=reasons,
        authorization_id=authorization_id,
    )


def run_branch_refresh_actions(
    *,
    trigger: BranchRefreshActionsTrigger,
    github_client: object,
    repository_root: str,
    invocation_id: str,
    environment: Mapping[str, str],
    refresh_callable: Callable[..., object] = refresh_pr,
) -> BranchRefreshActionsExecutionResult:
    """Reacquire canonical authority/currentness and invoke one refresh facade call."""
    if trigger.status != "accepted" or trigger.pr_number is None:
        return _blocked(trigger)
    if not isinstance(repository_root, str) or not repository_root:
        raise ValueError("repository_root is required")
    if not isinstance(invocation_id, str) or not invocation_id.strip():
        raise ValueError("invocation_id is required")
    if not isinstance(environment, Mapping):
        raise TypeError("environment must be a mapping")

    transport = PyGithubRefreshAuthorizationSourceTransport(github_client)
    source = reacquire_refresh_authorization_source(
        transport=transport,
        repository=trigger.repository,
        pr_number=trigger.pr_number,
    )
    if source.status is not RefreshAuthorizationSourceStatus.CURRENT:
        return _blocked(trigger, *source.reason_codes)

    try:
        head_sha, main_sha, changed_paths = _current_pr_evidence(
            github_client, trigger.repository, trigger.pr_number
        )
        resolved = resolve_branch_refresh_authorization(
            source.records,
            repository=trigger.repository,
            pr_number=trigger.pr_number,
            current_head_sha=head_sha,
            current_main_sha=main_sha,
            current_changed_paths=changed_paths,
        )
    except (TypeError, ValueError, RuntimeError):
        return _blocked(trigger, "actions.current-evidence-unavailable")

    if not resolved.applicable or resolved.authorization_id is None:
        return _blocked(
            trigger,
            *resolved.reason_codes,
            authorization_id=resolved.authorization_id,
        )

    receipt = refresh_callable(
        **resolved.refresh_pr_kwargs(
            repository_root=repository_root,
            invocation_id=invocation_id,
            environment=environment,
        )
    )
    payload = _receipt_dict(receipt)
    mutation_count = int(payload.get("mutation_count", 0))
    status = str(payload.get("status", "blocked"))
    reason_codes = tuple(
        sorted(
            {
                str(item)
                for item in payload.get("reason_codes", ())
                if isinstance(item, str) and item
            }
        )
    )
    side_effects = bool(payload.get("side_effects_performed", False))
    authorization_consumed = bool(payload.get("authorization_consumed", False))
    published = False

    if authorization_consumed:
        authorization_receipt = RefreshAuthorizationReceipt(
            schema_version="1.0",
            repository=trigger.repository,
            pr_number=trigger.pr_number,
            authorization_id=resolved.authorization_id,
            admitted_head_sha=head_sha,
            admitted_main_sha=main_sha,
            mutation_attempted=True,
            mutation_succeeded=(
                mutation_count == 1
                and isinstance(payload.get("new_head_sha"), str)
                and payload.get("new_head_sha") is not None
            ),
            terminal_status=status,
            reason_codes=reason_codes,
        )
        try:
            github_client.get_repo(trigger.repository).get_issue(
                trigger.pr_number
            ).create_comment(
                serialize_refresh_authorization_receipt(authorization_receipt)
            )
            published = True
        except Exception as error:
            http_status = _publication_status(error)
            publication_reasons = {"authorization.receipt-publication-failed"}
            if http_status is not None:
                publication_reasons.add(
                    f"authorization.receipt-publication-http-{http_status}"
                )
            return BranchRefreshActionsExecutionResult(
                repository=trigger.repository,
                pr_number=trigger.pr_number,
                status="needs-decision",
                reason_codes=tuple(sorted(set(reason_codes) | publication_reasons)),
                authorization_id=resolved.authorization_id,
                refresh_receipt=payload,
                authorization_receipt_published=False,
                receipt_publication_http_status=http_status,
                mutation_count=mutation_count,
                side_effects_performed=side_effects,
            )

    return BranchRefreshActionsExecutionResult(
        repository=trigger.repository,
        pr_number=trigger.pr_number,
        status=status,
        reason_codes=reason_codes,
        authorization_id=resolved.authorization_id,
        refresh_receipt=payload,
        authorization_receipt_published=published,
        mutation_count=mutation_count,
        side_effects_performed=side_effects,
    )


def _write_result(path: str, result: BranchRefreshActionsExecutionResult) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


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

    trigger = classify_event_file(
        args.event,
        repository=args.repository,
        repository_id=args.repository_id,
        ref=args.ref,
        workflow_ref=args.workflow_ref,
        run_attempt=args.run_attempt,
    )
    if trigger.status != "accepted":
        result = _blocked(trigger)
        _write_result(args.output, result)
        return 0

    try:
        client = build_branch_refresh_github_client(os.environ)
        result = run_branch_refresh_actions(
            trigger=trigger,
            github_client=client,
            repository_root=args.repository_root,
            invocation_id=args.invocation_id,
            environment=dict(os.environ),
        )
    except Exception:
        result = BranchRefreshActionsExecutionResult(
            repository=trigger.repository,
            pr_number=trigger.pr_number,
            status="needs-decision",
            reason_codes=("actions.runtime-failure",),
        )

    _write_result(args.output, result)
    return 0 if result.status == "converged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
