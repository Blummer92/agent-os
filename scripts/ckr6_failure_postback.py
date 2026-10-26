#!/usr/bin/env python3
"""Stdlib-only CKR6 infrastructure-failure result postback (#3691).

The CKR6 bridge (``agent_os_execution_service.ckr6_github_bridge``) posts a
bounded result comment for every request it can classify or execute, and
converts envelope errors into bounded ``rejected`` receipts. It cannot report
failures that happen *before* it runs -- checkout, Python setup, or the pip
install of the Agent OS runtime itself -- because the workflow's ``execute``
job is skipped when ``classify`` fails, and its postback step imports the
very package whose installation may have failed (live proof: run
39665727697, where a missing ``agent-os-navigation-registry`` distribution
failed classification and no result comment was ever posted).

This reporter closes exactly that hole. The workflow's ``report-failure``
job runs it when the ``classify`` or ``execute`` job fails. It deliberately
imports only the Python standard library and no project package, so it works
precisely when the runtime installation did not. It validates the same
ingress identity the bridge validates (repository, issue-not-PR, authorized
actor, exact command prefix), then posts the bridge's existing bounded
fallback result -- ``status: manual-review``,
``reason_codes: ["ckr6-result-unavailable"]``, every authority flag false --
under the canonical ``agent-os-ckr6-result:v1`` marker, correlated with
``request_comment_id`` and deduplicated per request, mirroring
``ckr6_github_bridge.postback_result_comment`` semantics. It creates no
CKR6 decision, no execution authority, and no other GitHub write.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Mapping

COMMAND_PREFIX = "/agent-os ckr6 "
CKR6_RESULT_MARKER = "<!-- agent-os-ckr6-result:v1 -->"
MAX_COMMENT_BYTES = 16 * 1024


def _canonical_result_json(payload: Mapping[str, object]) -> str:
    # Identical to the bridge's canonical form (ensure_ascii=False,
    # allow_nan=False): dedupe parses bridge-posted results, whose payloads
    # may carry non-ASCII lesson/handoff text, and must recompute the exact
    # same canonical string or the parse -- and therefore dedupe -- fails.
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def fallback_result(repository: str, issue_number: int) -> dict[str, object]:
    """Bounded manual-review result when no CKR6 result evidence exists.

    Mirrors ``ckr6_github_bridge._fallback_result`` field-for-field: the
    host must receive an explicit terminal signal rather than silence.
    """
    return {
        "operation": "unknown",
        "repository": repository,
        "issue_number": issue_number,
        "status": "manual-review",
        "reason_codes": ["ckr6-result-unavailable"],
        "selected_lesson_ids": [],
        "canonical_github_refs": [],
        "substantial_hypothesis_admissible": False,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }


def serialize_result_comment(
    result: Mapping[str, object], *, request_comment_id: int
) -> str:
    """Marker plus one line of canonical compact JSON (bridge format)."""
    if type(request_comment_id) is not int or request_comment_id < 1:
        raise ValueError("request_comment_id must be a positive integer")
    payload = {**result, "request_comment_id": request_comment_id}
    return CKR6_RESULT_MARKER + "\n" + _canonical_result_json(payload)


def parse_result_comment(body: object) -> dict[str, object]:
    """Parse a canonical CKR6 result comment; raise ValueError otherwise."""
    if type(body) is not str:
        raise ValueError("CKR6 result comment must be text")
    prefix = CKR6_RESULT_MARKER + "\n"
    if not body.startswith(prefix) or body.count("\n") != 1:
        raise ValueError("CKR6 result comment must contain exactly two lines")
    serialized = body[len(prefix) :]
    payload = json.loads(serialized)
    if type(payload) is not dict or _canonical_result_json(payload) != serialized:
        raise ValueError("CKR6 result payload must be canonical compact JSON")
    return payload


def validate_event(
    event: Mapping[str, object], *, expected_repository: str, allowed_actor: str
) -> tuple[int, int, str]:
    """Return (issue_number, request_comment_id, comment_created_at).

    Applies the same ingress identity checks as the bridge's
    ``envelope_from_event``: event repository must match, the comment must
    be on an issue (not a pull request), the actor must be the authorized
    owner, and the body must carry the exact CKR6 command prefix. Raises
    ValueError on any mismatch; nothing is posted for ineligible events.
    """
    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")
    repository = event.get("repository")
    issue = event.get("issue")
    comment = event.get("comment")
    if (
        not isinstance(repository, Mapping)
        or repository.get("full_name") != expected_repository
    ):
        raise ValueError("event repository identity mismatch")
    if not isinstance(issue, Mapping) or "pull_request" in issue:
        raise ValueError("CKR6 ingress accepts issue comments only")
    if type(issue.get("number")) is not int or issue["number"] < 1:
        raise ValueError("event issue number missing")
    if not isinstance(comment, Mapping):
        raise ValueError("comment evidence missing")
    user = comment.get("user")
    if not isinstance(user, Mapping) or user.get("login") != allowed_actor:
        raise ValueError("comment actor is not authorized for CKR6 ingress")
    if type(comment.get("id")) is not int or comment["id"] < 1:
        raise ValueError("event request comment id missing")
    body = comment.get("body")
    if type(body) is not str or len(body.encode("utf-8")) > MAX_COMMENT_BYTES:
        raise ValueError("comment body missing or oversized")
    if not body.startswith(COMMAND_PREFIX):
        raise ValueError("comment does not use the CKR6 command envelope")
    created_at = comment.get("created_at")
    return issue["number"], comment["id"], created_at if type(created_at) is str else ""


def _request_json(request: urllib.request.Request) -> object:
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _existing_result_comment(
    target: str, since: str, request_comment_id: int, token: str
) -> int | None:
    """Return an already-posted result comment id for this request, if any.

    Bounded to one page of comments created since the request. Lookup
    failure is not evidence of absence: the caller still posts, preferring
    a duplicate receipt over silence (bridge semantics).
    """
    if not since:
        return None
    query = urllib.parse.urlencode({"since": since, "per_page": 100})
    request = urllib.request.Request(
        f"{target}?{query}",
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "User-Agent": "agent-os-ckr6-failure-postback",
        },
    )
    try:
        comments = _request_json(request)
    except Exception:
        return None
    if type(comments) is not list:
        return None
    for item in comments:
        if not isinstance(item, Mapping) or type(item.get("id")) is not int:
            continue
        try:
            parsed = parse_result_comment(item.get("body"))
        except (TypeError, ValueError):
            continue
        if parsed.get("request_comment_id") == request_comment_id:
            return item["id"]
    return None


def post_failure_result(
    *,
    event: Mapping[str, object],
    repository: str,
    allowed_actor: str,
    api_url: str,
    token: str,
) -> dict[str, object]:
    """Validate the event and post exactly one correlated fallback result.

    Fail-closed: validation errors and transport errors raise instead of
    reporting a posted result. The token is never logged or embedded in
    returned evidence.
    """
    if type(api_url) is not str or not api_url.startswith("https://"):
        raise ValueError("api_url must be an https URL")
    if type(token) is not str or not token:
        raise ValueError("GitHub token is required for failure postback")
    issue_number, request_comment_id, created_at = validate_event(
        event, expected_repository=repository, allowed_actor=allowed_actor
    )
    result = fallback_result(repository, issue_number)
    body = serialize_result_comment(result, request_comment_id=request_comment_id)
    target = f"{api_url.rstrip('/')}/repos/{repository}/issues/{issue_number}/comments"
    existing = _existing_result_comment(target, created_at, request_comment_id, token)
    if existing is None:
        request = urllib.request.Request(
            target,
            data=json.dumps({"body": body}).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "User-Agent": "agent-os-ckr6-failure-postback",
            },
        )
        try:
            posted = _request_json(request)
        except Exception as exc:
            raise RuntimeError(
                f"CKR6 failure postback failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(posted, Mapping) or type(posted.get("id")) is not int:
            raise RuntimeError("CKR6 failure postback returned an unexpected response")
    return {
        "issue_number": issue_number,
        "request_comment_id": request_comment_id,
        "posted_comment_id": existing if existing is not None else posted["id"],
        "result_status": result["status"],
        "deduplicated": existing is not None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event", required=True, help="Path to the GitHub event payload JSON"
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-actor", required=False, default="Blummer92")
    parser.add_argument(
        "--api-url",
        required=False,
        default=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    args = parser.parse_args(argv)

    event = json.loads(Path(args.event).read_text(encoding="utf-8"))
    if not isinstance(event, Mapping):
        raise ValueError("event payload must be an object")
    outcome = post_failure_result(
        event=event,
        repository=args.repository,
        allowed_actor=args.allowed_actor,
        api_url=args.api_url,
        token=os.environ.get("GITHUB_TOKEN", ""),
    )
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
