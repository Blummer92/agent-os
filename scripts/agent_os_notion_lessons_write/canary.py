"""One exact-head, owner-authorized PR-open canary before default-branch activation.

This is a finite acceptance condition for #3305, not a general PR write trigger.
Current GitHub authorization and workflow-run evidence are the existing ledger;
no queue, scheduler, retry system, state store or credential path is introduced.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping

from .admission import AdmittedRequest, OWNER_ID, REPOSITORY, REPOSITORY_ID, WriteBlocked
from .catalog import ISSUE_NUMBER, LESSON, REQUEST_ID, WRITABLE_TYPES
from .currentness import _get

BRANCH = "issue-3305-lessons-write-20261006"
AUTH_COMMENT_ID = 6026930367
AUTH_MARKER = "\nAgent OS Lessons canary binding:\n"
WORKFLOW_PATH = ".github/workflows/agent-os-notion-lessons-write.yml"


def admit_canary(event: dict, *, event_name: str, ref: str, workflow_ref: str,
                 run_attempt: str, run_id: str) -> AdmittedRequest:
    pr = event.get("pull_request", {})
    number = pr.get("number")
    head = pr.get("head", {})
    sha = head.get("sha")
    if (event_name, event.get("action"), run_attempt) != ("pull_request", "opened", "1"):
        raise WriteBlocked("first-pr-open-canary-only")
    if type(number) is not int or number < 1 or type(sha) is not str or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise WriteBlocked("canary-pr-identity-required")
    expected_ref = f"refs/pull/{number}/merge"
    if ref != expected_ref or workflow_ref != f"{REPOSITORY}/{WORKFLOW_PATH}@{expected_ref}":
        raise WriteBlocked("canary-workflow-identity-mismatch")
    if (event.get("repository", {}).get("id"), event.get("repository", {}).get("full_name")) != (REPOSITORY_ID, REPOSITORY):
        raise WriteBlocked("canary-repository-mismatch")
    if (head.get("repo", {}).get("id"), head.get("repo", {}).get("full_name"), head.get("ref")) != (REPOSITORY_ID, REPOSITORY, BRANCH):
        raise WriteBlocked("fixed-owner-canary-branch-required")
    if (pr.get("user", {}).get("id"), pr.get("user", {}).get("login"), pr.get("draft"), pr.get("base", {}).get("ref")) != (OWNER_ID, "Blummer92", True, "main"):
        raise WriteBlocked("owner-draft-canary-required")
    # Reacquire mutable PR, ordinary issue, and exact owner authorization.
    current = _get(f"/pulls/{number}")
    if current.get("state") != "open" or current.get("merged") is True or current.get("draft") is not True:
        raise WriteBlocked("current-draft-canary-required")
    if (current.get("head", {}).get("sha"), current.get("head", {}).get("ref")) != (sha, BRANCH):
        raise WriteBlocked("canary-head-changed")
    if _get(f"/issues/{ISSUE_NUMBER}").get("state") != "open":
        raise WriteBlocked("open-canonical-issue-required")
    comment = _get(f"/issues/comments/{AUTH_COMMENT_ID}")
    if comment.get("user", {}).get("id") != OWNER_ID or comment.get("issue_url") != f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}":
        raise WriteBlocked("canonical-canary-authorization-required")
    body = comment.get("body", "")
    if type(body) is not str or body.count(AUTH_MARKER) != 1:
        raise WriteBlocked("exact-canary-authorization-required")
    try:
        binding = json.loads(body.split(AUTH_MARKER)[1])
    except (TypeError, ValueError):
        raise WriteBlocked("exact-canary-authorization-required") from None
    expected = {"repository": REPOSITORY, "issue_number": ISSUE_NUMBER, "branch": BRANCH,
                "head_sha": sha, "request_id": REQUEST_ID, "max_write_attempts": 1,
                "operation": "one-create-or-update-then-canonical-readback",
                "fields": list(WRITABLE_TYPES)}
    if binding != expected:
        raise WriteBlocked("canary-authorization-head-or-scope-mismatch")
    # Reuse canonical Actions history for this exact head. Any other run of
    # this canary (including a second PR on this head) consumes/refuses replay.
    history = _get(f"/actions/runs?event=pull_request&head_sha={sha}&per_page=100")
    runs = history.get("workflow_runs")
    if type(runs) is not list or type(history.get("total_count")) is not int or history["total_count"] > 100:
        raise WriteBlocked("canary-run-history-incomplete")
    matching = [run for run in runs if run.get("path") == WORKFLOW_PATH and run.get("head_sha") == sha]
    if not run_id.isdecimal() or len(matching) != 1 or matching[0].get("id") != int(run_id):
        raise WriteBlocked("canary-replay-or-run-identity-mismatch")
    if matching[0].get("run_attempt") != 1 or matching[0].get("event") != "pull_request":
        raise WriteBlocked("canary-replay-refused")
    return AdmittedRequest(AUTH_COMMENT_ID)


def execute_canary(request: AdmittedRequest, client) -> dict:
    from .admission import notion_id
    from .writer import execute
    # The separately approved canary covers this exact reviewed lesson/field
    # map's create OR update. Resolve the current exact target/revision, then
    # let the same writer independently verify schema, reconciliation and CAS
    # evidence. This adds zero mutations and never selects a different lesson.
    rows = client.find_exact(LESSON["Lesson Learned"])
    if not isinstance(rows, Mapping) or rows.get("has_more") is not False or type(rows.get("results")) is not list or len(rows["results"]) > 1:
        raise WriteBlocked("canary-reconciliation-ambiguous")
    if rows["results"]:
        row = rows["results"][0]
        request = AdmittedRequest(request.comment_id, notion_id(row.get("id")), row.get("last_edited_time"))
    return execute(request, client)
