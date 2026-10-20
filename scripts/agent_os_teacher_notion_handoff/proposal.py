"""Review-only teacher planning ingress. It has no Notion client or execution path.

The accepted command is deliberately *not* the live /agent-os notion-write
command. No field in this module may authorize a provider mutation.
"""
from __future__ import annotations
import re
from typing import Any

REPOSITORY = "Blummer92/agent-os"
REPOSITORY_ID = 1289370915
OWNER_ID = 32861845
COMMAND = "/agent-os teacher-notion-propose"
CATEGORIES = frozenset({"planning-note", "lesson-candidate", "working-knowledge", "handoff-note"})
REQUEST_ID = re.compile(r"[a-z](?:[a-z0-9]|-(?=[a-z0-9])){2,39}\Z", re.ASCII)

class ProposalBlocked(ValueError):
    """Finite fail-closed refusal without echoing untrusted request contents."""

def _record(category: str, request_id: str) -> dict[str, Any]:
    return {
        "schema_version": "agent-os-teacher-notion-proposal/1.0",
        "status": "review-required",
        "category": category,
        "request_id": request_id,
        "write_mode": "draft",
        "github_handoff_only": True,
        "notion_target_verified": False,
        "external_write_authorized": False,
        "notion_write_performed": False,
        "secret_dispatch_authorized": False,
        "execution_authorized": False,
    }

def build_proposal(category: object, request_id: object) -> dict[str, Any]:
    """Make a public-safe, finite GitHub review request; never include note text."""
    if type(category) is not str or category not in CATEGORIES:
        raise ProposalBlocked("request-category-not-allowlisted")
    if type(request_id) is not str or REQUEST_ID.fullmatch(request_id) is None:
        raise ProposalBlocked("request-id-invalid")
    proposal = _record(category, request_id)
    proposal["comment"] = f"{COMMAND} {category} {request_id}"
    return proposal

def inspect_github_comment(
    event: object, *, event_name: str, ref: str, run_attempt: str
) -> dict[str, Any]:
    """Validate GitHub-created evidence for review only, never write admission.

    Any future writer must re-fetch canonical comment identity, verify live
    destination/schema/field authority and approved content, then read back the
    exact mutation. Separate workflow/secret authorization is required.
    """
    if (event_name, ref, run_attempt) != ("issue_comment", "refs/heads/main", "1"):
        raise ProposalBlocked("untrusted-event-context")
    if not isinstance(event, dict) or event.get("action") != "created":
        raise ProposalBlocked("created-comment-required")
    repo = event.get("repository")
    if not isinstance(repo, dict) or (repo.get("full_name"), repo.get("id")) != (REPOSITORY, REPOSITORY_ID):
        raise ProposalBlocked("repository-mismatch")
    issue = event.get("issue")
    if not isinstance(issue, dict) or type(issue.get("number")) is not int or issue["number"] < 1 or "pull_request" in issue:
        raise ProposalBlocked("ordinary-issue-required")
    comment = event.get("comment")
    if not isinstance(comment, dict) or type(comment.get("id")) is not int or comment["id"] < 1:
        raise ProposalBlocked("comment-identity-required")
    actor = comment.get("user")
    if not isinstance(actor, dict) or (actor.get("id"), actor.get("login"), actor.get("type")) != (OWNER_ID, "Blummer92", "User"):
        raise ProposalBlocked("owner-comment-required")
    if not isinstance(comment.get("created_at"), str) or comment["created_at"] != comment.get("updated_at"):
        raise ProposalBlocked("edited-comment-refused")
    body = comment.get("body")
    if type(body) is not str or len(body) > 120 or not body.startswith(COMMAND + " "):
        raise ProposalBlocked("finite-comment-required")
    parts = body.split(" ")
    if len(parts) != 4 or parts[:2] != ["/agent-os", "teacher-notion-propose"]:
        raise ProposalBlocked("finite-comment-required")
    result = build_proposal(parts[2], parts[3])
    if body != result["comment"]:
        raise ProposalBlocked("noncanonical-comment")
    result.pop("comment")
    result["issue_number"] = issue["number"]
    result["comment_id"] = comment["id"]
    return result
