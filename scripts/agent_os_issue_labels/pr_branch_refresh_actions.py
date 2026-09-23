"""Finite GitHub Actions ingress contract for governed PR refresh (#1807).

This module classifies only the owner-authored operation identity needed to route
an issue-comment event toward the existing #1187/#1365/#1381 refresh stack. It
never grants branch-refresh authority and never accepts shell text, repository,
branch, refspec, path, credential, or authorization inputs from the comment.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

_REPOSITORY = "Blummer92/agent-os"
_REPOSITORY_ID = 1289370915
_OWNER_LOGIN = "Blummer92"
_OWNER_ID = 32861845
_WORKFLOW_REF = (
    "Blummer92/agent-os/.github/workflows/"
    "agent-os-governed-invocation.yml@refs/heads/main"
)
_TRIGGER = re.compile(r"^/agent-os refresh-pr (?P<pr>[1-9][0-9]*)$")


@dataclass(frozen=True, slots=True)
class BranchRefreshActionsTrigger:
    status: str
    reason: str
    pr_number: int | None
    repository: str
    side_effects_performed: bool = field(default=False, init=False)
    branch_refresh_authorized: bool = field(default=False, init=False)
    label_write_authorized: bool = field(default=False, init=False)
    merge_authorized: bool = field(default=False, init=False)
    issue_closure_authorized: bool = field(default=False, init=False)


def classify_branch_refresh_actions_trigger(
    event: Mapping[str, object],
    *,
    repository: str,
    repository_id: int,
    ref: str,
    workflow_ref: str,
    run_attempt: int,
) -> BranchRefreshActionsTrigger:
    """Classify one fixed refresh operation without manufacturing authority."""
    if repository != _REPOSITORY or repository_id != _REPOSITORY_ID:
        return _blocked(repository, "repository-not-allowed")
    if ref != "refs/heads/main" or workflow_ref != _WORKFLOW_REF:
        return _blocked(repository, "workflow-source-not-canonical")
    if run_attempt != 1:
        return _blocked(repository, "rerun-not-allowed")
    if event.get("action") != "created":
        return _blocked(repository, "event-action-not-allowed")

    issue = event.get("issue")
    comment = event.get("comment")
    repo = event.get("repository")
    if not isinstance(issue, Mapping) or not isinstance(comment, Mapping) or not isinstance(repo, Mapping):
        return _blocked(repository, "event-shape-invalid")
    if issue.get("pull_request") is not None:
        return _blocked(repository, "pr-comment-not-allowed")
    if repo.get("id") != _REPOSITORY_ID or repo.get("full_name") != _REPOSITORY:
        return _blocked(repository, "event-repository-mismatch")

    actor = comment.get("user")
    body = comment.get("body")
    if not isinstance(actor, Mapping) or actor.get("login") != _OWNER_LOGIN or actor.get("id") != _OWNER_ID:
        return _blocked(repository, "actor-not-allowed")
    if not isinstance(body, str):
        return _blocked(repository, "comment-body-invalid")
    match = _TRIGGER.fullmatch(body)
    if match is None:
        return _blocked(repository, "operation-not-requested")

    pr_number = int(match.group("pr"))
    return BranchRefreshActionsTrigger(
        status="accepted",
        reason="finite-refresh-operation-requested",
        pr_number=pr_number,
        repository=repository,
    )


def classify_event_file(
    event_path: str,
    *,
    repository: str,
    repository_id: int,
    ref: str,
    workflow_ref: str,
    run_attempt: int,
) -> BranchRefreshActionsTrigger:
    path = Path(event_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("event payload must be an object")
    return classify_branch_refresh_actions_trigger(
        payload,
        repository=repository,
        repository_id=repository_id,
        ref=ref,
        workflow_ref=workflow_ref,
        run_attempt=run_attempt,
    )


def _blocked(repository: str, reason: str) -> BranchRefreshActionsTrigger:
    return BranchRefreshActionsTrigger(
        status="blocked",
        reason=reason,
        pr_number=None,
        repository=repository,
    )
