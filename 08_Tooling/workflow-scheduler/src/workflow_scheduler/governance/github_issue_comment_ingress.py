"""Bounded GitHub issue-comment transport parsing for Agent OS Scheduler ingress.

This module validates only the low-trust GitHub event envelope for #1203.  A
successful parse is *transport evidence*, not implementation authorization and
not Scheduler admission.  Canonical authorization, handoff reconstruction,
lease state, exact-head state, dependency readiness, and runtime dispatch remain
owned by their existing Agent OS components.

Two bounded operations are recognized. ``resume`` carries one immutable
``executor-handoff:<sha256>`` identity, exactly as before. ``discover-handoff``
(#1284) carries no argument whatsoever: the repository and issue identity used
downstream are the envelope values validated here, so an integration surface can
locate an existing handoff without any caller-supplied path, store root, handoff
string, or command text reaching the host. Discovery is a locator only; the
resume operation remains the sole execution trigger.

The parser never executes comment text, constructs shell commands from comment
text, performs network I/O, mutates a repository, acquires a lease, or invokes a
Scheduler/executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

INGRESS_SCHEMA_VERSION = "1.1"
MAX_EVENT_BYTES = 1_048_576
MAX_COMMENT_BYTES = 256
_HANDOFF_RE = re.compile(r"executor-handoff:[0-9a-f]{64}", re.ASCII)
_TRIGGER_RE = re.compile(
    r"/agent-os resume (?P<handoff>executor-handoff:[0-9a-f]{64})",
    re.ASCII,
)
#: The #1284 discovery trigger deliberately carries no arguments at all. The
#: repository and issue identity come from the already-validated GitHub event
#: envelope, never from comment prose, so no caller-supplied store root, path,
#: handoff, branch, or command text can reach the host.
_DISCOVERY_TRIGGER = "/agent-os discover-handoff"
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.ASCII)
_ACTOR_RE = re.compile(r"[A-Za-z0-9-]{1,39}", re.ASCII)

IngressStatus = Literal["accepted", "blocked", "ignored"]
IngressOperation = Literal["resume", "discover-handoff"]
IngressReason = Literal[
    "accepted-envelope",
    "event-not-created",
    "pull-request-comment",
    "repository-mismatch",
    "workflow-rerun",
    "actor-not-allowed",
    "actor-evidence-mismatch",
    "malformed-trigger",
    "invalid-event-envelope",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class IssueCommentIngressResult:
    """Non-authorizing, bounded evidence for one GitHub transport event."""

    schema_version: str
    status: IngressStatus
    reason: IngressReason
    repository: str
    issue_number: int | None
    comment_id: int | None
    actor: str | None
    operation_or_none: IngressOperation | None
    handoff_id_or_none: str | None
    logical_trigger_id_or_none: str | None
    run_attempt: int
    execution_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "reason": self.reason,
            "repository": self.repository,
            "issue_number": self.issue_number,
            "comment_id": self.comment_id,
            "actor": self.actor,
            "operation_or_none": self.operation_or_none,
            "handoff_id_or_none": self.handoff_id_or_none,
            "logical_trigger_id_or_none": self.logical_trigger_id_or_none,
            "run_attempt": self.run_attempt,
            "execution_authorized": False,
            "scheduler_invoked": False,
            "side_effects_performed": False,
        }


def _logical_trigger_id(repository: str, issue_number: int, handoff_id: str) -> str:
    material = f"{repository}\0{issue_number}\0{handoff_id}".encode("ascii")
    return f"issue-comment-trigger:{hashlib.sha256(material).hexdigest()}"


def _discovery_trigger_id(repository: str, issue_number: int) -> str:
    """Derive the replay-stable logical identity of one discovery request.

    Discovery has no handoff to bind, so identity comes from the repository and
    issue alone. Two identical discovery comments therefore share one logical
    trigger identity, exactly as duplicate resume comments already do.
    """
    material = f"{repository}\0{issue_number}".encode("ascii")
    return f"issue-comment-discovery-trigger:{hashlib.sha256(material).hexdigest()}"


def _result(
    *,
    status: IngressStatus,
    reason: IngressReason,
    repository: str,
    run_attempt: int,
    issue_number: int | None = None,
    comment_id: int | None = None,
    actor: str | None = None,
    operation: IngressOperation | None = None,
    handoff_id: str | None = None,
) -> IssueCommentIngressResult:
    logical_id = None
    if issue_number is not None:
        if handoff_id is not None:
            logical_id = _logical_trigger_id(repository, issue_number, handoff_id)
        elif operation == "discover-handoff":
            logical_id = _discovery_trigger_id(repository, issue_number)
    return IssueCommentIngressResult(
        schema_version=INGRESS_SCHEMA_VERSION,
        status=status,
        reason=reason,
        repository=repository,
        issue_number=issue_number,
        comment_id=comment_id,
        actor=actor,
        operation_or_none=operation,
        handoff_id_or_none=handoff_id,
        logical_trigger_id_or_none=logical_id,
        run_attempt=run_attempt,
    )


def admit_issue_comment_event(
    event: object,
    *,
    expected_repository: str,
    allowed_actor: str,
    run_attempt: int,
) -> IssueCommentIngressResult:
    """Validate one ``issue_comment`` event without granting execution authority."""

    if not _REPOSITORY_RE.fullmatch(expected_repository):
        raise ValueError("expected_repository must use owner/name syntax")
    if not _ACTOR_RE.fullmatch(allowed_actor):
        raise ValueError("allowed_actor must use GitHub login syntax")
    if type(run_attempt) is not int or run_attempt < 1:
        raise ValueError("run_attempt must be a positive integer")

    if type(event) is not dict:
        return _result(
            status="blocked",
            reason="invalid-event-envelope",
            repository=expected_repository,
            run_attempt=run_attempt,
        )

    action = event.get("action")
    repository = event.get("repository")
    issue = event.get("issue")
    comment = event.get("comment")
    sender = event.get("sender")
    if not all(type(value) is dict for value in (repository, issue, comment, sender)):
        return _result(
            status="blocked",
            reason="invalid-event-envelope",
            repository=expected_repository,
            run_attempt=run_attempt,
        )

    repo_name = repository.get("full_name")
    issue_number = issue.get("number")
    comment_id = comment.get("id")
    comment_user = comment.get("user")
    sender_login = sender.get("login")
    if (
        type(repo_name) is not str
        or type(issue_number) is not int
        or issue_number < 1
        or type(comment_id) is not int
        or comment_id < 1
        or type(comment_user) is not dict
        or type(sender_login) is not str
    ):
        return _result(
            status="blocked",
            reason="invalid-event-envelope",
            repository=expected_repository,
            run_attempt=run_attempt,
        )

    comment_login = comment_user.get("login")
    actor = comment_login if type(comment_login) is str else None

    if action != "created":
        return _result(
            status="blocked",
            reason="event-not-created",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )
    if "pull_request" in issue:
        return _result(
            status="ignored",
            reason="pull-request-comment",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )
    if repo_name != expected_repository:
        return _result(
            status="blocked",
            reason="repository-mismatch",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )
    if run_attempt != 1:
        return _result(
            status="blocked",
            reason="workflow-rerun",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )
    if actor != allowed_actor:
        return _result(
            status="blocked",
            reason="actor-not-allowed",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )
    if sender_login != actor:
        return _result(
            status="blocked",
            reason="actor-evidence-mismatch",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )

    body = comment.get("body")
    if type(body) is not str or len(body.encode("utf-8")) > MAX_COMMENT_BYTES:
        return _result(
            status="ignored",
            reason="malformed-trigger",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )
    if body == _DISCOVERY_TRIGGER:
        # Discovery carries no caller-supplied argument. Repository and issue
        # identity are the envelope values already validated above, so comment
        # prose can never name a store root, path, handoff, or command.
        return _result(
            status="accepted",
            reason="accepted-envelope",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
            operation="discover-handoff",
        )

    match = _TRIGGER_RE.fullmatch(body)
    if match is None:
        return _result(
            status="ignored",
            reason="malformed-trigger",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )
    handoff_id = match.group("handoff")
    if _HANDOFF_RE.fullmatch(handoff_id) is None:
        return _result(
            status="ignored",
            reason="malformed-trigger",
            repository=expected_repository,
            run_attempt=run_attempt,
            issue_number=issue_number,
            comment_id=comment_id,
            actor=actor,
        )
    return _result(
        status="accepted",
        reason="accepted-envelope",
        repository=expected_repository,
        run_attempt=run_attempt,
        issue_number=issue_number,
        comment_id=comment_id,
        actor=actor,
        operation="resume",
        handoff_id=handoff_id,
    )


def _read_event(path: Path) -> object:
    if path.stat().st_size > MAX_EVENT_BYTES:
        raise ValueError("event payload exceeds byte bound")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_result(path: Path, result: IssueCommentIngressResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
    path.write_text(encoded + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-actor", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = admit_issue_comment_event(
        _read_event(args.event),
        expected_repository=args.repository,
        allowed_actor=args.allowed_actor,
        run_attempt=args.run_attempt,
    )
    _write_result(args.output, result)
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
