"""Credential-free admission of one explicit owner request, not a scheduler."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID

from .catalog import ISSUE_NUMBER, REQUEST_ID

REPOSITORY = "Blummer92/agent-os"
REPOSITORY_ID = 1289370915
OWNER_ID = 32861845
WORKFLOW_REF = REPOSITORY + "/.github/workflows/agent-os-notion-lessons-write.yml@refs/heads/main"
COMMAND = "/agent-os notion-write " + REQUEST_ID
MAX_EVENT_BYTES = 64 * 1024


class WriteBlocked(ValueError):
    """Finite reason code; never include low-trust input or provider detail."""


def notion_id(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-fA-F-]{32,36}", value):
        raise WriteBlocked("invalid-notion-identity")
    try:
        return str(UUID(value))
    except ValueError:
        raise WriteBlocked("invalid-notion-identity") from None


@dataclass(frozen=True)
class AdmittedRequest:
    comment_id: int
    expected_page_id: str | None = None
    expected_revision: str | None = None


def admit(event: object, *, event_name: str, ref: str, workflow_ref: str,
          run_attempt: str) -> AdmittedRequest:
    """Reject replay, edits, PRs, foreign targets, actors and expanded commands."""
    if (event_name, ref, workflow_ref, run_attempt) != (
        "issue_comment", "refs/heads/main", WORKFLOW_REF, "1"
    ):
        raise WriteBlocked("untrusted-execution-context")
    if type(event) is not dict or event.get("action") != "created":
        raise WriteBlocked("created-comment-required")
    repository = event.get("repository", {})
    if (repository.get("full_name"), repository.get("id")) != (REPOSITORY, REPOSITORY_ID):
        raise WriteBlocked("repository-mismatch")
    issue = event.get("issue", {})
    if (issue.get("number"), issue.get("state")) != (ISSUE_NUMBER, "open") or "pull_request" in issue:
        raise WriteBlocked("open-canonical-issue-required")
    comment = event.get("comment", {})
    user = comment.get("user", {})
    if (user.get("id"), user.get("login"), user.get("type")) != (OWNER_ID, "Blummer92", "User"):
        raise WriteBlocked("explicit-owner-request-required")
    if type(comment.get("id")) is not int or comment["id"] < 1:
        raise WriteBlocked("comment-identity-required")
    created = comment.get("created_at")
    if type(created) is not str or created != comment.get("updated_at"):
        raise WriteBlocked("edited-comment-refused")
    body = comment.get("body")
    if body == COMMAND:
        return AdmittedRequest(comment["id"])
    if type(body) is not str or len(body) > 512 or not body.startswith(COMMAND + " "):
        raise WriteBlocked("finite-request-required")
    parts = body[len(COMMAND) + 1:].split(" ")
    if len(parts) != 2:
        raise WriteBlocked("exact-update-binding-required")
    page_id = notion_id(parts[0])
    revision = parts[1]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z", revision):
        raise WriteBlocked("exact-update-binding-required")
    try:
        datetime.fromisoformat(revision.replace("Z", "+00:00"))
    except ValueError:
        raise WriteBlocked("exact-update-binding-required") from None
    return AdmittedRequest(comment["id"], page_id, revision)
