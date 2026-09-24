"""Pure readback admission for bounded GitHub issue-comment mutations (#2785)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


class CommentPersistenceStatus(str, Enum):
    PERSISTED = "persisted"
    NOT_PERSISTED = "not-persisted"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class CommentReadback:
    comment_id: int
    issue_number: int
    body: str


@dataclass(frozen=True, slots=True)
class CommentPersistenceResult:
    status: CommentPersistenceStatus
    issue_number: int
    content_digest: str
    persisted_comment_id: int | None
    retry_safe: bool
    reason_codes: tuple[str, ...]
    side_effects_performed: bool = False


def content_digest(issue_number: int, body: str) -> str:
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("issue_number must be a positive integer")
    if type(body) is not str or not body.strip():
        raise ValueError("body must be non-empty")
    payload = f"{issue_number}\0{body}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evaluate_comment_persistence(
    *,
    issue_number: int,
    intended_body: str,
    provider_reported_success: bool | None,
    readback_complete: bool,
    comments: tuple[CommentReadback, ...],
) -> CommentPersistenceResult:
    """Require canonical issue + content identity before reporting persistence."""
    digest = content_digest(issue_number, intended_body)
    if type(readback_complete) is not bool or type(comments) is not tuple:
        raise TypeError("readback_complete must be bool and comments must be tuple")
    if any(type(item) is not CommentReadback for item in comments):
        raise TypeError("comments must contain exact CommentReadback values")
    if any(item.issue_number != issue_number for item in comments):
        return CommentPersistenceResult(
            CommentPersistenceStatus.UNCERTAIN, issue_number, digest, None, False,
            ("readback.target-mismatch",),
        )
    matches = tuple(item for item in comments if item.body == intended_body)
    if len(matches) > 1:
        return CommentPersistenceResult(
            CommentPersistenceStatus.UNCERTAIN, issue_number, digest, None, False,
            ("readback.duplicate-content",),
        )
    if len(matches) == 1:
        return CommentPersistenceResult(
            CommentPersistenceStatus.PERSISTED, issue_number, digest, matches[0].comment_id, False,
            ("readback.persisted",),
        )
    if not readback_complete:
        return CommentPersistenceResult(
            CommentPersistenceStatus.UNCERTAIN, issue_number, digest, None, False,
            ("readback.incomplete",),
        )
    if provider_reported_success is True:
        return CommentPersistenceResult(
            CommentPersistenceStatus.NOT_PERSISTED, issue_number, digest, None, True,
            ("provider-success-without-persistence",),
        )
    if provider_reported_success is False:
        return CommentPersistenceResult(
            CommentPersistenceStatus.NOT_PERSISTED, issue_number, digest, None, True,
            ("provider-failure-and-no-persistence",),
        )
    return CommentPersistenceResult(
        CommentPersistenceStatus.UNCERTAIN, issue_number, digest, None, False,
        ("provider-outcome-uncertain",),
    )
