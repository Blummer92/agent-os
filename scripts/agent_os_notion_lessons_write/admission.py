"""Credential-free admission of one explicit owner request, not a scheduler."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import json
import urllib.request
from uuid import UUID

from .catalog import LESSON_ID, REQUEST_ID, entry_for

REPOSITORY = "Blummer92/agent-os"
REPOSITORY_ID = 1289370915
OWNER_ID = 32861845
WORKFLOW_REF = REPOSITORY + "/.github/workflows/agent-os-notion-lessons-write.yml@refs/heads/main"
COMMAND_PREFIX = "/agent-os notion-write "
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
    expected_lesson_id: str | None = None
    expected_revision: str | None = None
    request_id: str = REQUEST_ID
    issue_number: int = 0


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
    # #3417: the request surface is any ordinary (non-PR) issue in this
    # repository. Issue open/closed state is not an authorization signal: the
    # reviewed catalog entry authorizes content, the owner comment the write.
    issue = event.get("issue", {})
    if (not isinstance(issue, dict) or type(issue.get("number")) is not int
            or issue["number"] < 1 or "pull_request" in issue):
        raise WriteBlocked("ordinary-issue-request-required")
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
    if type(body) is not str or len(body) > 512 or not body.startswith(COMMAND_PREFIX):
        raise WriteBlocked("finite-request-required")
    parts = body[len(COMMAND_PREFIX):].split(" ")
    request_id = parts.pop(0)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", request_id):
        raise WriteBlocked("finite-request-required")
    try:
        target = entry_for(request_id)["target_lesson_id"]
    except ValueError:
        raise WriteBlocked("finite-request-required") from None
    if target is None:
        # Create entry: an update binding can never retarget it.
        if parts:
            raise WriteBlocked("update-binding-not-applicable")
        return AdmittedRequest(comment["id"], request_id=request_id, issue_number=issue["number"])
    if len(parts) != 2:
        raise WriteBlocked("exact-update-binding-required")
    lesson_id, revision = parts
    if not LESSON_ID.fullmatch(lesson_id) or lesson_id != target:
        raise WriteBlocked("reviewed-target-lesson-mismatch")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z", revision):
        raise WriteBlocked("exact-update-binding-required")
    try:
        datetime.fromisoformat(revision.replace("Z", "+00:00"))
    except ValueError:
        raise WriteBlocked("exact-update-binding-required") from None
    return AdmittedRequest(comment["id"], lesson_id, revision, request_id, issue["number"])


def _get(path: str) -> dict:
    # Fixed internal paths only, never a user-provided URL. Refuse redirects.
    from .live import _NoRedirect
    request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + path,
                                     headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": "agent-os-lessons-write"})
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=15) as response:
        raw = response.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise WriteBlocked("canonical-owner-request-unavailable")
    value = json.loads(raw)
    if type(value) is not dict:
        raise WriteBlocked("canonical-owner-request-unavailable")
    return value


def verify_current_request(event: dict, request: AdmittedRequest, *, context: dict) -> None:
    try:
        issue = _get(f"/issues/{request.issue_number}")
        comment = _get(f"/issues/comments/{request.comment_id}")
        if comment.get("issue_url") != f"https://api.github.com/repos/{REPOSITORY}/issues/{request.issue_number}":
            raise WriteBlocked("canonical-comment-target-mismatch")
        current = {**event, "issue": issue, "comment": comment}
        if admit(current, **context) != request or comment.get("body") != event["comment"]["body"]:
            raise WriteBlocked("canonical-owner-request-changed")
    except WriteBlocked:
        raise
    except Exception:
        raise WriteBlocked("canonical-owner-request-unavailable") from None
