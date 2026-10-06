"""Two exact public GitHub reads bind still-current owner intent before Notion.

The existing repository is public. This finite check needs no GitHub token or
permission change and cannot dispatch an arbitrary endpoint or publish data.
"""
from __future__ import annotations

import json
import urllib.request

from .admission import AdmittedRequest, REPOSITORY, WriteBlocked, admit
from .catalog import ISSUE_NUMBER


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
        issue = _get(f"/issues/{ISSUE_NUMBER}")
        comment = _get(f"/issues/comments/{request.comment_id}")
        if comment.get("issue_url") != f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}":
            raise WriteBlocked("canonical-comment-target-mismatch")
        current = {**event, "issue": issue, "comment": comment}
        if admit(current, **context) != request or comment.get("body") != event["comment"]["body"]:
            raise WriteBlocked("canonical-owner-request-changed")
    except WriteBlocked:
        raise
    except Exception:
        raise WriteBlocked("canonical-owner-request-unavailable") from None
