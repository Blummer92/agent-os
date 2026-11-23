"""Compose a bounded CKR6 command without publishing or granting authority.

Reuse the canonical GitHub CKR6 parser; never duplicate its field vocabulary,
materiality classification, or mutation/merge authorization policy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from . import ckr6_github_bridge as bridge
from .ckr6_mutation_gate import _HEAD_REFERENCE_RE, _PR_TARGET_RE

_MAX_INPUT_CHARS = bridge.MAX_COMMENT_BYTES * 4
_HEAD = re.compile(r"[0-9a-fA-F]{40}\Z")
_BOUNDARY_OPERATIONS = frozenset({"issue-start", "failed-repair"})


class ComposeBlocked(ValueError):
    """Content-free explanation for a pre-publication STOP."""


def compose_request_comment(
    payload: Mapping[str, object], *, pr_number: int | None = None,
    head_sha: str | None = None,
) -> str:
    """Return one syntactically valid command; never post or authorize it.

    When targeting a PR, both pr_number and head_sha are mandatory.
    task_reference must bind the exact PR and head itself; never invent,
    truncate, or rewrite task signals.
    """
    if type(payload) is not dict:
        raise ComposeBlocked("envelope-invalid")
    try:
        envelope = bridge.parse_envelope(payload)
    except (ValueError, TypeError) as exc:
        reason = "envelope-field-oversized" if "oversized" in str(exc) else "envelope-invalid"
        raise ComposeBlocked(reason) from None
    if envelope.operation not in _BOUNDARY_OPERATIONS:
        raise ComposeBlocked("operation-not-boundary")

    if (pr_number is None) != (head_sha is None):
        raise ComposeBlocked("pr-binding-incomplete")
    if pr_number is not None:
        if type(pr_number) is not int or pr_number < 1:
            raise ComposeBlocked("pr-number-invalid")
        if type(head_sha) is not str or _HEAD.fullmatch(head_sha) is None:
            raise ComposeBlocked("pr-head-invalid")
        if envelope.repository != bridge.GITHUB_REPOSITORY:
            raise ComposeBlocked("pr-repository-mismatch")
        if envelope.issue_number != pr_number:
            raise ComposeBlocked("pr-target-mismatch")
        mentioned_prs = [
            int(match.group(1) or match.group(2))
            for match in _PR_TARGET_RE.finditer(envelope.task_reference)
        ]
        if mentioned_prs != [pr_number]:
            raise ComposeBlocked("pr-reference-unbound-or-ambiguous")
        mentioned_heads = _HEAD_REFERENCE_RE.findall(envelope.task_reference)
        if len(mentioned_heads) != 1 or mentioned_heads[0].lower() != head_sha.lower():
            raise ComposeBlocked("pr-head-unbound-or-ambiguous")

    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"),
            sort_keys=True, allow_nan=False,
        )
        body = bridge.COMMAND_PREFIX + encoded
        if len(body.encode("utf-8")) > bridge.MAX_COMMENT_BYTES:
            raise ComposeBlocked("comment-oversized")
        if bridge.parse_envelope(json.loads(encoded)) != envelope:
            raise ComposeBlocked("envelope-roundtrip-mismatch")
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ComposeBlocked):
            raise
        raise ComposeBlocked("envelope-serialization-invalid") from None
    return body


def _unique_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in items:
        if key in out:
            raise ComposeBlocked("duplicate-json-field")
        out[key] = value
    return out


def _load_payload(path: str) -> dict[str, object]:
    try:
        if path == "-":
            raw = sys.stdin.read(_MAX_INPUT_CHARS + 1)
        else:
            with Path(path).open("r", encoding="utf-8") as source:
                raw = source.read(_MAX_INPUT_CHARS + 1)
    except (OSError, UnicodeError):
        raise ComposeBlocked("input-unreadable") from None
    if len(raw) > _MAX_INPUT_CHARS:
        raise ComposeBlocked("input-oversized")
    try:
        obj = json.loads(
            raw, object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ComposeBlocked("invalid-json")),
        )
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise ComposeBlocked("invalid-json") from None
    if type(obj) is not dict:
        raise ComposeBlocked("envelope-invalid")
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight one CKR6 request; never post to GitHub",
    )
    parser.add_argument("--input", default="-", help="JSON file or '-' for stdin")
    parser.add_argument("--pr-number", type=int, default=None)
    parser.add_argument("--head-sha", default=None)
    args = parser.parse_args(argv)
    try:
        body = compose_request_comment(
            _load_payload(args.input),
            pr_number=args.pr_number,
            head_sha=args.head_sha,
        )
    except ComposeBlocked as exc:
        print(f"CKR6 request blocked: {exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(body.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
