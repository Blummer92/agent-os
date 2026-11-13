#!/usr/bin/env python3
"""Stdlib-only fallback postback for CKR6 infrastructure failures (#3691).

Independent of the installable CKR6 bridge; preserves its canonical
non-authorizing result and request-comment correlation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Mapping

COMMAND_PREFIX = "/agent-os ckr6 "
CKR6_RESULT_MARKER = "<!-- agent-os-ckr6-result:v1 -->"
MAX_COMMENT_BYTES = 16 * 1024
COMMENTS_PAGE_SIZE = 100


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
    """Match the bridge's non-authorizing fallback result exactly."""
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
    """Validate owner-only issue-comment ingress; return correlation metadata.

    A top-level PR Conversation comment arrives as an issue_comment event
    whose issue record carries a "pull_request" mapping; the event issue
    number is the PR number. The failure postback target
    (``/repos/{repo}/issues/{n}/comments``) is the same endpoint for both
    kinds, so no target kind is returned.
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
    if not isinstance(issue, Mapping):
        raise ValueError("CKR6 ingress accepts issue comments only")
    pull_request = issue.get("pull_request")
    if pull_request is not None and not isinstance(pull_request, Mapping):
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


# #3951 post-merge live failure (run 43340181423): this reporter failed with
# a bare ``HTTP Error 403: Forbidden`` and the refusal was undiagnosable
# because the HTTPError body and headers were discarded. Surface a bounded,
# sanitized diagnostic instead: status, the GitHub ``message`` field, and
# the ``X-Accepted-GitHub-Permissions`` / ``X-GitHub-Request-Id`` headers.
# Never the token, the request headers, or an unbounded response body.
_MAX_DIAGNOSTIC_MESSAGE_CHARS = 200
_MAX_DIAGNOSTIC_BODY_BYTES = 8192
# GitHub authors the surfaced fields, but a reflected response could still
# echo caller-supplied text, so redact token-shaped substrings and strip
# control characters before anything reaches the log.
_DIAGNOSTIC_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
)


def _sanitize_diagnostic_text(value: str, *, token: str, ascii_only: bool = False) -> str:
    if ascii_only:
        text = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in value)
    else:
        text = "".join(ch if ch.isprintable() else " " for ch in value)
    # Redact the exact credential first: a reflecting server could echo it
    # verbatim inside an otherwise ordinary message field.
    if token:
        text = text.replace(token, "[redacted]")
    for pattern in _DIAGNOSTIC_SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


def _http_failure_diagnostics(exc: BaseException, *, token: str = "") -> str:
    """Bounded, sanitized description of a GitHub transport failure."""
    if type(exc) is not urllib.error.HTTPError:
        return type(exc).__name__
    parts = [f"HTTP {exc.code}"]
    try:
        # Bounded read: at most limit+1 bytes are consumed, and an oversized
        # body is never parsed at all.
        body = exc.read(_MAX_DIAGNOSTIC_BODY_BYTES + 1)
    except Exception:
        body = b""
    message = ""
    if isinstance(body, (bytes, bytearray)) and 0 < len(body) <= _MAX_DIAGNOSTIC_BODY_BYTES:
        try:
            payload = json.loads(bytes(body).decode("utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict) and type(payload.get("message")) is str:
            message = payload["message"]
    if message:
        parts.append(
            f"message={_sanitize_diagnostic_text(message, token=token)[:_MAX_DIAGNOSTIC_MESSAGE_CHARS]!r}"
        )
    headers = getattr(exc, "headers", None)
    if headers is not None:
        for name in ("X-Accepted-GitHub-Permissions", "X-GitHub-Request-Id"):
            value = headers.get(name)
            if type(value) is str and value:
                parts.append(
                    f"{name.lower()}={_sanitize_diagnostic_text(value, token=token, ascii_only=True)[:_MAX_DIAGNOSTIC_MESSAGE_CHARS]!r}"
                )
    return "; ".join(parts)


def _github_request(url: str, token: str, *, body: str | None = None) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "User-Agent": "agent-os-ckr6-failure-postback",
    }
    if body is None:
        return urllib.request.Request(url, headers=headers, method="GET")
    headers["Content-Type"] = "application/json"
    return urllib.request.Request(
        url, data=json.dumps({"body": body}).encode("utf-8"),
        headers=headers, method="POST",
    )


def _existing_result_comment(
    target: str, since: str, request_comment_id: int, token: str
) -> tuple[int | None, str | None]:
    """Return ``(existing result comment id, None)`` or ``(None, reason)``.

    ``(None, None)`` means absence was proven. A reason means it could not be:
    the caller still posts (the bridge's rule -- a duplicate, non-authorizing
    receipt is preferable to leaving the requester without a result) and then
    fails the job visibly. Exactly-once is not claimed: lookup-then-post is not
    atomic.
    """
    if not since:
        return None, "request created_at missing"
    query = urllib.parse.urlencode({"since": since, "per_page": COMMENTS_PAGE_SIZE})
    request = _github_request(f"{target}?{query}", token)
    try:
        comments = _request_json(request)
    except Exception as exc:
        return None, "lookup failed: " + _http_failure_diagnostics(exc, token=token)
    if type(comments) is not list:
        return None, "lookup returned an unexpected response"
    for item in comments:
        if not isinstance(item, Mapping) or type(item.get("id")) is not int:
            continue
        try:
            parsed = parse_result_comment(item.get("body"))
        except (TypeError, ValueError):
            continue
        if parsed.get("request_comment_id") == request_comment_id:
            return item["id"], None
    if len(comments) >= COMMENTS_PAGE_SIZE:
        return None, "lookup may be truncated"
    return None, None


def post_failure_result(
    *,
    event: Mapping[str, object],
    repository: str,
    allowed_actor: str,
    api_url: str,
    token: str,
) -> dict[str, object]:
    """Post or deduplicate the bounded fallback; never expose the token."""
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
    existing, uncertain = _existing_result_comment(target, created_at, request_comment_id, token)
    if existing is None:
        request = _github_request(target, token, body=body)
        try:
            posted = _request_json(request)
        except Exception as exc:
            raise RuntimeError(
                "CKR6 failure postback failed: "
                + _http_failure_diagnostics(exc, token=token)
            ) from exc
        if not isinstance(posted, Mapping) or type(posted.get("id")) is not int:
            raise RuntimeError("CKR6 failure postback returned an unexpected response")
        if uncertain:
            raise RuntimeError(
                f"CKR6 failure postback posted comment {posted['id']} without verified dedupe: {uncertain}"
            )
    return {
        "issue_number": issue_number,
        "request_comment_id": request_comment_id,
        "posted_comment_id": existing if existing is not None else posted["id"],
        "result_status": result["status"],
        "deduplicated": existing is not None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, help="Path to the GitHub event payload JSON")
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
